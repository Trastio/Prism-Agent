"""ABSA 引擎一致性实验：LLM prompt vs Qwen3-4B 微调历史标签（上线方案 §7.1 前置实验）。

设计：
- 样本：post_comments.dim_sentiment 非空的评论随机抽 N 条（分层保证含负/正/空标签）
- 对照组：库内 dim_sentiment（微调模型历史产出，JSON dict）
- 实验组：GLM-4-flash（call_llm 双 provider 优先级）零样本 prompt——
  系统指令与 local_absa.SYSTEM_PROMPT 同口径（15 维、1/0/-1、维度#情感|、只输出涉及维度）
- 指标：解析成功率 / 整条完全一致 / (维度,极性)对 P/R/F1 / 维度命中时极性一致率 /
  负面检出召回（看板最关键信号）/ 综合情感一致
- 产出：scripts/absa_experiment_result.json + 控制台摘要 + badcase 样本（前 20）

用法：python scripts/absa_prompt_experiment.py [N]   # N 默认 1000
"""
import asyncio
import json
import os
import random
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.llm_client import call_llm, LLMError, _select_provider  # noqa: E402

from pipeline.analysis.local_absa import SYSTEM_PROMPT, ALL_DIMENSIONS, parse_absa_output  # noqa: E402

# 引擎覆盖（配对实验：ABSA_MODEL=glm-5.3-flash python scripts/absa_prompt_experiment.py 1000）
MODEL_OVERRIDE = os.environ.get("ABSA_MODEL", "")
import httpx  # noqa: E402


async def _call(prompt: str, timeout: int = 60) -> str:
    if not MODEL_OVERRIDE:
        return await call_llm(prompt, timeout=timeout)
    api_key, api_url, _m = _select_provider()
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(api_url, headers={"Authorization": f"Bearer {api_key}"},
                         json={"model": MODEL_OVERRIDE, "messages": [{"role": "user", "content": prompt}],
                               "max_tokens": 2048})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

DB = Path(__file__).resolve().parent.parent / "data" / "vehicle_sentiment.db"
OUT = Path(__file__).resolve().parent / "absa_experiment_result.json"
CONCURRENCY = 20
_VALID = {"1", "0", "-1"}


def load_sample(n: int):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT id, content, dim_sentiment FROM post_comments "
        "WHERE dim_sentiment IS NOT NULL AND content IS NOT NULL AND length(content) >= 4"
    ).fetchall()
    conn.close()
    # 分层：负(含-1) / 正(含1无-1) / 空({}) 按库内真实比例各抽
    def bucket(ds_text: str):
        try:
            d = json.loads(ds_text)
        except Exception:
            return "bad"
        vals = list(d.values()) if isinstance(d, dict) else []
        if not vals:
            return "empty"
        if -1 in vals:
            return "neg"
        return "pos"
    groups = {"neg": [], "pos": [], "empty": []}
    for r in rows:
        b = bucket(r[2])
        if b in groups:
            groups[b].append(r)
    total = sum(len(v) for v in groups.values())
    sample = []
    for k, v in groups.items():
        take = round(n * len(v) / total) if total else 0
        sample.extend(random.sample(v, min(take, len(v))))
    random.shuffle(sample)
    return sample[:n], {k: len(v) for k, v in groups.items()}


async def prompt_label(sem, row):
    cid, content, _gt = row
    # /no_think 是 Qwen3 专用控制符，GLM 会复读它导致空输出——实验组剥掉（冒烟实证）
    sys_prompt = SYSTEM_PROMPT.replace("/no_think", "").strip()
    prompt = f"{sys_prompt}\n\n评论文本：{content.strip()[:400]}\n\n请直接输出\"维度#情感\"格式结果，不要解释。"
    async with sem:
        for attempt in range(3):
            try:
                out = await _call(prompt, timeout=60)
                parsed = parse_absa_output(out)  # 复用微调同款解析器（含 <think> 剥离）
                return {"id": cid, "raw": out[:200], "pred": parsed["dim_sentiment"], "err": None}
            except LLMError as e:
                if attempt == 2:
                    return {"id": cid, "raw": "", "pred": None, "err": f"LLMError:{e}"}
                await asyncio.sleep(2 * (attempt + 1))
            except Exception as e:
                if attempt == 2:
                    return {"id": cid, "raw": "", "pred": None, "err": str(e)[:120]}
                await asyncio.sleep(2 * (attempt + 1))


def pair_set(d: dict):
    return {(k, int(v)) for k, v in d.items()} if isinstance(d, dict) else set()


def overall(d: dict):
    if not d:
        return "neutral"
    vals = list(d.values())
    if any(v == -1 for v in vals) and sum(1 for v in vals if v == -1) > sum(1 for v in vals if v == 1):
        return "negative"
    if any(v == 1 for v in vals):
        return "positive"
    return "neutral"


