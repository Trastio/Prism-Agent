from dataclasses import dataclass
from typing import Optional
import json


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON string


@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    content: Optional[str] = None
    error: Optional[str] = None

    @property
    def is_error(self) -> bool:
        return self.error is not None

    def to_message_content(self) -> str:
        if self.error:
            return json.dumps({"error": self.error}, ensure_ascii=False)
        return self.content or ""


class AgentMessage:
    @staticmethod
    def make_user(text: str) -> dict:
        return {"role": "user", "content": text}

    @staticmethod
    def make_assistant(text: str) -> dict:
        return {"role": "assistant", "content": text}

    @staticmethod
    def make_assistant_with_tools(tool_calls: list[ToolCall], reasoning_content: str = "") -> dict:
        msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in tool_calls
            ],
        }
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content
        return msg

    @staticmethod
    def make_tool_result(result: ToolResult) -> dict:
        return {
            "role": "tool",
            "tool_call_id": result.tool_call_id,
            "name": result.name,
            "content": result.to_message_content(),
        }

    @staticmethod
    def make_system(text: str) -> dict:
        return {"role": "system", "content": text}
