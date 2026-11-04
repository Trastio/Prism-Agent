"""显著性实验判定单（2026-11-02 预注册口径）

只读 eval/reports/*.json，不改判分、不重算分数。
主检验：题级通过（该臂 ≥75% 跑次 rubric.pass）→ McNemar 精确单侧（stats.mcnemar_exact）
区间：不一致对中"改善占比"的 Clopper-Pearson 95% CI

用法：
  python eval/exp_analyze.py --reports <r1.json> <r2.json> ... --out eval/reports/significance-2026-11-02.json
  （不传 --tasks 时自动取报告里 set=experiment 的题 + config-07）
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stats import mcnemar_exact, clopper_pearson  # noqa: E402

PASS_RATE = 0.75  # 预注册：该臂 6 次运行中 ≥4 次（4 次运行中 ≥3 次）


def load_results(paths):
    rows = []
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        for r in data.get("results", []):
            rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", nargs="+", required=True)
    ap.add_argument("--tasks", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    rows = load_results(args.reports)
    if args.tasks:
        tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
    else:
        tasks = sorted({r["task"] for r in rows
                        if r.get("task") == "config-07"
                        or str(r.get("task", "")).startswith("pool-")
                        or str(r.get("task", "")).startswith("a2-")})

    per = {}
    for t in tasks:
        for arm in ("A", "B"):
            sel = [r for r in rows if r.get("task") == t and r.get("arm") == arm]
            scores = [r.get("score", 0) for r in sel]
            passes = [bool((r.get("rubric") or {}).get("pass")) for r in sel]
            per[(t, arm)] = {
                "n": len(sel),
                "pass_n": sum(passes),
                "pass": (sum(passes) / len(sel) >= PASS_RATE) if sel else None,
                "median": statistics.median(scores) if scores else None,
                "scores": scores,
                "duration_s": sum((r.get("cost") or {}).get("duration_s") or 0 for r in sel),
            }

    pairs, n01, n10, dropped = [], 0, 0, []
    for t in tasks:
        a, b = per[(t, "A")], per[(t, "B")]
        if a["n"] < 2 or b["n"] < 2 or a["pass"] is None or b["pass"] is None:
            dropped.append({"task": t, "reason": f"成对不足（A n={a['n']} / B n={b['n']}）"})
            continue
        pairs.append({"task": t, "A_pass": a["pass"], "B_pass": b["pass"]})
        if not a["pass"] and b["pass"]:
            n01 += 1
        elif a["pass"] and not b["pass"]:
            n10 += 1

    p = mcnemar_exact(n01, n10, "greater") if (n01 + n10) > 0 else 1.0
    ci = clopper_pearson(n01, n01 + n10) if (n01 + n10) > 0 else (0.0, 1.0)
    b_total = n01 + n10
    significant = (n01 + n10) >= 5 and p < 0.05 and n10 == 0
    verdict = "显著改善" if significant else "未达统计显著"

    print(f"{'题':<12}{'A 通过':<8}{'B 通过':<8}{'A 中位':<8}{'B 中位':<8}")
    for t in tasks:
        a, b = per[(t, "A")], per[(t, "B")]
        print(f"{t:<12}{str(a['pass']):<8}{str(b['pass']):<8}{str(a['median']):<8}{str(b['median']):<8}"
              f"  A[{','.join(map(str, a['scores']))}] B[{','.join(map(str, b['scores']))}]")
    print(f"\n不一致对：改善 n01={n01}，退化 n10={n10}，合计 b={b_total}")
    print(f"McNemar 精确单侧 p={p:.5f}；改善占比 {n01}/{b_total if b_total else 0}"
          f" 的 CP 95% CI = [{ci[0]:.3f}, {ci[1]:.3f}]")
    print(f"判定：{verdict}（门槛 b≥5 且 p<0.05；本例 b={b_total}）")
    if dropped:
        print(f"剔除单元：{len(dropped)} 题 —— " + "; ".join(f"{d['task']}({d['reason']})" for d in dropped))

    out = {
        "reports": args.reports,
        "pass_rate_threshold": PASS_RATE,
        "per_task": {f"{t}|{arm}": v for (t, arm), v in per.items()},
        "pairs": pairs,
        "n01": n01, "n10": n10, "b": b_total,
        "p_one_sided_exact": p,
        "improve_share_ci95": {"point": (n01 / b_total) if b_total else None, "lo": ci[0], "hi": ci[1]},
        "verdict": verdict,
        "dropped": dropped,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n判定 JSON: {args.out}")


if __name__ == "__main__":
    main()
