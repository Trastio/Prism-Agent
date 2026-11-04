"""极性单任务一致性实验：DeepSeek v4-flash vs Qwen3-4B 微调（换引擎前置实验）。

背景：旧实验（absa_prompt_experiment.py）证伪的是"维度+极性"双任务；
2026-10-16 起评论降级只判极性（comment_polarity），单任务从未对比过。
本实验回答：DeepSeek 直出极性与微调模型的一致率是否达到切换门槛。

设计（对齐 absa_prompt_experiment.py 框架）：
- 样本：post_comments.comment_polarity in (1/0/-1)（微调极性直出历史产出），
  按库内真实比例分层随机抽 N 条（seed=42，样本 ID 落盘可复现）
- 对照：comment_polarity（微调产出——注意它是"现任"不是金标；
  一致率衡量的是换引擎口径漂移，谁对谁错由 40 条分歧人工仲裁）
- 实验组：DeepSeek（api.deepseek.com，key 解析 env > .secrets > pi auth.json，
  全程不打印密钥）；prompt=POLARITY_SYSTEM_PROMPT 去 /no_think（Qwen3 专用
  控制符，对 DeepSeek 是噪声——旧实验对 GLM 同样剥离）
- 指标：解析成功率 / 3x3 混淆矩阵 / 总一致率 / 逐类一致率 /
  负面召回（微调-1 且 DS-1，看板最关键信号）/ 负面扩张精度（DS-1 中微调
  也为 -1 的占比，防负面率虚高）/ Cohen's kappa / token 用量
- 产出：scripts/polarity_experiment_result.json + _detail.jsonl +
  polarity_arbitration_sample.md（40 条分歧给用户仲裁）

用法：
  python scripts/deepseek_polarity_experiment.py --smoke   # 先冒烟：模型名/thinking开关/单条
  python scripts/deepseek_polarity_experiment.py [N]       # N 默认 1000
"""
import asyncio
import json
import os
import random
import sqlite3
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.analysis.local_absa import POLARITY_SYSTEM_PROMPT, parse_polarity_output  # noqa: E402

DB = Path(__file__).resolve().parent.parent / "data" / "vehicle_sentiment.db"
OUT = Path(__file__).resolve().parent / "polarity_experiment_result.json"
DETAIL = Path(__file__).resolve().parent / "polarity_experiment_detail.jsonl"
ARBITRATION_MD = Path(__file__).resolve().parent / "polarity_arbitration_sample.md"
CONCURRENCY = 20
_VALID = {"1", "0", "-1"}
_API_URL = "https://api.deepseek.com/v1/chat/completions"
_MODEL_CANDIDATES = [os.environ.get("DS_MODEL", "deepseek-v4-flash"), "deepseek-chat"]
# /no_think 是 Qwen3 控制符；DeepSeek prompt 剥掉（口径：仅指令+文本）
EXP_PROMPT = POLARITY_SYSTEM_PROMPT.replace("/no_think", "").strip()


def resolve_api_key() -> tuple[str, str]:
    """key 解析顺序：env > 舆情 .secrets > pi auth.json。返回 (key, 来源)。"""
    k = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if k:
        return k, "env"
    secrets = Path(__file__).resolve().parent.parent / ".secrets"
    try:
        cfg = json.loads(secrets.read_text(encoding="utf-8"))
        k = (cfg.get("deepseek") or {}).get("api_key", "")
        if k:
            return k, ".secrets"
    except Exception:
        pass
    try:
        d = json.loads(Path(os.path.expanduser("~/.pi/agent/auth.json")).read_text(encoding="utf-8"))
        k = (d.get("deepseek") or {}).get("key", "")
        if k:
            return k, "pi-auth"
    except Exception:
        pass
    return "", "none"


def load_sample(n: int):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT id, content, comment_polarity FROM post_comments "
        "WHERE comment_polarity IN ('1','0','-1') AND content IS NOT NULL AND length(content) >= 4"
    ).fetchall()
    conn.close()
    groups = {"-1": [], "0": [], "1": []}
    for r in rows:
        if r[2] in groups:
            groups[r[2]].append(r)
    total = sum(len(v) for v in groups.values())
    sample = []
    for k, v in groups.items():
        take = round(n * len(v) / total) if total else 0
        sample.extend(random.sample(v, min(take, len(v))))
    random.shuffle(sample)
    return sample[:n], {k: len(v) for k, v in groups.items()}


async def _post(client, api_key, model, messages, thinking_off, max_tokens, timeout=60):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.1}
    if thinking_off:
        body["thinking"] = {"type": "disabled"}
    resp = await client.post(_API_URL, headers={"Authorization": f"Bearer {api_key}"}, json=body)
    return resp


