"""多提供商 LLM 客户端

支持：
- 主提供商 + 降级提供商自动切换
- 推理模型适配（reasoning_content 回传）
- 请求缓存（TTL 内存缓存，减少重复调用）
- 模型能力自动检测
"""
import json
import os
import time
import logging
import httpx
import asyncio
from typing import Optional, AsyncGenerator

logger = logging.getLogger(__name__)
_LLM_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 300  # 5 分钟 TTL


def _cache_key(messages: list, tools: list | None, max_tokens: int) -> str:
    """构建确定性缓存 key"""
    content = json.dumps(messages[-1] if messages else {}, ensure_ascii=False, sort_keys=True)
    return f"{hash(content)}:{max_tokens}:{bool(tools)}"


# Reasoning model name patterns — these models typically reject temperature param
_REASONING_MODEL_PATTERNS = ["reasoning", "thinking", "deepseek-v4", "deepseek-r1", "deepseek-reasoner", "o1", "o3"]


def _model_supports_temperature(model: str) -> bool:
    model_lower = model.lower()
    for pattern in _REASONING_MODEL_PATTERNS:
        if pattern in model_lower:
            return False
    return True


def _model_supports_reasoning(model: str) -> bool:
    model_lower = model.lower()
    for pattern in ["reasoning", "thinking", "deepseek-v4", "deepseek-r1", "o1", "o3"]:
        if pattern in model_lower:
            return True
    return False


class LLMProviderConfig:
    """单个 LLM 提供商的配置"""
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self._supports_temperature: bool | None = None
        self._supports_reasoning: bool | None = None

    @property
    def supports_temperature(self) -> bool:
        if self._supports_temperature is None:
            self._supports_temperature = _model_supports_temperature(self.model)
        return self._supports_temperature

    @property
    def supports_reasoning(self) -> bool:
        if self._supports_reasoning is None:
            self._supports_reasoning = _model_supports_reasoning(self.model)
        return self._supports_reasoning

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    @classmethod
    def from_env(cls, prefix: str = "") -> "LLMProviderConfig":
        if prefix:
            return cls(
                base_url=os.environ.get(f"{prefix}LLM_BASE_URL", ""),
                api_key=os.environ.get(f"{prefix}LLM_API_KEY", "") or os.environ.get(f"{prefix}DASHSCOPE_API_KEY", ""),
                model=os.environ.get(f"{prefix}LLM_MODEL", ""),
            )
        return cls(
            base_url=os.environ.get("LLM_BASE_URL", ""),
            api_key=os.environ.get("LLM_API_KEY", "") or os.environ.get("DASHSCOPE_API_KEY", ""),
            model=os.environ.get("LLM_MODEL", "deepseek-chat"),
        )


