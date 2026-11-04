"""MCP Client adapter — bridges FastMCP stdio tools to OpenAI function calling format.

Usage:
    async with MCPToolBridge(args=["mcp_server.py"]) as bridge:
        tools = await bridge.list_tools()    # OpenAI function calling format
        result = await bridge.call_tool("search_cars", {"keyword": "比亚迪"})
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPToolBridge:
    """Manages an MCP stdio connection and converts tools to OpenAI format.

    This bridge:
    1. Connects to an MCP server via stdio subprocess
    2. Discovers available tools and converts schemas to OpenAI function calling format
    3. Dispatches tool calls and returns results as dicts
    """

    def __init__(self, command: str = sys.executable, args: list[str] | None = None,
                 env: dict[str, str] | None = None):
        # env=None（默认）：子进程完整继承父进程环境（见 __aenter__）——mcp_server 是同仓库
        # 可信子进程，其无参 init_db() 与 LLM/TAGGER/TAVILY 等配置全部依赖环境变量，而 MCP SDK
        # 对 env=None 的默认是剥离一切非系统键的安全白名单，会把它们全部丢掉。
        # 显式传 env 则由调用方指定（SDK 仍会在其下垫合并系统白名单键，如 PATH）。
        self._command = command
        self._args = args or []
        self._env = env
        self._session: ClientSession | None = None
        self._stdio_context = None
        self._session_context = None
        self._tools_cache: list[dict] | None = None

    async def __aenter__(self):
        env = self._env
        if env is None:
            # 同仓库可信子进程：完整继承父进程环境（DATABASE_URL/LLM_*/TAGGER_*/TAVILY_* 等）。
            # MCP SDK 对任何非 None env 都会底垫合并系统白名单（PATH 等），系统键不会丢。
            env = dict(os.environ)
        server_params = StdioServerParameters(
            command=self._command,
            args=self._args,
            env=env,
        )
        self._stdio_context = stdio_client(server_params)
        read_stream, write_stream = await self._stdio_context.__aenter__()

        self._session_context = ClientSession(read_stream, write_stream)
        self._session = await self._session_context.__aenter__()
        await self._session.initialize()

        # Warm the tool cache
        self._tools_cache = await self._build_tool_list()
        logger.info("MCP client connected, %d tools available", len(self._tools_cache))
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session_context:
            await self._session_context.__aexit__(exc_type, exc_val, exc_tb)
        if self._stdio_context:
            await self._stdio_context.__aexit__(exc_type, exc_val, exc_tb)
        self._session = None
        self._tools_cache = None

    async def list_tools(self) -> list[dict]:
        """Return tools in OpenAI function calling format.

        Returns a cached list after first call.
        """
        if self._tools_cache is not None:
            return self._tools_cache
        self._tools_cache = await self._build_tool_list()
        return self._tools_cache

    async def _build_tool_list(self) -> list[dict]:
        """Fetch tools from MCP server and convert to OpenAI schema."""
        result = await self._session.list_tools()
        tools = []
        for tool in result.tools:
            tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema or {"type": "object", "properties": {}},
                },
            })
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict:
        """Call a tool on the MCP server and return the result as a dict.

        Args:
            name: Tool name (e.g. "search_cars")
            arguments: Tool arguments as a dict

        Returns:
            Tool result as a dict. Falls back to {"result": text} if not JSON.
        """
        result = await self._session.call_tool(name, arguments)
        # MCP returns list of content items; we expect JSON text
        if result.content and len(result.content) > 0:
            text = result.content[0].text
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return {"result": text}
        return {}
