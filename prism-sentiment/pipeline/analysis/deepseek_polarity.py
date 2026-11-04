"""评论极性打标引擎：DeepSeek v4-flash（2026-10-20 用户拍板，替代本地 Qwen3-4B）。

切换依据：scripts/deepseek_polarity_experiment.py 1000 条分层对比——
总一致率 69.5% / 负面召回 57.6%，分歧抽样显示扣分项主要是微调的错
（话题触发误报/隐性负面漏检/反讽误读），DeepSeek 口径负面占比 31.5%→24.7%；
未做人工仲裁（用户拍板全自动直切）。
口径断点：2026-10-20 起 comment_polarity 由本引擎判定，此前为微调产出，
跨引擎趋势不作对比（见 openspec/changes/极性引擎切换DeepSeek/）。

key 解析顺序：env DEEPSEEK_API_KEY > .secrets(deepseek.api_key) >
~/.pi/agent/auth.json(deepseek.key)（工位机 pi-auth 兜底；上云写 .secrets/env）。
"""
import asyncio
import json
import os
from pathlib import Path

import httpx

from pipeline.analysis.local_absa import POLARITY_SYSTEM_PROMPT, parse_polarity_output
from utils.config import env_int

_API_URL = "https://api.deepseek.com/v1/chat/completions"
# /no_think 是 Qwen3 控制符，对 DeepSeek 是噪声——与实验脚本同口径剥离
POLARITY_PROMPT = POLARITY_SYSTEM_PROMPT.replace("/no_think", "").strip()

# 仓库根（隔审 P1-1：曾写 parent.parent 差一层算到 pipeline/.secrets，被 pi-auth
# 兜底掩盖；测试 test_default_secrets_path_is_repo_root 钉死此路径）
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SECRETS = _REPO_ROOT / ".secrets"


class DeepSeekPolarityError(Exception):
    """引擎级失败（无 key/认证错/重试耗尽）。调用方捕获后当批不写库留队列。"""


def resolve_api_key(secrets_path: str | None = None, auth_path: str | None = None) -> tuple[str, str]:
    """key 解析顺序：env > .secrets > pi auth.json。返回 (key, 来源)；
    找不到返回 ("", "none")。路径参数仅测试注入用，不打印密钥内容。"""
    k = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if k:
        return k, "env"
    if secrets_path is None:
        secrets_path = str(_DEFAULT_SECRETS)
    try:
        cfg = json.loads(Path(secrets_path).read_text(encoding="utf-8"))
        k = ((cfg.get("deepseek") or {}).get("api_key") or "").strip()
        if k:
            return k, ".secrets"
    except Exception:
        pass
    if auth_path is None:
        auth_path = os.path.expanduser("~/.pi/agent/auth.json")
    try:
        d = json.loads(Path(auth_path).read_text(encoding="utf-8"))
        k = ((d.get("deepseek") or {}).get("key") or "").strip()
        if k:
            return k, "pi-auth"
    except Exception:
        pass
    return "", "none"


async def _post_one(client: httpx.AsyncClient, api_key: str, model: str, content: str) -> str | None:
    """单条打标：返回 "1"/"0"/"-1"/None（不可解析）。

    4xx（非 429）抛 DeepSeekPolarityError（永久错不重试）；5xx/429/超时/传输
    抛 httpx 异常（调用方重试）。thinking 冒烟实证可关（1 词元输出）。
    """
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": POLARITY_PROMPT},
            {"role": "user", "content": content.strip()[:400]},
        ],
        "max_tokens": 8,
        "temperature": 0.1,
        "thinking": {"type": "disabled"},
    }
    resp = await client.post(_API_URL, headers={"Authorization": f"Bearer {api_key}"}, json=body)
    if resp.status_code == 200:
        try:
            data = resp.json()
        except ValueError as e:  # 隔审 P2-2：200 但非 JSON 体——契约错误，不当成功也不穿透裸异常
            raise DeepSeekPolarityError(f"200 响应非 JSON: {e}")
        raw = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return parse_polarity_output(raw)
    if 400 <= resp.status_code < 500 and resp.status_code != 429:
        raise DeepSeekPolarityError(f"http{resp.status_code}: {resp.text[:120]}")
    resp.raise_for_status()  # 5xx/429 → 可重试类
    return None  # pragma: no cover（raise_for_status 非 2xx 必抛）


async def tag_polarity_batch(texts: list[str]) -> list[str | None]:
    """批量极性打标。返回与 texts 等长列表，元素 "1"/"0"/"-1"/None（不可解析）。

    引擎级失败（无 key/认证/重试耗尽）raise DeepSeekPolarityError——
    调用方（batch_runner）捕获后当批不写库，评论留在 NULL 队列下次再标。
    **不写 "none" 哨兵**：传输失败值得重试，区别于真不可解析（重试无益）。
    """
    api_key, _src = resolve_api_key()
    if not api_key:
        raise DeepSeekPolarityError("config: 未找到 DeepSeek key（env/.secrets/pi-auth）")
    model = os.environ.get("DS_POLARITY_MODEL", "deepseek-v4-flash")
    concurrency = env_int("DS_POLARITY_CONCURRENCY", 20)
    timeout = env_int("DS_POLARITY_TIMEOUT", 60)
    sem = asyncio.Semaphore(concurrency)

    async def one(client: httpx.AsyncClient, content: str) -> str | None:
        async with sem:
            last: Exception | None = None
            for attempt in range(3):
                try:
                    return await _post_one(client, api_key, model, content)
                except DeepSeekPolarityError:
                    raise  # 永久错不重试
                except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as e:
                    last = e
                    await asyncio.sleep(2 * (attempt + 1))
            raise DeepSeekPolarityError(f"重试 3 次耗尽: {last}")

    if not texts:
        return []
    async with httpx.AsyncClient(timeout=timeout) as client:
        # 隔审 P2-1：等全部任务落地再判异常（return_exceptions 防首异常时
        # client 在兄弟任务脚下关闭）；任何异常=引擎契约错误，全批不写。
        results = await asyncio.gather(*[one(client, t) for t in texts], return_exceptions=True)
    for r in results:
        if isinstance(r, BaseException):
            if isinstance(r, DeepSeekPolarityError):
                raise r
            raise DeepSeekPolarityError(f"批内非预期异常: {r}")
    return list(results)