class BaseLLMClient:
    """多提供商 LLM 客户端。

    对应 OpenClaw 的 provider auto-detection + fallback 模式：
    - 主提供商（env 配置）优先
    - 降级提供商（FALLBACK_LLM_*）自动切换
    - 预留更多 provider 的扩展点
    """

    def __init__(self):
        self._primary = LLMProviderConfig.from_env()
        self._fallback = LLMProviderConfig.from_env("FALLBACK_")
        self._http_client: httpx.AsyncClient | None = None

        if not self._primary.api_key:
            logger.warning("DASHSCOPE_API_KEY/LLM_API_KEY 未设置，LLM 调用将失败")
        else:
            logger.info(f"LLM init: model={self._primary.model}, "
                        f"base_url={self._primary.base_url}, "
                        f"api_key_prefix={self._primary.api_key[:10]}... len={len(self._primary.api_key)}")

    def _get_providers(self) -> list[LLMProviderConfig]:
        """获取可用提供商列表（OpenClaw resolveCandidates 模式）"""
        providers = []
        if self._primary.is_configured:
            providers.append(self._primary)
        if self._fallback.is_configured:
            providers.append(self._fallback)
        return providers if providers else [self._primary]

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=120.0)
        return self._http_client

    async def close(self):
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    def _headers(self, provider: LLMProviderConfig) -> dict:
        return {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }

    async def _try_chat(self, provider: LLMProviderConfig, messages: list,
                        tools: list | None, max_tokens: int, temperature: float,
                        stream: bool) -> dict | AsyncGenerator:
        """对单个 provider 尝试调用（带重试）"""
        cleaned = []
        for m in messages:
            if provider.supports_reasoning:
                m_copy = dict(m)
                if m_copy.get("role") == "assistant" and "reasoning_content" not in m_copy:
                    m_copy["reasoning_content"] = ""
                cleaned.append(m_copy)
            else:
                m_copy = {k: v for k, v in m.items() if k != "reasoning_content"}
                cleaned.append(m_copy)

        validated = []
        i = 0
        while i < len(cleaned):
            m = cleaned[i]
            if m.get("role") == "assistant" and m.get("tool_calls"):
                validated.append(m)
                tc_ids = {tc.get("id") for tc in m.get("tool_calls", [])}
                i += 1
                provided_ids = set()
                while i < len(cleaned) and cleaned[i].get("role") == "tool":
                    validated.append(cleaned[i])
                    provided_ids.add(cleaned[i].get("tool_call_id"))
                    i += 1
                for tid in tc_ids - provided_ids:
                    validated.append({
                        "role": "tool",
                        "tool_call_id": tid,
                        "content": json.dumps({"error": "工具结果缺失"}, ensure_ascii=False),
                    })
            elif m.get("role") == "tool":
                has_parent = any(
                    v.get("role") == "assistant" and v.get("tool_calls")
                    and m.get("tool_call_id") in {tc.get("id") for tc in v.get("tool_calls", [])}
                    for v in validated
                )
                if has_parent:
                    validated.append(m)
                i += 1
            else:
                validated.append(m)
                i += 1
        cleaned = validated
        body = {
            "model": provider.model, "messages": cleaned,
            "max_tokens": max_tokens,
        }
        if provider.supports_temperature:
            body["temperature"] = temperature
        if stream:
            body["stream"] = True
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        client = await self._get_client()
        max_retries = 3

        for attempt in range(max_retries):
            resp = await client.post(
                f"{provider.base_url}/chat/completions",
                headers=self._headers(provider), json=body,
            )

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "5"))
                logger.warning(f"Rate limited ({provider.model} attempt {attempt + 1}), waiting {retry_after}s")
                await asyncio.sleep(retry_after)
                if attempt == max_retries - 1:
                    raise RuntimeError(f"Rate limited after {max_retries} retries")
                continue

            if resp.status_code >= 400:
                err_body = ""
                try:
                    err_body = (await resp.aread()).decode()[:500]
                except Exception:
                    pass
                logger.error(f"LLM {resp.status_code} ({provider.model}): {err_body}")
                resp.raise_for_status()

            if not stream:
                return resp.json()
            # streaming — caller handles
            return resp

        raise RuntimeError("Unexpected")

    async def chat_nonstream(self, messages: list, tools: list | None = None,
                              max_tokens: int = 8192, temperature: float = 0,
                              max_retries: int = 3) -> dict:
        # 检查缓存（仅无 tool 调用时）
        if not tools:
            ck = _cache_key(messages, tools, max_tokens)
            if ck in _LLM_CACHE:
                ts, cached = _LLM_CACHE[ck]
                if time.time() - ts < CACHE_TTL:
                    return cached

        providers = self._get_providers()
        last_error = None

        for provider in providers:
            try:
                result = await self._try_chat(provider, messages, tools, max_tokens, temperature, False)
                if not tools:
                    _LLM_CACHE[_cache_key(messages, tools, max_tokens)] = (time.time(), result)
                return result
            except Exception as e:
                last_error = e
                logger.warning(f"Provider {provider.model} failed: {e}")
                if provider != providers[-1]:
                    await asyncio.sleep(0.5)

        raise RuntimeError(f"All providers failed. Last error: {last_error}")

    async def chat_stream(self, messages: list, tools: list | None = None,
                           max_tokens: int = 8192, temperature: float = 0,
                           max_retries: int = 3):
        """Async generator yielding parsed SSE chunks. Provider fallback on failure.

        Mid-stream disconnect: if the stream breaks after partial output, the next
        provider is tried (full retry from scratch) — the outer AgentLoop will
        reconstruct state from the accumulated tool_calls/content chunks.
        """
        providers = self._get_providers()
        last_error = None

        for provider_idx, provider in enumerate(providers):
            try:
                resp = await self._try_chat(provider, messages, tools, max_tokens, temperature, True)
            except Exception as e:
                last_error = e
                logger.warning(f"Stream provider {provider.model} failed: {e}")
                if provider_idx < len(providers) - 1:
                    await asyncio.sleep(0.5)
                continue

            try:
                got_done = False
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            got_done = True
                            await resp.aclose()
                            return
                        yield json.loads(data)
                await resp.aclose()
                if not got_done:
                    logger.warning("Stream ended without [DONE] marker, yielding synthetic stop")
                    yield {"choices": [{"delta": {}, "finish_reason": "stop"}]}
                return
            except (httpx.ReadError, httpx.RemoteProtocolError, ConnectionError) as e:
                last_error = e
                try:
                    await resp.aclose()
                except Exception:
                    pass
                logger.warning(f"Stream read error ({provider.model}), "
                             f"trying next provider ({provider_idx + 1}/{len(providers)})")
                if provider_idx < len(providers) - 1:
                    await asyncio.sleep(1.0)
                    continue
            except Exception as e:
                last_error = e
                try:
                    await resp.aclose()
                except Exception:
                    pass
                logger.warning(f"Stream read error ({provider.model}): {e}")
                if provider_idx == len(providers) - 1:
                    raise

        raise RuntimeError(f"All stream providers failed. Last error: {last_error}")

