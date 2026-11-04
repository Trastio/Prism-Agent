from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.nlp.llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = (
    "请总结以下对话的关键信息，包含：用户主要需求、已完成操作、当前讨论重点、"
    "需记住的关键数据（如车型名、价格、配置差异等）。用简洁的中文回答，不超过300字。"
)


class CompressionStrategy(ABC):
    @abstractmethod
    def micro_compact(self, messages: list[dict]) -> list[dict]:
        ...

    @abstractmethod
    async def auto_compact(self, messages: list[dict]) -> list[dict]:
        ...

    def should_auto_compact(self, messages: list[dict]) -> bool:
        return False


class MainAgentCompression(CompressionStrategy):
    def __init__(
        self,
        micro_keep_recent: int = 5,
        micro_min_length: int = 500,
        auto_threshold_chars: int = 400_000,
        auto_keep_recent: int = 15,
        transcript_dir: str = ".transcripts",
        llm_client: BaseLLMClient | None = None,
    ):
        self.micro_keep_recent = micro_keep_recent
        self.micro_min_length = micro_min_length
        self.auto_threshold_chars = auto_threshold_chars
        self.auto_keep_recent = auto_keep_recent
        self.transcript_dir = Path(transcript_dir)
        self._llm = llm_client

    def micro_compact(self, messages: list[dict]) -> list[dict]:
        result = list(messages)
        tool_msgs = [(i, m) for i, m in enumerate(result) if m.get("role") == "tool"]
        if len(tool_msgs) <= self.micro_keep_recent:
            return result

        recent_ids = {idx for idx, _ in tool_msgs[-self.micro_keep_recent:]}
        for idx, m in tool_msgs:
            if idx not in recent_ids and len(m.get("content", "")) > self.micro_min_length:
                name = m.get("name", "tool")
                n = len(m["content"])
                result[idx] = {**m, "content": (
                    f"[Previous: {name} executed, result was {n} chars, now compacted]"
                )}
        return result

    def should_auto_compact(self, messages: list[dict]) -> bool:
        total = sum(len(str(m)) for m in messages)
        return total > self.auto_threshold_chars

    async def auto_compact(self, messages: list[dict]) -> list[dict]:
        self._save_transcript(messages)
        system_msg = (
            messages[0] if messages and messages[0].get("role") == "system" else None
        )
        keep = (
            messages[-self.auto_keep_recent:]
            if len(messages) > self.auto_keep_recent
            else list(messages)
        )

        # Generate LLM summary of dropped messages
        summary_text = await self._generate_summary(messages, keep)

        result = []
        if system_msg is not None and not any(m is system_msg for m in keep):
            result.append(system_msg)
        if summary_text:
            from src.agent.types import AgentMessage
            result.append(AgentMessage.make_system(
                f"[对话摘要]\n{summary_text}"
            ))
        result.extend(keep)
        return _fix_message_pairs(result)

    async def manual_compact(self, messages: list[dict]) -> list[dict]:
        return await self.auto_compact(messages)

    async def _generate_summary(
        self, all_messages: list[dict], keep_messages: list[dict]
    ) -> str | None:
        if self._llm is None:
            return None

        keep_ids = {id(m) for m in keep_messages}
        dropped = [m for m in all_messages if id(m) not in keep_ids
                   and m.get("role") != "system"]
        if len(dropped) < 3:
            return None

        summary_parts = []
        for m in dropped[:20]:
            role = m.get("role", "")
            content = m.get("content", "")
            if role == "user" and content:
                summary_parts.append(f"用户: {content[:200]}")
            elif role == "assistant" and content:
                summary_parts.append(f"助手: {content[:200]}")
            elif role == "tool":
                name = m.get("name", "tool")
                summary_parts.append(f"工具结果({name}): {content[:150]}")

        if not summary_parts:
            return None

        conversation_text = "\n".join(summary_parts)
        if len(conversation_text) > 3000:
            conversation_text = conversation_text[:3000] + "..."

        try:
            resp = await self._llm.chat_nonstream(
                messages=[
                    {"role": "system", "content": _SUMMARY_PROMPT},
                    {"role": "user", "content": conversation_text},
                ],
            )
            choices = resp.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.warning("LLM summary generation failed: %s", e)
        return None

    def _save_transcript(self, messages: list[dict]):
        try:
            self.transcript_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            path = self.transcript_dir / f"main_{ts}.jsonl"
            with open(path, "w", encoding="utf-8") as f:
                for m in messages:
                    f.write(json.dumps(m, ensure_ascii=False) + "\n")
            logger.info("Saved transcript to %s", path)
        except OSError as e:
            logger.warning("Failed to save transcript: %s", e)


class SubagentCompression(CompressionStrategy):
    def __init__(
        self,
        micro_keep_recent: int = 2,
        micro_min_length: int = 300,
        auto_max_messages: int = 8,
        auto_keep_last: int = 4,
    ):
        self.micro_keep_recent = micro_keep_recent
        self.micro_min_length = micro_min_length
        self.auto_max_messages = auto_max_messages
        self.auto_keep_last = auto_keep_last

    def micro_compact(self, messages: list[dict]) -> list[dict]:
        result = list(messages)
        tool_msgs = [(i, m) for i, m in enumerate(result) if m.get("role") == "tool"]
        if len(tool_msgs) <= self.micro_keep_recent:
            return result

        recent_ids = {idx for idx, _ in tool_msgs[-self.micro_keep_recent:]}
        for idx, m in tool_msgs:
            if idx not in recent_ids and len(m.get("content", "")) > self.micro_min_length:
                name = m.get("name", "tool")
                result[idx] = {**m, "content": f"[Previous result: {name}]"}
        return result

    def should_auto_compact(self, messages: list[dict]) -> bool:
        return len(messages) > self.auto_max_messages

    async def auto_compact(self, messages: list[dict]) -> list[dict]:
        system_msg = (
            messages[0] if messages and messages[0].get("role") == "system" else None
        )
        keep = (
            messages[-self.auto_keep_last:]
            if len(messages) > self.auto_keep_last
            else list(messages)
        )
        result = []
        if system_msg is not None and not any(m is system_msg for m in keep):
            result.append(system_msg)
        result.extend(keep)
        return _fix_message_pairs(result)


def _fix_message_pairs(messages: list[dict]) -> list[dict]:
    messages = list(messages)
    for _ in range(3):
        changed = False
        orphan_ids = set()
        for m in messages:
            if m.get("role") == "tool":
                orphan_ids.add(m.get("tool_call_id"))
        for m in messages:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    orphan_ids.discard(tc.get("id"))
        if orphan_ids:
            messages = [
                m for m in messages
                if not (m.get("role") == "tool" and m.get("tool_call_id") in orphan_ids)
            ]
            changed = True
        result_tool_ids = set()
        for m in messages:
            if m.get("role") == "tool":
                result_tool_ids.add(m.get("tool_call_id"))
        new_messages = [
            m for m in messages
            if not (
                m.get("role") == "assistant"
                and m.get("tool_calls")
                and all(tc.get("id") not in result_tool_ids for tc in m["tool_calls"])
            )
        ]
        if len(new_messages) < len(messages):
            messages = new_messages
            changed = True
        if not changed:
            break
    return messages


async def compress_messages(
    messages: list[dict], strategy: CompressionStrategy
) -> list[dict]:
    result = strategy.micro_compact(messages)
    if strategy.should_auto_compact(result):
        result = await strategy.auto_compact(result)
    return result
