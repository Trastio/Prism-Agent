from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from src.agent.background import BackgroundManager
from src.agent.compression import SubagentCompression
from src.agent.loop import AgentLoop
from src.agent.types import AgentMessage

logger = logging.getLogger(__name__)

_STATUS_MARKERS = {"pending": " ", "in_progress": ">", "completed": "x"}


@dataclass
class TodoItem:
    id: str
    text: str
    status: Literal["pending", "in_progress", "completed"] = "pending"


class TodoManager:
    def __init__(self, max_items: int = 20):
        self.todos: list[TodoItem] = []
        self.max_items = max_items
        self.rounds_since_todo: int = 0

    def update(self, items: list[str]):
        new_todos = [TodoItem(id=str(i), text=text)
                     for i, text in enumerate(items[:self.max_items])]
        self.todos = new_todos
        self.rounds_since_todo = 0

    def set_in_progress(self, item_id: str):
        for t in self.todos:
            if t.status == "in_progress":
                t.status = "pending"
        for t in self.todos:
            if t.id == item_id:
                t.status = "in_progress"
                break
        self.rounds_since_todo = 0

    def complete(self, item_id: str):
        for t in self.todos:
            if t.id == item_id:
                t.status = "completed"
                break
        self.rounds_since_todo = 0

    def render(self) -> str:
        completed = sum(1 for t in self.todos if t.status == "completed")
        total = len(self.todos)
        lines = [f"Todo [{completed}/{total}]"]
        for t in self.todos:
            lines.append(f"  [{_STATUS_MARKERS[t.status]}] #{t.id}: {t.text}")
        return "\n".join(lines)


class SubagentRunner:
    def __init__(self, llm_client, tool_registry, task: str,
                 focus: str = "", max_iterations: int = 20):
        self.task = task
        self.focus = focus
        self.max_iterations = max_iterations
        self.todo_mgr = TodoManager()
        self.compression = SubagentCompression()
        self.messages: list[dict] = []
        self._llm = llm_client
        self._tool_registry = tool_registry
        self._bg_manager: BackgroundManager | None = None

    def _get_bg_manager(self) -> BackgroundManager:
        if self._bg_manager is None:
            self._bg_manager = BackgroundManager(concurrency=2, persist=False)
        return self._bg_manager

    def _make_todo_tool_fn(self):
        async def todo(items: list[str]) -> dict:
            """更新任务清单，规划和跟踪工作步骤。

            每次调用会替换整个清单。保持已完成的项目标注为 completed。
            同一时间只有一个项目可以是 in_progress。

            Args:
                items: 任务列表，每项为一个步骤描述
            """
            self.todo_mgr.update(items)
            return {"rendered": self.todo_mgr.render()}
        return todo

    async def _compress_with_todo(self):
        if self.compression.should_auto_compact(self.messages):
            snapshot = self.todo_mgr.render()
            self.messages.append(
                AgentMessage.make_user(f"<todo_snapshot>\n{snapshot}\n</todo_snapshot>")
            )
            self.messages = await self.compression.auto_compact(self.messages)
            self.todo_mgr.rounds_since_todo = 0

    async def run(self) -> str:
        system_msg = (
            "你是汽车之家智能助手的研究分析员，专注于独立完成深度调研任务。\n\n"
            f"任务：{self.task}"
        )
        if self.focus:
            system_msg += f"\n关注点：{self.focus}"
        system_msg += (
            "\n\n"
            "## 工作方式\n"
            "1. 先用 todo 工具规划工作步骤（拆分成可执行的子任务）\n"
            "2. 调用工具获取实时数据，不凭空编造信息\n"
            "3. 基于工具返回的数据进行深度分析，挖掘关键发现\n"
            "4. 完成后输出完整的分析摘要\n\n"
            "## 注意事项\n"
            "- 你在独立上下文中运行，无法与用户交互，请自行完成所有步骤\n"
            "- 工具调用失败时跳过该步骤，用已有数据继续分析\n"
            "- 引用数据来源，使用训练知识时标注「知识库数据，非实时」\n"
            "- 分析要深入但简洁，突出关键发现和结论"
        )

        self.messages = [AgentMessage.make_system(system_msg)]
        self.messages.append(AgentMessage.make_user(f"请执行任务：{self.task}"))

        tools = self._tool_registry.get_all_descriptions()
        tool_fns = {name: self._tool_registry.get_function(name)
                    for name in [td["function"]["name"] for td in tools]}

        # Add subagent-scoped todo tool
        todo_fn = self._make_todo_tool_fn()
        todo_fn.__name__ = "todo"
        tool_fns["todo"] = todo_fn
        tools.append({
            "type": "function",
            "function": {
                "name": "todo",
                "description": "更新任务清单，规划和跟踪工作步骤。每次调用替换整个清单。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "任务步骤列表"
                        }
                    },
                    "required": ["items"]
                }
            }
        })

        loop = AgentLoop(
            llm_client=self._llm,
            tools=tools,
            tool_functions=tool_fns,
            messages=self.messages,
            compression=self.compression,
        )

        try:
            for iteration in range(self.max_iterations):
                self.todo_mgr.rounds_since_todo += 1

                if self.todo_mgr.rounds_since_todo >= 3:
                    reminder = (
                        f"<reminder>Update your todos. "
                        f"You are working on: {self.task}</reminder>"
                    )
                    self.messages.append(AgentMessage.make_user(reminder))
                    self.todo_mgr.rounds_since_todo = 0

                await self._compress_with_todo()

                result = await loop.run()
                if result.get("content") and not any(
                    m.get("tool_calls") for m in self.messages[-3:]
                ):
                    return result["content"]
        finally:
            if self._bg_manager is not None:
                await self._bg_manager.shutdown()

        last_assistant = ""
        for m in reversed(self.messages):
            if m.get("role") == "assistant" and m.get("content"):
                last_assistant = m["content"]
                break
        return last_assistant or "Subagent completed but produced no text output."
