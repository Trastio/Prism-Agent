import json
import asyncio
import logging
import httpx
from collections import Counter
from typing import Optional, Callable, Awaitable
from src.agent.types import ToolCall, ToolResult, AgentMessage
from src.agent.compression import (
    CompressionStrategy, MainAgentCompression, compress_messages,
)

logger = logging.getLogger(__name__)

MAX_LOOP = 10
TOOL_TIMEOUT = 180.0
MAX_TOOL_CALLS = 12
MAX_EMPTY_SEARCHES = 2
# Same tool called this many times → inject stop hint after tool results
MAX_SAME_TOOL_CALLS = 2

# Tool names handled locally in the main process (not via MCP)
_LOCAL_TOOL_NAMES = {"load_skill", "spawn_subagent"}


class AgentLoop:
    def __init__(self, llm_client, tools: list[dict],
                 tool_functions: Optional[dict[str, Callable[..., Awaitable[dict]]]] = None,
                 system_prompt: Optional[str] = None,
                 messages: Optional[list[dict]] = None,
                 compression: Optional[CompressionStrategy] = None,
                 mcp_bridge=None):
        self.llm = llm_client
        self.tools = tools
        self.tool_fns = tool_functions or {}
        self.system_prompt = system_prompt
        self.messages: list[dict] = messages if messages is not None else []
        self._compression = compression or MainAgentCompression()
        self._mcp_bridge = mcp_bridge
        self._consecutive_errors = 0
        self._total_tool_calls = 0
        self._empty_search_count = 0
        # Track per-tool call count within one request
        self._tool_call_counts: Counter = Counter()
        if not self.messages and system_prompt:
            self.messages.append(AgentMessage.make_system(system_prompt))

    async def _maybe_compress(self):
        compressed = await compress_messages(self.messages, self._compression)
        if len(compressed) < len(self.messages):
            logger.info("Context compressed: %d -> %d messages",
                        len(self.messages), len(compressed))
        self.messages = compressed

    def add_user_message(self, text: str):
        self.messages.append(AgentMessage.make_user(text))

    def _check_same_tool_limit(self, tcs: list[ToolCall]) -> bool:
        """Check if any tool has been called too many times. Returns True if limit hit."""
        for tc in tcs:
            self._tool_call_counts[tc.name] += 1
        for name, count in self._tool_call_counts.items():
            if count > MAX_SAME_TOOL_CALLS:
                return True
        return False

    async def run(self) -> dict:
        """Non-streaming run: returns final assistant message dict. Used by tests/batch."""
        loop_count = 0
        while loop_count < MAX_LOOP:
            loop_count += 1
            await self._maybe_compress()
            response = await self.llm.chat_nonstream(
                messages=self.messages,
                tools=self.tools if self.tools else None,
            )
            choices = response.get("choices", [])
            if not choices:
                logger.warning("LLM response has no choices, retrying...")
                continue
            choice = choices[0]
            finish_reason = choice.get("finish_reason", "stop")
            msg = choice["message"]

            if msg.get("content") and not msg.get("tool_calls"):
                self.messages.append(AgentMessage.make_assistant(msg["content"]))
                return AgentMessage.make_assistant(msg["content"])

            if finish_reason == "length" and not msg.get("tool_calls"):
                content = msg.get("content", "")
                if content:
                    self.messages.append(AgentMessage.make_assistant(content))
                return AgentMessage.make_assistant(content + "\n\n> ⚠️ 回复内容过长，已截断。")

            if msg.get("tool_calls"):
                tool_calls = [
                    ToolCall(id=tc["id"], name=tc["function"]["name"],
                             arguments=tc["function"]["arguments"])
                    for tc in msg["tool_calls"]
                ]
                reasoning = msg.get("reasoning_content", "")
                self.messages.append(AgentMessage.make_assistant_with_tools(tool_calls, reasoning))

                self._total_tool_calls += len(tool_calls)
                if self._total_tool_calls > MAX_TOOL_CALLS:
                    self.messages.append(AgentMessage.make_user(
                        "工具调用次数较多，建议基于已获取的数据生成最终回答。"))
                    continue

                same_tool_hit = self._check_same_tool_limit(tool_calls)

                for tc in tool_calls:
                    result = await self._execute_tool(tc)
                    self.messages.append(AgentMessage.make_tool_result(result))
                    if not result.is_error and result.content:
                        try:
                            parsed = json.loads(result.content)
                            if isinstance(parsed, dict) and parsed.get("stop_searching"):
                                self._empty_search_count += 1
                        except (json.JSONDecodeError, TypeError):
                            pass

                # Inject stop hint AFTER all tool results (maintains valid message sequence)
                if same_tool_hit:
                    logger.info("Same tool called too many times, injecting stop hint")
                    self.messages.append(AgentMessage.make_user(
                        "你已经多次调用了相同工具，请直接基于已获取的工具结果生成回答，"
                        "不要再重复调用相同的工具。"))

                if self._empty_search_count >= MAX_EMPTY_SEARCHES:
                    self.messages.append(AgentMessage.make_user(
                        "搜索多次返回空结果，建议用你的训练知识回答用户问题，"
                        "标注数据为'非实时数据'。"))
                    self._empty_search_count = 0
            else:
                break

        return AgentMessage.make_assistant("抱歉，处理超时，请简化问题重试。")

    async def run_streaming(self):
        """Async generator yielding (event_type, data) tuples for SSE streaming."""
        loop_count = 0
        while loop_count < MAX_LOOP:
            loop_count += 1
            await self._maybe_compress()
            try:
                response_stream = self.llm.chat_stream(
                    messages=self.messages,
                    tools=self.tools if self.tools else None,
                )
            except RuntimeError as e:
                logger.error(f"LLM stream init failed: {e}")
                yield ("text", {"content": "抱歉，AI服务暂时不可用，请稍后重试。"})
                yield ("done", {})
                return

            content_chunks = []
            tool_calls: dict[int, dict] = {}
            finish = None
            reasoning_chunks = []
            has_tool_calls_in_stream = False

            try:
                async for chunk in response_stream:
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    finish = choices[0].get("finish_reason")

                    if delta.get("content"):
                        content_chunks.append(delta["content"])
                        if not has_tool_calls_in_stream:
                            yield ("text", {"content": delta["content"]})

                    if delta.get("reasoning_content"):
                        reasoning_chunks.append(delta["reasoning_content"])

                    if delta.get("tool_calls"):
                        has_tool_calls_in_stream = True
                        for tc_delta in delta["tool_calls"]:
                            idx = tc_delta.get("index", 0)
                            if idx not in tool_calls:
                                tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
                            if tc_delta.get("id"):
                                tool_calls[idx]["id"] += tc_delta["id"]
                            fn = tc_delta.get("function", {})
                            tool_calls[idx]["name"] += fn.get("name") or ""
                            tool_calls[idx]["arguments"] += fn.get("arguments") or ""
            except (httpx.ReadError, httpx.RemoteProtocolError, ConnectionError) as e:
                logger.error(f"LLM stream read error: {e}")
                if content_chunks:
                    partial = "".join(content_chunks)
                    self.messages.append(AgentMessage.make_assistant(partial))
                    yield ("text", {"content": "\n\n> ⚠️ AI服务连接中断，以上为部分回复。请重新发送问题继续。"})
                else:
                    yield ("text", {"content": "抱歉，AI服务连接中断，请稍后重试。"})
                yield ("done", {})
                return
            except RuntimeError as e:
                logger.error(f"LLM stream runtime error: {e}")
                yield ("text", {"content": "抱歉，AI服务暂时不可用，请稍后重试。"})
                yield ("done", {})
                return

            if has_tool_calls_in_stream:
                content_chunks.clear()
                yield ("clear_text", {})

            if finish == "stop" and not tool_calls:
                content = "".join(content_chunks)
                if content:
                    self.messages.append(AgentMessage.make_assistant(content))
                yield ("done", {})
                return

            if finish == "length" and not tool_calls:
                content = "".join(content_chunks)
                if content:
                    self.messages.append(AgentMessage.make_assistant(content))
                logger.info("LLM response truncated by max_tokens, returning partial content")
                yield ("text", {"content": "\n\n> ⚠️ 回复内容过长，已截断。如需更多详情，请继续提问。"})
                yield ("done", {})
                return

            if finish is None and not tool_calls:
                content = "".join(content_chunks)
                if content:
                    self.messages.append(AgentMessage.make_assistant(content))
                    logger.info("Stream ended without finish_reason, returning partial content (%d chars)", len(content))
                    yield ("text", {"content": "\n\n> ⚠️ 回复被截断，以上为部分内容。如需完整信息，请继续提问。"})
                    yield ("done", {})
                    return
                logger.warning("Stream ended without finish_reason and no content, retrying once")
                retry_stream = self.llm.chat_stream(
                    messages=self.messages,
                    tools=self.tools if self.tools else None,
                )
                retry_content = []
                retry_finish = None
                try:
                    async for chunk in retry_stream:
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        retry_finish = choices[0].get("finish_reason")
                        if delta.get("content"):
                            retry_content.append(delta["content"])
                            yield ("text", {"content": delta["content"]})
                except Exception as e:
                    logger.error(f"Retry stream also failed: {e}")

                retry_text = "".join(retry_content)
                if retry_text:
                    self.messages.append(AgentMessage.make_assistant(retry_text))
                elif not retry_content:
                    yield ("text", {"content": "抱歉，AI生成回复时出现异常，请重新发送问题或简化提问。"})
                yield ("done", {})
                return

            if tool_calls:
                reasoning = "".join(reasoning_chunks)
                tcs = [ToolCall(id=t["id"], name=t["name"], arguments=t["arguments"])
                       for t in tool_calls.values()]
                self.messages.append(AgentMessage.make_assistant_with_tools(tcs, reasoning))

                self._total_tool_calls += len(tcs)
                if self._total_tool_calls > MAX_TOOL_CALLS:
                    self.messages.append(AgentMessage.make_user(
                        "工具调用次数较多，建议基于已获取的数据生成最终回答。"))
                    continue

                # Check same-tool limit (but inject hint AFTER tool results)
                same_tool_hit = self._check_same_tool_limit(tcs)

                for idx, tc in enumerate(tcs):
                    yield ("tool_call", {"name": tc.name, "args": tc.arguments, "tool_id": tc.id or str(idx)})

                if len(tcs) > 1:
                    tasks = [self._execute_tool(tc) for tc in tcs]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for tc, result in zip(tcs, results):
                        if isinstance(result, Exception):
                            result = ToolResult(tool_call_id=tc.id, name=tc.name, error=str(result))
                        self.messages.append(AgentMessage.make_tool_result(result))
                        if result.is_error:
                            self._consecutive_errors += 1
                            yield ("tool_result", {"name": tc.name, "error": result.error, "tool_id": tc.id or ""})
                        else:
                            self._consecutive_errors = 0
                            evt_data = {"name": tc.name, "ok": True, "tool_id": tc.id or ""}
                            if result.content:
                                _rv = result.content
                                if len(_rv) > 1500:
                                    _rv = _rv[:1500] + "\n...[已截断，共 " + str(len(result.content)) + " 字符]"
                                evt_data["result"] = _rv
                                try:
                                    parsed = json.loads(result.content)
                                    if isinstance(parsed, dict) and "interactive" in parsed:
                                        evt_data["interactive"] = parsed["interactive"]
                                    if isinstance(parsed, dict) and parsed.get("stop_searching"):
                                        self._empty_search_count += 1
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            yield ("tool_result", evt_data)
                else:
                    for tc in tcs:
                        result = await self._execute_tool(tc)
                        self.messages.append(AgentMessage.make_tool_result(result))
                        if result.is_error:
                            self._consecutive_errors += 1
                            yield ("tool_result", {"name": tc.name, "error": result.error, "tool_id": tc.id or ""})
                        else:
                            self._consecutive_errors = 0
                            evt_data = {"name": tc.name, "ok": True, "tool_id": tc.id or ""}
                            if result.content:
                                _rv = result.content
                                if len(_rv) > 1500:
                                    _rv = _rv[:1500] + "\n...[已截断，共 " + str(len(result.content)) + " 字符]"
                                evt_data["result"] = _rv
                                try:
                                    parsed = json.loads(result.content)
                                    if isinstance(parsed, dict) and "interactive" in parsed:
                                        evt_data["interactive"] = parsed["interactive"]
                                    if isinstance(parsed, dict) and parsed.get("stop_searching"):
                                        self._empty_search_count += 1
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            yield ("tool_result", evt_data)

                # Inject stop hint AFTER all tool results to maintain valid message sequence
                if same_tool_hit:
                    over_tools = [name for name, cnt in self._tool_call_counts.items()
                                  if cnt > MAX_SAME_TOOL_CALLS]
                    logger.info("Same tool called too many times: %s, injecting stop hint", over_tools)
                    self.messages.append(AgentMessage.make_user(
                        "你已经多次调用了相同工具，请直接基于已获取的工具结果生成回答，"
                        "不要再重复调用相同的工具。"))

                # If 3+ consecutive tool errors, stop
                if self._consecutive_errors >= 3:
                    self.messages.append(AgentMessage.make_assistant(
                        "当前搜索和抓取工具暂时不可用，我将基于已有知识为你回答。"))
                    yield ("text", {"content": "当前搜索和抓取工具暂时不可用，我将基于已有知识为你回答。"})
                    yield ("done", {})
                    return

                if self._empty_search_count >= MAX_EMPTY_SEARCHES:
                    self.messages.append(AgentMessage.make_user(
                        "搜索多次返回空结果，建议用你的训练知识回答用户问题，"
                        "标注数据为'非实时数据'。"))
                    self._empty_search_count = 0

        yield ("error", {"message": "达到最大循环次数"})

    async def _execute_tool(self, tc: ToolCall) -> ToolResult:
        # ── Local tools (handled in main process) ──
        if tc.name in _LOCAL_TOOL_NAMES:
            fn = self.tool_fns.get(tc.name)
            if fn is None:
                return ToolResult(tool_call_id=tc.id, name=tc.name,
                                  error=f"工具 '{tc.name}' 不存在")
            try:
                args = json.loads(tc.arguments)
            except json.JSONDecodeError as e:
                return ToolResult(tool_call_id=tc.id, name=tc.name,
                                  error=f"参数 JSON 解析失败: {e}")
            try:
                output = await asyncio.wait_for(fn(**args), timeout=TOOL_TIMEOUT)
                content = json.dumps(output, ensure_ascii=False)
                return ToolResult(tool_call_id=tc.id, name=tc.name, content=content)
            except asyncio.TimeoutError:
                return ToolResult(tool_call_id=tc.id, name=tc.name,
                                  error=f"工具执行超时（{TOOL_TIMEOUT:.0f}秒）")
            except Exception as e:
                logger.warning(f"Local tool {tc.name} error: {e}")
                return ToolResult(tool_call_id=tc.id, name=tc.name, error=str(e))

        # ── MCP tools (delegated to MCP server) ──
        if self._mcp_bridge is not None:
            try:
                args = json.loads(tc.arguments)
            except json.JSONDecodeError as e:
                return ToolResult(tool_call_id=tc.id, name=tc.name,
                                  error=f"参数 JSON 解析失败: {e}")
            try:
                output = await asyncio.wait_for(
                    self._mcp_bridge.call_tool(tc.name, args),
                    timeout=TOOL_TIMEOUT,
                )
                content = json.dumps(output, ensure_ascii=False)
                return ToolResult(tool_call_id=tc.id, name=tc.name, content=content)
            except asyncio.TimeoutError:
                return ToolResult(tool_call_id=tc.id, name=tc.name,
                                  error=f"工具执行超时（{TOOL_TIMEOUT:.0f}秒）")
            except Exception as e:
                logger.warning(f"MCP tool {tc.name} error: {e}")
                return ToolResult(tool_call_id=tc.id, name=tc.name, error=str(e))

        # ── Fallback: direct function call (backward compat) ──
        fn = self.tool_fns.get(tc.name)
        if fn is None:
            return ToolResult(tool_call_id=tc.id, name=tc.name,
                              error=f"工具 '{tc.name}' 不存在")

        try:
            args = json.loads(tc.arguments)
        except json.JSONDecodeError as e:
            return ToolResult(tool_call_id=tc.id, name=tc.name,
                              error=f"参数 JSON 解析失败: {e}")

        from src.tools.params import validate_params
        td = next((t for t in self.tools if t["function"]["name"] == tc.name), None)
        if td:
            valid, err_msg = validate_params(args, td["function"].get("parameters", {}))
            if not valid:
                return ToolResult(tool_call_id=tc.id, name=tc.name, error=err_msg)

        try:
            output = await asyncio.wait_for(fn(**args), timeout=TOOL_TIMEOUT)
            content = json.dumps(output, ensure_ascii=False)
            return ToolResult(tool_call_id=tc.id, name=tc.name, content=content)
        except asyncio.TimeoutError:
            return ToolResult(tool_call_id=tc.id, name=tc.name,
                              error=f"工具执行超时（{TOOL_TIMEOUT:.0f}秒）")
        except Exception as e:
            logger.warning(f"Tool {tc.name} error: {e}")
            return ToolResult(tool_call_id=tc.id, name=tc.name, error=str(e))
