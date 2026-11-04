#!/usr/bin/env python3
"""G-1 防回潮：扫描 api/ 下函数体内 import，期望 0 命中（# noqa: inline-import 可豁免）。

口径：api/ 全口径（禁止函数内 import 跨分支使用致 UnboundLocalError 的反模式）。
范围：仅 api/；tests/ 排除；pipeline/scripts/utils/models/ 不在口径内。
豁免：import 行尾加 `# noqa: inline-import` 注释则跳过（用于合理的延迟加载）。
退出码：0 命中=通过，>0=失败。
"""
import ast
import sys
from pathlib import Path

NOQA_TAG = "noqa: inline-import"
TARGET_DIR = Path(__file__).resolve().parent.parent / "api"


def _is_noqa(node: ast.stmt, source_lines: list[str]) -> bool:
    """判断 import 节点所在行是否含 noqa: inline-import 注释。"""
    line = source_lines[node.lineno - 1] if node.lineno - 1 < len(source_lines) else ""
    return NOQA_TAG in line


def _walk_functions(tree: ast.Module):
    """遍历所有函数定义（含嵌套），产出 (func_node) 。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _function_imports(func: ast.FunctionDef, source_lines: list[str]):
    """func 直接体内的 import 语句（不下钻嵌套函数——嵌套函数由 _walk_functions 单独遍历负责）。"""
    for child in ast.iter_child_nodes(func):
        # 遇到嵌套函数定义：其体内的 import 归嵌套函数自己报，不下钻
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            if _is_noqa(child, source_lines):
                continue
            yield child
        # 递归下钻非函数子节点（if/for/try/with 等块内的 import 仍属本函数）
        yield from _walk_non_function_body(child, source_lines)


def _walk_non_function_body(node: ast.AST, source_lines: list[str]):
    """递归遍历 node 的子节点，但遇到嵌套函数定义时不下钻其体（只看本函数直接控制流块）。"""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            if _is_noqa(child, source_lines):
                continue
            yield child
        yield from _walk_non_function_body(child, source_lines)


def check_file(path: Path) -> list[str]:
    """返回该文件的所有违规（函数内 import 且无 noqa）。"""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return [f"{path}: 语法错误 {e}"]
    lines = source.splitlines()
    violations = []
    for func in _walk_functions(tree):
        for imp in _function_imports(func, lines):
            # ImportFrom 报模块路径+导入名（from X import Y）；Import 报 import 名
            if isinstance(imp, ast.ImportFrom):
                mod = imp.module or ""
                names = ", ".join(a.name for a in imp.names)
                desc = f"from {mod} import {names}" if mod else f"from . import {names}"
            else:
                names = ", ".join(a.name for a in imp.names)
                desc = f"import {names}"
            violations.append(f"{path}:{imp.lineno}: 函数 `{func.name}` 内 {desc}（加 `# noqa: inline-import` 豁免）")
    return violations


def main() -> int:
    if not TARGET_DIR.exists():
        print(f"目标目录不存在: {TARGET_DIR}", file=sys.stderr)
        return 2
    py_files = sorted(TARGET_DIR.rglob("*.py"))
    all_violations = []
    for f in py_files:
        all_violations.extend(check_file(f))
    if all_violations:
        print(f"❌ G-1 检查失败：发现 {len(all_violations)} 处函数内 import（api/ 全口径禁止）：", file=sys.stderr)
        for v in all_violations:
            print(f"  {v}", file=sys.stderr)
        return 1
    print(f"✅ G-1 通过：api/ 下 0 处函数内 import（扫描 {len(py_files)} 文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
