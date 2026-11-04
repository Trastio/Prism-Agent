"""utils/llm_client 共享 LLM 调用层测试（主题 C Task1 + F-4/F-5/F-10 修复）。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from utils import llm_client
from utils.llm_client import _select_provider, call_llm, LLMError


# ── provider 路由 ────────────────────────────────────────────────────────

def test_select_glm(monkeypatch):
    monkeypatch.setattr(llm_client, "load_api_config", lambda: {
        "glm": {"api_key": "k", "base_url": "http://x/v4", "model": "glm-4-flash"}
    })
    assert _select_provider() == ("k", "http://x/v4/chat/completions", "glm-4-flash")


def test_select_glm_default_base_when_missing(monkeypatch):
    monkeypatch.setattr(llm_client, "load_api_config", lambda: {"glm": {"api_key": "k"}})
    _, url, model = _select_provider()
    assert url.endswith("/chat/completions")
    assert model == "glm-4-flash"


def test_select_deepseek_fallback_when_no_glm(monkeypatch):
    monkeypatch.setattr(llm_client, "load_api_config", lambda: {
        "deepseek": {"api_key": "ds", "api_url": "http://ds/chat", "model": "deepseek-chat"}
    })
    assert _select_provider() == ("ds", "http://ds/chat", "deepseek-chat")


def test_select_none_when_unconfigured(monkeypatch):
    monkeypatch.setattr(llm_client, "load_api_config", lambda: {})
    assert _select_provider() == ("", "", "")


def test_glm_takes_precedence_over_deepseek(monkeypatch):
    monkeypatch.setattr(llm_client, "load_api_config", lambda: {
        "glm": {"api_key": "g"}, "deepseek": {"api_key": "d"}
    })
    assert _select_provider()[0] == "g"


# ── call_llm（F-4/F-5/F-10：失败 raise LLMError 不再吞串）──────────────

@pytest.mark.asyncio
async def test_call_llm_unconfigured_raises_llm_error(monkeypatch):
    """F-10：无配置 raise LLMError("config")，不再返回友好串。"""
    monkeypatch.setattr(llm_client, "load_api_config", lambda: {})
    with pytest.raises(LLMError) as exc:
        await call_llm("hi")
    assert exc.value.kind == "config"


@pytest.mark.asyncio
async def test_call_llm_success_returns_content(monkeypatch):
    monkeypatch.setattr(llm_client, "load_api_config", lambda: {"glm": {"api_key": "k"}})
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"choices": [{"message": {"content": "分析结果"}}]})
    with patch("httpx.AsyncClient") as mock_cls:
        client = AsyncMock()
        client.post = AsyncMock(return_value=mock_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = client
        assert await call_llm("prompt") == "分析结果"


@pytest.mark.asyncio
async def test_call_llm_failure_raises_llm_error(monkeypatch):
    """F-10：失败 raise LLMError，不再返回'生成失败'串。"""
    monkeypatch.setattr(llm_client, "load_api_config", lambda: {"glm": {"api_key": "k"}})
    with patch("utils.llm_client._post", AsyncMock(side_effect=LLMError("timeout", "超时"))):
        with pytest.raises(LLMError) as exc:
            await call_llm("prompt")
    assert exc.value.kind == "timeout"


@pytest.mark.asyncio
async def test_call_llm_empty_choices_raises_parse_error(monkeypatch):
    """F-5：限流返回空 choices → LLMError("parse")。"""
    monkeypatch.setattr(llm_client, "load_api_config", lambda: {"glm": {"api_key": "k"}})
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"choices": []})  # 空 choices
    with patch("httpx.AsyncClient") as mock_cls:
        client = AsyncMock()
        client.post = AsyncMock(return_value=mock_resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = client
        with pytest.raises(LLMError) as exc:
            await call_llm("prompt")
    assert exc.value.kind == "parse"
