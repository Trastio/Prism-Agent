"""工具注册中心 — 装饰器模式 + Pydantic Schema 生成

改进点：
- 装饰器 @tool 注册，新增工具不需要手写 import + register
- Pydantic BaseModel 定义参数 → 自动生成精确 JSON Schema
- 支持按场景（chat/compare/decision/market）启用/禁用工具子集
"""
from __future__ import annotations
import inspect
import json
import types
import typing
import warnings
from typing import Callable, Awaitable, Optional
from dataclasses import dataclass, field

# 尝试用 Pydantic 生成 Schema，失败则回退到 docstring 解析
try:
    from pydantic import BaseModel, create_model, Field as PydanticField
    _HAS_PYDANTIC = True
except ImportError:
    _HAS_PYDANTIC = False


def _is_optional_annotation(annotation) -> bool:
    """检查 annotation 是否为 Optional[X] 或 X | None 类型的联合"""
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        args = typing.get_args(annotation)
        return type(None) in args
    return False


def _unwrap_optional(annotation):
    """从 Optional[X] 或 X | None 中提取 X 的类型"""
    if not _is_optional_annotation(annotation):
        return annotation
    args = [a for a in typing.get_args(annotation) if a is not type(None)]
    return args[0] if args else str


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict
    func: Callable
    tags: set = field(default_factory=set)  # e.g. {"chat", "compare", "decision"}

    @classmethod
    def from_function(cls, func: Callable, tags: set | None = None) -> "ToolDef":
        name = func.__name__
        description = (func.__doc__ or "").strip()
        sig = inspect.signature(func)
        properties = {}
        required_params = []

        # 从 docstring 提取参数描述
        param_docs = {}
        if func.__doc__:
            for line in func.__doc__.split("\n"):
                stripped = line.strip()
                if stripped.startswith(":param"):
                    parts = stripped.split(":", 2)
                    if len(parts) >= 3:
                        pname = parts[1].replace("param", "").strip()
                        param_docs[pname] = parts[2].strip()

        # 尝试 Pydantic Schema 生成
        if _HAS_PYDANTIC:
            try:
                fields = {}
                for pname, param in sig.parameters.items():
                    if pname in ("self", "cls"):
                        continue
                    py_type, desc = cls._infer_python_type(param.annotation), param_docs.get(pname, pname)
                    default = param.default if param.default is not inspect.Parameter.empty else ...
                    fields[pname] = (py_type, PydanticField(default=default, description=desc))
                if fields:
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", message=".*protected namespace.*")
                        model = create_model(f"{name}_params", **fields)
                    schema = model.model_json_schema()
                    parameters = schema
                    return cls(name=name, description=description, parameters=parameters,
                               func=func, tags=set(tags or []))
            except Exception:
                pass  # 回退到手动解析

        # Fallback: 手动类型推断
        for pname, param in sig.parameters.items():
            if pname in ("self", "cls"):
                continue
            items_type = None
            py_type = cls._infer_json_type(param.annotation)
            if isinstance(py_type, tuple):
                py_type, items_type = py_type
            prop = {"type": py_type, "description": param_docs.get(pname, pname)}
            if items_type:
                prop["items"] = {"type": items_type}
            properties[pname] = prop
            if param.default is inspect.Parameter.empty:
                required_params.append(pname)

        parameters = {"type": "object", "properties": properties}
        if required_params:
            parameters["required"] = required_params

        return cls(name=name, description=description, parameters=parameters,
                   func=func, tags=set(tags or []))

    @staticmethod
    def _infer_python_type(annotation) -> type:
        if annotation is inspect.Parameter.empty:
            return str
        annotation = _unwrap_optional(annotation)
        origin = typing.get_origin(annotation)
        if origin is list:
            return list
        if origin is dict:
            return dict
        if annotation is int:
            return int
        if annotation is float:
            return float
        if annotation is bool:
            return bool
        return str

    @staticmethod
    def _infer_json_type(annotation):
        if annotation is inspect.Parameter.empty:
            return "string"
        annotation = _unwrap_optional(annotation)
        if annotation is int:
            return "integer"
        if annotation is float:
            return "number"
        if annotation is bool:
            return "boolean"
        origin = typing.get_origin(annotation)
        if origin is list:
            args = typing.get_args(annotation)
            if args:
                inner = ToolDef._infer_json_type(args[0])
                return ("array", inner if isinstance(inner, str) else "string")
            return ("array", "string")
        if origin is dict:
            return "object"
        return "string"

    def to_openai_tool(self) -> dict:
        # Pydantic schema 已经包含完整结构，直接返回
        if "properties" in self.parameters and "$defs" not in self.parameters:
            return {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": self.parameters,
                },
            }
        # Pydantic 生成的 schema 可能有多余字段，标准化
        params = {"type": "object", "properties": self.parameters.get("properties", {})}
        if "required" in self.parameters:
            params["required"] = self.parameters["required"]
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params,
            },
        }


class ToolRegistry:
    """工具注册中心。

    用法：
        registry = ToolRegistry()

        @registry.register(tags={"chat", "decision"})
        async def search_cars(...): ...
    """

    def __init__(self):
        self._tools: dict[str, ToolDef] = {}

    def register(self, func: Callable = None, *, tags: set | None = None):
        """装饰器：@registry.register(tags={"chat"}) 注册工具"""
        if func is None:
            return lambda f: self.register(f, tags=tags)

        td = ToolDef.from_function(func, tags=tags)
        if td.name in self._tools:
            raise ValueError(f"Tool '{td.name}' already registered")
        self._tools[td.name] = td
        return func

    def get_function(self, name: str) -> Optional[Callable[..., Awaitable[dict]]]:
        td = self._tools.get(name)
        return td.func if td else None

    def get_tool_descriptions(self, mode: str = "chat") -> list[dict]:
        """获取工具列表，可按场景过滤"""
        tools = []
        for td in self._tools.values():
            if not td.tags or mode in td.tags or "all" in td.tags:
                tools.append(td.to_openai_tool())
        return tools

    def get_all_descriptions(self) -> list[dict]:
        return [td.to_openai_tool() for td in self._tools.values()]

    def __len__(self):
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


# 全局实例
tool_registry = ToolRegistry()
