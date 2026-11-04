"""每周随机抽样已分析帖做交叉验证（双模型 GLM vs DeepSeek），输出不一致率报告。

背景（C4）：分析管线一次定型——帖入库时由 GLM 判 sentiment，此后不重判。
LLM 存在系统性偏差（如营销号一律判正、短文本误判中性），需定期抽检校准。
本脚本随机抽 N 条已分析帖，用 DeepSeek 重新判 sentiment，与库内 GLM 结论
对比，输出不一致率与逐条 diff，供人工复核。

双模型交叉验证前提：GLM 与 DeepSeek 同时配置（.secrets 里 glm + deepseek
都有 api_key）。仅配 GLM 时无法交叉验证——脚本退化为"输出 GLM 结论 + 原文
供人工标注"模式（仍可用于人审抽检）。

用法:
    python scripts/llm_qa_sample.py --vehicle 风云T7 --sample-size 20
    python scripts/llm_qa_sample.py --vehicle M03 --sample-size 30 --seed 42
"""
import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 复用分析管线的组合 prompt（保证 DeepSeek 判 sentiment 与 GLM 同口径）
from pipeline.analysis.analyzer import COMBINED_ANALYSIS_PROMPT, EVENT_TAG_POOL, _format_confusables
from utils.config import load_api_config
from utils.llm_helpers import extract_json_object

_DS_DEFAULT_URL = "https://api.deepseek.com/v1/chat/completions"
_VALID_SENTIMENTS = {"positive", "negative", "neutral"}


def _deepseek_config() -> tuple[str, str, str] | None:
    """返回 DeepSeek (api_key, api_url, model)；未配置返回 None。"""
    config = load_api_config()
    ds = config.get("deepseek", {}) or {}
    if not ds.get("api_key"):
        return None
    return (
        ds["api_key"],
        ds.get("api_url", _DS_DEFAULT_URL),
        ds.get("model", "deepseek-chat"),
    )


def _glm_config() -> tuple[str, str, str] | None:
    """返回 GLM (api_key, api_url, model)；未配置返回 None。"""
    config = load_api_config()
    glm = config.get("glm", {}) or {}
    if not glm.get("api_key"):
        return None
    base = glm.get("base_url", "https://open.bigmodel.cn/api/paas/v4")
    return (glm["api_key"], f"{base}/chat/completions",
            glm.get("model", "glm-4-flash"))


async def _call_model(api_key: str, api_url: str, model: str, prompt: str) -> str:
    """单次 chat completion 调用（无 retry，抽检场景失败即标该条无法验证）。"""
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            api_url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def _parse_sentiment(raw: str) -> str:
    """从 LLM 响应里提取 sentiment，非法/缺失回退 neutral（对齐 analyzer 口径）。"""
    data = extract_json_object(raw)
    if not data:
        return "neutral"
    s = data.get("sentiment", "neutral")
    return s if s in _VALID_SENTIMENTS else "neutral"