async def smoke(api_key: str) -> tuple[str, bool]:
    """解析可用模型名 + thinking 能否关。返回 (model, thinking_off)。"""
    async with httpx.AsyncClient(timeout=30) as c:
        for model in _MODEL_CANDIDATES:
            for thinking_off in (True, False):
                try:
                    r = await _post(c, api_key, model,
                                    [{"role": "user", "content": "判断这条评论的情感倾向，只输出一个数字（1、0 或 -1）：这车真好开"}],
                                    thinking_off, max_tokens=8)
                except Exception as e:
                    print(f"  [{model}] thinking_off={thinking_off} 网络异常: {str(e)[:100]}")
                    continue
                if r.status_code == 200:
                    content = r.json()["choices"][0]["message"]["content"]
                    usage = r.json().get("usage", {})
                    print(f"  ✓ 模型={model} thinking_off={thinking_off} 回复={content!r} "
                          f"completion_tokens={usage.get('completion_tokens')}")
                    return model, thinking_off
                err = r.text[:160].replace("\n", " ")
                # thinking 参数不识别 → 换 thinking_off=False 再试同模型
                if r.status_code == 400 and thinking_off and "thinking" in err.lower():
                    continue
                print(f"  [{model}] thinking_off={thinking_off} HTTP {r.status_code}: {err}")
                if r.status_code in (401, 403):
                    raise SystemExit("DeepSeek 认证失败——检查 key 来源")
                break  # 该模型不可用（大概率模型名错），换下一个
    raise SystemExit("没有可用模型名（v4-flash / chat 均 400）")


async def label_one(sem, client, api_key, model, thinking_off, row):
    cid, content, _ft = row
    messages = [
        {"role": "system", "content": EXP_PROMPT},
        {"role": "user", "content": content.strip()[:400]},
    ]
    async with sem:
        for attempt in range(3):
            try:
                r = await _post(client, api_key, model, messages, thinking_off,
                                max_tokens=8 if thinking_off else 1024)
                if r.status_code == 200:
                    data = r.json()
                    raw = data["choices"][0]["message"]["content"]
                    return {"id": cid, "pred": parse_polarity_output(raw), "raw": raw[:60],
                            "err": None, "usage": data.get("usage", {})}
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    return {"id": cid, "pred": None, "raw": "", "err": f"http{r.status_code}", "usage": {}}
            except (httpx.TimeoutException, httpx.TransportError):
                pass
            await asyncio.sleep(2 * (attempt + 1))
    return {"id": cid, "pred": None, "raw": "", "err": "exhausted", "usage": {}}


def kappa(matrix, n):
    if not n:
        return 0.0
    po = sum(matrix[a][a] for a in _VALID) / n
    row = {a: sum(matrix[a].values()) / n for a in _VALID}
    col = {b: sum(matrix[a][b] for a in _VALID) / n for b in _VALID}
    pe = sum(row[a] * col[a] for a in _VALID)
    return (po - pe) / (1 - pe) if pe < 1 else 0.0