async def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    random.seed(42)
    sample, pop = load_sample(n)
    print(f"样本 {len(sample)} 条（库内分布 {pop}），并发 {CONCURRENCY}，开始打标…")
    sem = asyncio.Semaphore(CONCURRENCY)
    results = []
    done = 0
    for fut in asyncio.as_completed([prompt_label(sem, r) for r in sample]):
        res = await fut
        results.append(res)
        done += 1
        if done % 100 == 0:
            print(f"  进度 {done}/{len(sample)}")

    by_id = {r["id"]: r for r in results}
    gt_by_id = {r[0]: json.loads(r[2]) for r in sample}
    stats = {
        "n": len(sample), "engine": MODEL_OVERRIDE or "glm-4-flash(call_llm) zero-shot",
        "parse_ok": 0, "llm_err": 0,
        "exact_match": 0,
        "pair_pred": 0, "pair_gt": 0, "pair_hit": 0,
        "dim_hit_pol_match": 0, "dim_hit": 0,
        "neg_gt": 0, "neg_hit": 0, "neg_any_pol": 0,
        "overall_match": 0,
        "empty_both": 0,
        # GT 非中性子集（微调模型给出真实情感 ±1 的评论）——GT 噪声主要集中在
        # 无实义短评被贴"单维度=0"标签，该子集是两引擎真正的可比口径
        "nn_n": 0, "nn_exact": 0, "nn_pair_pred": 0, "nn_pair_gt": 0, "nn_pair_hit": 0,
        "nn_neg_gt": 0, "nn_neg_hit": 0,
    }
    badcases = []
    for cid, pred in by_id.items():
        gt = gt_by_id[cid]
        if pred["err"]:
            stats["llm_err"] += 1
            continue
        stats["parse_ok"] += 1
        p, g = pred["pred"], gt
        ps, gs = pair_set(p), pair_set(g)
        stats["pair_pred"] += len(ps)
        stats["pair_gt"] += len(gs)
        stats["pair_hit"] += len(ps & gs)
        if p == g:
            stats["exact_match"] += 1
            if not g:
                stats["empty_both"] += 1
        elif len(badcases) < 20:
            badcases.append({"id": cid, "gt": g, "pred": p, "raw": pred["raw"][:120]})
        # 维度命中时极性一致
        pmap = {k: v for k, v in (p or {}).items()}
        for dim, gv in g.items():
            if dim in pmap:
                stats["dim_hit"] += 1
                if pmap[dim] == gv:
                    stats["dim_hit_pol_match"] += 1
        # 负面检出
        gnegs = {d for d, v in g.items() if v == -1}
        if gnegs:
            stats["neg_gt"] += 1
            pnegs = {d for d, v in (pmap or {}).items() if v == -1}
            if gnegs & pnegs:
                stats["neg_hit"] += 1
            if gnegs & set(pmap):
                stats["neg_any_pol"] += 1
        if overall(g) == overall(p or {}):
            stats["overall_match"] += 1
        # 非中性子集
        if any(v in (1, -1) for v in g.values()):
            stats["nn_n"] += 1
            nps, ngs = pair_set(p), pair_set(g)
            stats["nn_pair_pred"] += len(nps)
            stats["nn_pair_gt"] += len(ngs)
            stats["nn_pair_hit"] += len(nps & ngs)
            if p == g:
                stats["nn_exact"] += 1
            if any(v == -1 for v in g.values()):
                stats["nn_neg_gt"] += 1
                if any(v == -1 for v in (pmap or {}).values()):
                    stats["nn_neg_hit"] += 1

    ok = stats["parse_ok"]
    prec = stats["pair_hit"] / stats["pair_pred"] if stats["pair_pred"] else 0
    rec = stats["pair_hit"] / stats["pair_gt"] if stats["pair_gt"] else 0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
    summary = {
        **stats,
        "exact_match_rate": round(stats["exact_match"] / ok, 4) if ok else 0,
        "pair_f1": round(f1, 4), "pair_precision": round(prec, 4), "pair_recall": round(rec, 4),
        "pol_consistency_given_dim": round(stats["dim_hit_pol_match"] / stats["dim_hit"], 4) if stats["dim_hit"] else 0,
        "neg_detection_recall": round(stats["neg_hit"] / stats["neg_gt"], 4) if stats["neg_gt"] else 0,
        "overall_match_rate": round(stats["overall_match"] / ok, 4) if ok else 0,
    }
    nn = stats["nn_n"]
    summary["nn_exact_rate"] = round(stats["nn_exact"] / nn, 4) if nn else 0
    nn_prec = stats["nn_pair_hit"] / stats["nn_pair_pred"] if stats["nn_pair_pred"] else 0
    nn_rec = stats["nn_pair_hit"] / stats["nn_pair_gt"] if stats["nn_pair_gt"] else 0
    summary["nn_pair_f1"] = round(2 * nn_prec * nn_rec / (nn_prec + nn_rec), 4) if nn_prec + nn_rec else 0
    summary["nn_neg_detection_recall"] = round(stats["nn_neg_gt"] and stats["nn_neg_hit"] / stats["nn_neg_gt"] or 0, 4)
    detail_path = OUT.with_name("absa_experiment_detail.jsonl")
    with open(detail_path, "w", encoding="utf-8") as f:
        for cid, r in by_id.items():
            f.write(json.dumps({"id": cid, "gt": gt_by_id[cid], "pred": r["pred"], "raw": r["raw"], "err": r["err"]}, ensure_ascii=False) + "\n")
    OUT.write_text(json.dumps({"summary": summary, "badcases": badcases}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"结果已存 {OUT}")

if __name__ == "__main__":
    asyncio.run(main())
