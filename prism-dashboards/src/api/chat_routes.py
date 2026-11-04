import logging
import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from src.api.schemas import ChatRequest, ChatSessionCreate, ChatSessionOut
from src.agent.types import AgentMessage
from src.agent.prompts import UNIFIED_SYSTEM_PROMPT
from src.agent.sse import sse_event
from src.agent.compression import MainAgentCompression
from src.agent.loop import AgentLoop
from src.conversation.manager import get_session_manager
from src.agent.mcp_client import MCPToolBridge
from src.nlp.llm_client import BaseLLMClient
from src.storage.db import session_scope
from src.models.orm import Conversation

router = APIRouter()
logger = logging.getLogger(__name__)
_session_mgr = get_session_manager()

# ── MCP Bridge (data tools) ─────────────────────────────────────
_mcp_bridge: MCPToolBridge | None = None
_mcp_lock = asyncio.Lock()


async def _get_mcp_bridge() -> MCPToolBridge:
    """Get or create the MCP bridge (connects to MCP server subprocess)."""
    global _mcp_bridge
    if _mcp_bridge is not None:
        return _mcp_bridge
    async with _mcp_lock:
        if _mcp_bridge is not None:
            return _mcp_bridge
        bridge = MCPToolBridge(args=["mcp_server.py"])
        await bridge.__aenter__()
        _mcp_bridge = bridge
        logger.info("MCP bridge connected, %d tools available", len(bridge._tools_cache or []))
        return _mcp_bridge


async def close_mcp_bridge():
    """Close MCP bridge on shutdown."""
    global _mcp_bridge
    if _mcp_bridge:
        await _mcp_bridge.__aexit__(None, None, None)
        _mcp_bridge = None


# ── Local Agent Tools (main process) ─────────────────────────────

async def load_skill(skill_name: str) -> dict:
    """加载专业知识模块，获取领域方法论辅助分析。

    可用模块：
    - config: 配置对比方法（核心对比维度、差异识别技巧）
    - decision: 购车决策框架（偏好引出策略、评分标准、推荐逻辑、报告模板）
    - market: 市场分析方法（竞品对比框架、销量数据解读、报告结构模板）

    :param skill_name: 技能名称
    """
    from src.agent.skills import get_skill_loader
    loader = get_skill_loader()
    content = loader.get_content(skill_name)
    return {"skill": skill_name, "content": content}


async def spawn_subagent(task: str, focus: str = "") -> dict:
    """创建子 Agent 执行深度调研任务，返回分析摘要。

    适合需要大量工具调用且不需要用户交互的深度分析任务。
    子 Agent 在独立上下文中运行，拥有完整的汽车数据工具链和 todo 规划能力。

    :param task: 任务描述（如"对比元UP、海豚、缤果的配置、口碑、性价比"）
    :param focus: 关注点（可选，如"性价比"）
    """
    from src.agent.subagent import SubagentRunner
    llm = await _get_llm_client()
    # Subagent uses MCP bridge for tools (same as main agent)
    bridge = await _get_mcp_bridge()
    runner = SubagentRunner(
        llm_client=llm,
        mcp_bridge=bridge,
        task=task,
        focus=focus,
    )
    summary = await runner.run()
    return {"summary": summary}


# Local tool functions keyed by name
_LOCAL_TOOL_FNS = {
    "load_skill": load_skill,
    "spawn_subagent": spawn_subagent,
}


# ── Component Initialization ─────────────────────────────────────

def init_tools():
    """Initialize skill loader (lightweight, no registry needed)."""
    try:
        from src.agent.skills import get_skill_loader
        loader = get_skill_loader()
        logger.info("SkillLoader initialized (%d skills)", len(loader.skills))
    except Exception as e:
        logger.error("SkillLoader failed: %s", e)


async def init_components():
    """Initialize components with graceful degradation."""
    try:
        bridge = await _get_mcp_bridge()
        logger.info("MCP bridge initialized (%d tools)", len(bridge._tools_cache or []))
    except Exception as e:
        logger.error("MCP bridge failed (degraded): %s", e)

    try:
        from src.agent.skills import get_skill_loader
        loader = get_skill_loader()
        logger.info("SkillLoader initialized (%d skills)", len(loader.skills))
    except Exception as e:
        logger.error("SkillLoader failed: %s", e)


# ── LLM Client ──────────────────────────────────────────────────

_llm_client: BaseLLMClient | None = None
_llm_lock = asyncio.Lock()


async def _get_llm_client():
    global _llm_client
    if _llm_client is not None:
        return _llm_client
    async with _llm_lock:
        if _llm_client is not None:
            return _llm_client
        _llm_client = BaseLLMClient()
        return _llm_client


async def close_llm_client():
    global _llm_client
    if _llm_client:
        await _llm_client.close()
        _llm_client = None


# ── Build merged tool list ──────────────────────────────────────