def main():
    args = [a for a in sys.argv[1:]]
    api_key, src = resolve_api_key()
    if not api_key:
        raise SystemExit("未找到 DeepSeek key（env/.secrets/pi-auth 均无）")
    print(f"key 来源: {src}（内容不显示）")

    model, thinking_off = asyncio.run(smoke(api_key))
    if "--smoke" in args:
        return

    n = int(next((a for a in args if a.isdigit()), 1000))
    random.seed(42)
    sample, pop = load_sample(n)
    print(f"样本 {len(sample)} 条（库内分布 {pop}），模型 {model} thinking_off={thinking_off}，"
          f"并发 {CONCURRENCY}，开始打标…")

    async def run_all():
        sem = asyncio.Semaphore(CONCURRENCY)
        results = []
        async with httpx.AsyncClient(timeout=60) as client:
            futs = [label_one(sem, client, api_key, model, thinking_off, r) for r in sample]
            done = 0
            for fut in asyncio.as_completed(futs):
                results.append(await fut)
                done += 1
                if done % 200 == 0:
                    print(f"  进度 {done}/{len(sample)}")
        return results

    results = asyncio.run(run_all())
    by_id = {r["id"]: r for r in results}
    ft_by_id = {r[0]: r[2] for r in sample}
    content_by_id = {r[0]: r[1] for r in sample}

    # 3x3 混淆矩阵：行=微调(ft)，列=DeepSeek(ds)
    matrix = {a: {b: 0 for b in _VALID} for a in _VALID}
    stats = {"n": len(sample), "engine": f"{model}(thinking_off={thinking_off})",
             "parse_ok": 0, "llm_err": 0, "prompt_tokens": 0, "completion_tokens": 0}
    disagreements = []
    for cid, r in by_id.items():
        if r["err"]:
            stats["llm_err"] += 1
            continue
        stats["parse_ok"] += 1
        u = r.get("usage") or {}
        stats["prompt_tokens"] += u.get("prompt_tokens", 0)
        stats["completion_tokens"] += u.get("completion_tokens", 0)
        ft, ds = ft_by_id[cid], r["pred"]
        if ds in _VALID:
            matrix[ft][ds] += 1
            if ft != ds:
                disagreements.append({"id": cid, "ft": ft, "ds": ds, "raw": r["raw"]})

    ok = stats["parse_ok"]
    n_cmp = sum(matrix[a][b] for a in _VALID for b in _VALID)
    conf = {a: dict(matrix[a]) for a in _VALID}
    agree = sum(matrix[a][a] for a in _VALID)
    neg_total = matrix["-1"]["-1"] + matrix["-1"]["0"] + matrix["-1"]["1"]
    ds_neg_total = matrix["-1"]["-1"] + matrix["0"]["-1"] + matrix["1"]["-1"]
    summary = {
        **stats,
        "confusion_ft_row_ds_col": conf,
        "n_compared": n_cmp,
        "overall_agreement": round(agree / n_cmp, 4) if n_cmp else 0,
        "per_class_agreement": {
            a: round(matrix[a][a] / sum(matrix[a].values()), 4) if sum(matrix[a].values()) else None
            for a in _VALID},
        "neg_recall_ft_neg_ds_neg": round(matrix["-1"]["-1"] / neg_total, 4) if neg_total else None,
        "neg_expansion_precision": round(matrix["-1"]["-1"] / ds_neg_total, 4) if ds_neg_total else None,
        "cohens_kappa": round(kappa(matrix, n_cmp), 4),
        "disagreements": len(disagreements),
    }

    # 40 条仲裁样本：A=微调负DS非负（最关键，20）B=DS负微调非负（扩张误报，12）C=正中互混（8）
    def pick(pred, cap):
        return [d for d in disagreements if pred(d)][:cap]
    arb = pick(lambda d: d["ft"] == "-1" and d["ds"] != "-1", 20)
    arb += pick(lambda d: d["ft"] != "-1" and d["ds"] == "-1"
                and d not in arb, 12)
    arb += pick(lambda d: {d["ft"], d["ds"]} == {"1", "0"}
                and d not in arb, 8)
    summary["arbitration_ids"] = [d["id"] for d in arb]

    DETAIL.write_text("\n".join(json.dumps(
        {"id": cid, "ft": ft_by_id[cid], "ds": by_id[cid]["pred"],
         "content": content_by_id[cid][:200], "raw": by_id[cid]["raw"], "err": by_id[cid]["err"]},
        ensure_ascii=False) for cid in ft_by_id), encoding="utf-8")
    OUT.write_text(json.dumps({"summary": summary}, ensure_ascii=False, indent=2), encoding="utf-8")

    label_cn = {"1": "正面", "0": "中性", "-1": "负面"}
    lines = ["# 极性分歧仲裁样本（40 条）", "",
             "说明：左=微调 Qwen3-4B 判，右=DeepSeek 判。请你在「你的裁决」行填 1/0/-1"
             "（以你读到评论后的真实判断为准；拿不准可标 ?）。",
             "A 组=微调判负 DeepSeek 不判负（负面召回损失，最关键）；B 组=DeepSeek 判负微调不判负"
             "（负面扩张）；C 组=正面/中性互混。", ""]
    for i, d in enumerate(arb, 1):
        lines.append(f"## {i}. [{d['ft']}→{d['ds']}] {label_cn[d['ft']]} vs {label_cn[d['ds']]}")
        lines.append(f"- 评论：{content_by_id[d['id']][:120]}")
        lines.append(f"- 你的裁决：____")
        lines.append("")
    ARBITRATION_MD.write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    est_cost = (stats["prompt_tokens"] / 1e6) + (stats["completion_tokens"] / 1e6) * 2
    print(f"\n实际用量: in={stats['prompt_tokens']} out={stats['completion_tokens']} "
          f"≈¥{est_cost:.2f}（¥1/M in + ¥2/M out）")
    print(f"结果: {OUT}\n明细: {DETAIL}\n仲裁样本: {ARBITRATION_MD}")


if __name__ == "__main__":
    main()
