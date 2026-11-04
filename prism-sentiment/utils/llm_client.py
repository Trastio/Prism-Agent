"""共享 LLM 调用层（主题 C 治根）。

双 provider 路由（glm 优先 → deepseek 备选）+ httpx + tenacity retry。
reports 等模块复用，消除散落的 `_call_llm` 重复实现。

F-4/F-5/F-10 修复（2026-09-30）：失败不再吞成字符串返回，改 raise LLMError
区分错误类型；retry 只重试超时/网络错，401/400 永久错不重试；响应解析加防御。
"""
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from utils.config import load_api_config

_GLM_DEFAULT_BASE = "https://open.bigmodel.cn/api/paas/v4"
_DS_DEFAULT_URL = "https://api.deepseek.com/v1/chat/completions"


class LLMError(Exception):
    """LLM 调用失败。kind 区分错误类型，调用方可据此决定 UI 反馈。"""
    def __init__(self, kind: str, msg: str):
        self.kind = kind  # "auth"/"ratelimit"/"timeout"/"parse"/"network"/"config"
        super().__init__(msg)


def _select_provider() -> tuple[str, str, str]:
    """选择 LLM provider，返回 (api_key, api_url, model)；无配置返回 ("", "", "")。"""
    config = load_api_config()
    glm_cfg = config.get("glm", {})
    if glm_cfg.get("api_key"):
        base = glm_cfg.get("base_url", _GLM_DEFAULT_BASE)
        return glm_cfg["api_key"], f"{base}/chat/completions", glm_cfg.get("model", "glm-4-flash")
    ds_cfg = config.get("deepseek", {})
    if ds_cfg.get("api_key"):
        return ds_cfg["api_key"], ds_cfg.get("api_url", _DS_DEFAULT_URL), ds_cfg.get("model", "deepseek-chat")
    return "", "", ""


# F-4：retry 只重试超时/网络错；401/400/限流等永久错不重试（原无 retry= 谓词全重试）
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
    reraise=True,
)
async def _post(api_key: str, api_url: str, model: str, prompt: str, timeout: int) -> str:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                api_url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}]},
            )
            # 401/403 认证错：永久，不重试
            if resp.status_code in (401, 403):
                raise LLMError("auth", f"认证失败 {resp.status_code}: {resp.text[:200]}")
            # 429 限流：不重试（已重试过的话），直接抛给调用方
            if resp.status_code == 429:
                raise LLMError("ratelimit", "LLM 限流，请稍后重试")
            # 4xx 其他：永久错
            if 400 <= resp.status_code < 500:
                raise LLMError("config", f"请求错误 {resp.status_code}: {resp.text[:200]}")
            resp.raise_for_status()
            # F-5：响应解析加防御——限流/空响应时 choices 可能为空
            data = resp.json()
            choices = data.get("choices")
            if not choices or not isinstance(choices, list) or len(choices) == 0:
                raise LLMError("parse", f"LLM 响应无 choices: {str(data)[:200]}")
            content = choices[0].get("message", {}).get("content")
            if not content:
                raise LLMError("parse", f"LLM 响应 content 为空: {str(choices[0])[:200]}")
            return content
    except httpx.TimeoutException:
        raise LLMError("timeout", f"LLM 请求超时（{timeout}s）")
    except httpx.TransportError as e:
        raise LLMError("network", f"网络错误: {e}")
    except LLMError:
        raise  # 已分类的 LLM 错误，向上传播
    except Exception as e:
        raise LLMError("network", f"未知错误: {e}")


async def call_llm(prompt: str, timeout: int = 60) -> str:
    """双 provider 路由 + retry。失败 raise LLMError（不再吞成字符串）。

    无配置 raise LLMError("config")；其余错误由 _post 分类后向上传播。
    调用方应 try/except LLMError 决定 UI 反馈（503/提示），不要把错误当正文落库。
    """
    api_key, api_url, model = _select_provider()
    if not api_key:
        raise LLMError("config", "API 未配置，请在 .secrets 中添加 glm 或 deepseek 配置")
    return await _post(api_key, api_url, model, prompt, timeout)