def _build_local_tool_schemas() -> list[dict]:
    """Build OpenAI function calling schemas for local agent tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": "load_skill",
                "description": "加载专业知识模块，获取领域方法论辅助分析。可用：config（配置对比方法）、decision（购车决策框架）、market（市场分析方法）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {"type": "string", "description": "技能名称"},
                    },
                    "required": ["skill_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "spawn_subagent",
                "description": "创建子 Agent 执行深度调研任务，返回分析摘要。适合多步工具调用的深度分析",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string", "description": "任务描述"},
                        "focus": {"type": "string", "description": "关注点（可选）"},
                    },
                    "required": ["task"],
                },
            },
        },
    ]


async def _build_all_tools() -> tuple[list[dict], dict]:
    """Merge MCP tools + local tools. Returns (tools, tool_fns)."""
    bridge = await _get_mcp_bridge()
    mcp_tools = await bridge.list_tools()
    local_tools = _build_local_tool_schemas()

    all_tools = mcp_tools + local_tools
    tool_fns = dict(_LOCAL_TOOL_FNS)

    return all_tools, tool_fns


# ── Domain Hints (soft, user-level) ─────────────────────────────

# 关键词 → 领域映射（用于软提示，不强制 LLM）
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "口碑/车主评价": ["口碑", "车主", "真实评价", "用车感受", "优缺点", "值不值得买", "车主反馈"],
    "配置/参数": ["配置", "参数", "辅助驾驶", "L2"],
    "对比/评分": ["对比", "评分", "排序", "哪款好"],
    "销量/排行": ["销量", "卖得好", "月销", "排名"],
    "经销商/报价": ["经销商", "报价", "落地价", "优惠", "多少钱"],
    "资讯/评测": ["资讯", "评测", "上市", "改款", "新闻"],
    "能耗/续航": ["续航", "能耗", "电耗", "油耗", "冬天"],
    "竞品/同级": ["竞品", "同级", "对手"],
}


def _infer_domain(text: str) -> str | None:
    """轻量关键词识别，返回最匹配的领域标签（仅软提示用，不强制）

    Args:
        text: 用户输入文本

    Returns:
        匹配到的领域标签（如"口碑/车主评价"），无匹配返回 None
    """
    if not text:
        return None
    best_domain = None
    best_score = 0
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_domain = domain
    return best_domain if best_score >= 1 else None


# ── Routes ──────────────────────────────────────────────────────

@router.post("/chat/send")
async def chat_send(req: ChatRequest):
    session_id = req.session_id
    if session_id:
        messages = _session_mgr.resume_session(session_id)
        if messages is None:
            raise HTTPException(410, "会话已过期，请创建新会话")
    else:
        session_id, messages = _session_mgr.create_session()

    messages.append(AgentMessage.make_user(req.message))

    # 软提示：识别用户问题领域，追加 user message 提示（不动 system prompt）
    domain = _infer_domain(req.message)
    if domain:
        hint = f"[问题领域提示: {domain}] 如需真实数据支撑，请调用对应工具。"
        messages.append(AgentMessage.make_user(hint))

    llm = await _get_llm_client()

    # Build merged tool list: MCP (15) + local (2)
    try:
        tools, tool_fns = await _build_all_tools()
    except Exception as e:
        logger.error(f"Failed to build tools: {e}")
        raise HTTPException(500, f"工具初始化失败: {str(e)[:200]}")

    bridge = await _get_mcp_bridge()

    loop = AgentLoop(llm_client=llm, tools=tools, tool_functions=tool_fns,
                     system_prompt=UNIFIED_SYSTEM_PROMPT,
                     messages=messages,
                     compression=MainAgentCompression(llm_client=llm),
                     mcp_bridge=bridge)

    _REQUEST_TIMEOUT = 300  # 5 minutes max per request

    async def event_stream():
        try:
            async with asyncio.timeout(_REQUEST_TIMEOUT):
                yield sse_event("meta", {"session_id": session_id})
                async for event_type, data in loop.run_streaming():
                    yield sse_event(event_type, data)
                # Strip synthetic domain-hint messages before persisting so resumed
                # sessions don't accumulate [问题领域提示: ...] noise.
                clean = [m for m in loop.messages
                         if not (hasattr(m, 'content') and isinstance(m.content, str)
                                 and m.content.startswith('[问题领域提示:'))]
                _session_mgr.save_messages(session_id, clean)
        except asyncio.TimeoutError:
            logger.warning("SSE stream timed out after %ds", _REQUEST_TIMEOUT)
            yield sse_event("error", {"message": "请求超时，请简化问题重试。"})
            yield sse_event("done", {})
        except Exception as e:
            logger.error(f"SSE stream error: {e}", exc_info=True)
            yield sse_event("error", {"message": f"服务异常: {str(e)[:200]}"})
            yield sse_event("done", {})

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/chat/progress/{series_id}")
async def collection_progress(series_id: str):
    """Poll collection progress for a given series_id."""
    from src.tools.reviews import get_collection_progress
    return get_collection_progress(series_id)


@router.post("/chat/sessions", response_model=ChatSessionOut)
async def create_session(req: ChatSessionCreate):
    sid, msgs = _session_mgr.create_session(user_id=req.user_id)
    return ChatSessionOut(session_id=sid, created_at="", message_count=len(msgs))


@router.get("/chat/sessions/{session_id}")
async def get_session_info(session_id: str):
    with session_scope() as session:
        conv = session.query(Conversation).filter_by(session_id=session_id).first()
    if conv is None:
        raise HTTPException(404, "会话不存在")
    return {
        "session_id": conv.session_id,
        "created_at": str(conv.created_at),
        "last_active_at": str(conv.last_active_at),
        "message_count": len(conv.messages_list),
        "is_expired": conv.is_expired,
    }