async def qa_sample(vehicle_name: str, sample_size: int = 20, seed: int | None = None):
    """随机抽 N 帖，用 DeepSeek 重新判 sentiment，与库内 GLM 结果对比。

    DeepSeek 未配置时退化为人工核对模式：只输出 GLM 库内结论 + 原文，
    不计算不一致率（无法交叉验证）。
    """
    from models.database import async_session
    from models.schemas import AnalyzedPost, RawPost, Vehicle
    from sqlalchemy import select

    ds_cfg = _deepseek_config()
    glm_cfg = _glm_config()
    # 主分析 provider（库内结论来源），用于报告标注
    if glm_cfg:
        primary_provider, primary_model = "glm", glm_cfg[2]
    elif _deepseek_config():
        primary_provider, primary_model = "deepseek", ds_cfg[2]
    else:
        primary_provider, primary_model = "（未配置）", ""

    async with async_session() as session:
        vehicle = (await session.execute(
            select(Vehicle).where(Vehicle.name.like(f"%{vehicle_name}%"))
        )).scalar_one_or_none()
        if not vehicle:
            print(f"[FAIL] 未找到车型: {vehicle_name}")
            return 1
        rows = (await session.execute(
            select(AnalyzedPost, RawPost).join(RawPost, AnalyzedPost.post_id == RawPost.id)
            .where(AnalyzedPost.vehicle_id == vehicle.id)
        )).all()
        if not rows:
            print(f"[FAIL] {vehicle.name} 无已分析帖")
            return 1

        rng = random.Random(seed)
        sample = rng.sample(rows, min(sample_size, len(rows)))

        print(f"\n=== LLM 判错抽检报告 ===")
        print(f"车型: {vehicle.name}（{len(rows)} 已分析帖，抽样 {len(sample)}）")
        print(f"库内结论来源: {primary_provider}/{primary_model}")

        if not ds_cfg:
            # 退化模式：无 DeepSeek 无法交叉验证，输出 GLM 结论供人工核对
            print(f"交叉验证模型: 未配置 DeepSeek → 无法交叉验证，以下为库内结论供人工核对\n")
            for i, (ap, rp) in enumerate(sample, 1):
                text = (rp.title + " " + (rp.content or "")).strip()
                print(f"[{i}/{len(sample)}] id={ap.id[:8]} sentiment={ap.sentiment} "
                      f"confidence={ap.confidence or 0:.2f}")
                print(f"    标题: {(rp.title or '')[:60]}")
                print(f"    正文: {text[:120]}")
                print()
            print("提示: 在 .secrets 配置 deepseek.api_key 后可启用双模型交叉验证。")
            return 0

        # 双模型交叉验证模式
        print(f"交叉验证模型: deepseek/{ds_cfg[2]}\n")
        mismatches = 0
        unverifiable = 0
        diffs: list[dict] = []
        for i, (ap, rp) in enumerate(sample, 1):
            text = ((rp.title or "") + " " + (rp.content or "")).strip()
            if not text:
                unverifiable += 1
                print(f"[{i}/{len(sample)}] id={ap.id[:8]} 空文本，跳过")
                continue
            prompt = COMBINED_ANALYSIS_PROMPT.format(
                event_tags="、".join(EVENT_TAG_POOL),
                vehicle_name=vehicle.name,
                vehicle_brand=vehicle.brand or "",
                confusables=_format_confusables([], vehicle.name),  # v3：prompt 新占位符（QA 交叉验证无需清单）
                text=text,
            )
            try:
                raw = await _call_model(ds_cfg[0], ds_cfg[1], ds_cfg[2], prompt)
                ds_sentiment = _parse_sentiment(raw)
            except Exception as e:
                unverifiable += 1
                print(f"[{i}/{len(sample)}] id={ap.id[:8]} DeepSeek 调用失败: {e}")
                continue
            glm_sentiment = ap.sentiment
            match = ds_sentiment == glm_sentiment
            if not match:
                mismatches += 1
                diffs.append({
                    "id": ap.id, "glm": glm_sentiment, "deepseek": ds_sentiment,
                    "title": (rp.title or "")[:60],
                })
            marker = "✓" if match else "✗ MISMATCH"
            print(f"[{i}/{len(sample)}] id={ap.id[:8]} "
                  f"GLM={glm_sentiment} DS={ds_sentiment} {marker}")

        verified = len(sample) - unverifiable
        rate = mismatches / verified if verified else 0
        print(f"\n--- 汇总 ---")
        print(f"抽样 {len(sample)} 帖：可验证 {verified}，不一致 {mismatches}，"
              f"无法验证 {unverifiable}")
        print(f"不一致率: {rate:.0%}（可验证样本）")
        if diffs:
            print(f"\n不一致明细（共 {len(diffs)} 条，供人工复核）:")
            for d in diffs:
                print(f"  id={d['id'][:8]} GLM={d['glm']} → DS={d['deepseek']}  "
                      f"标题: {d['title']}")
        return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="LLM 判错抽检（GLM vs DeepSeek 交叉验证）")
    ap.add_argument("--vehicle", required=True, help="车名（子串匹配）")
    ap.add_argument("--sample-size", type=int, default=20, help="抽样数量（默认 20）")
    ap.add_argument("--seed", type=int, default=None, help="随机种子（可复现）")
    args = ap.parse_args()

    async def _run_with_dispose():
        # engine 是模块级全局，asyncio.run 关循环后连接池的 aiosqlite 后台线程
        # 无循环清理会导致进程挂死不退出（2026-09-29 实证）。末尾显式 dispose。
        from models.database import engine
        try:
            return await qa_sample(args.vehicle, args.sample_size, args.seed)
        finally:
            await engine.dispose()

    sys.exit(asyncio.run(_run_with_dispose()))
