"""61 项概念配置映射校对（dashboard-v6 Task 9）。

遍历 config_snapshots 快照 × concept_configs 61 项，对每系取第一个版型跑
extract_concept，统计命中率与 miss 原因，输出报告 JSON + 升序摘要。

用法：
  python scripts/audit_concept_mapping.py                          # 首跑
  python scripts/audit_concept_mapping.py --snapshots-dir <DIR>    # 指定快照目录
  python scripts/audit_concept_mapping.py --compare docs/concept_mapping_audit.json
      # 修正 ah_param 后复跑：输出前后对比（哪些项命中率提升）

口径说明：
- 能源自适应：energy 不在 energy_scope 的系直接跳过（不计 total），
  纯电车查不到"发动机"类参数不视为 miss。
- hit = tier >= 0（boolean 的 ○=确认没有 也是合法命中）。
- miss 三类：快照无此参数（_find_param 落空）/ 该版型无此参数（值为空或 -）/
  归不了档（抽到值但落不进 tiers）。
- 每项附带 matched_params 计数：实际命中的快照参数名分布，
  用于诊断 contains 是否命中了预期参数（防同名歧义行）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.insights.concept_config import _find_param, _load_configs, extract_concept  # noqa: E402


def _first_spec_id(categories: dict) -> str | None:
    """取快照里第一个出现的 spec_id（全类别扫一遍，第一个 dict 值的键）。"""
    for params in categories.values():
        for v in params.values():
            if isinstance(v, dict) and v:
                return next(iter(v))
    return None


def audit(snapshots_dir: Path) -> dict:
    configs = _load_configs()
    stats: dict[str, dict] = {
        c["id"]: {"hit": 0, "total": 0, "miss": Counter(), "matched": Counter()}
        for c in configs
    }
    files = sorted(snapshots_dir.glob("*.json"))
    if not files:
        print(f"错误：快照目录无 JSON 文件：{snapshots_dir}", file=sys.stderr)
        sys.exit(1)

    for f in files:
        try:
            snap = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"警告：跳过损坏快照 {f.name}: {e}", file=sys.stderr)
            continue
        categories = snap.get("categories") or {}
        if not categories:
            continue
        energy = snap.get("energy") or ""
        spec_id = _first_spec_id(categories)
        if spec_id is None:
            continue
        for cfg in configs:
            scope = cfg.get("energy_scope", ["纯电", "增程", "插混"])
            if energy not in scope:
                continue  # 能源不适用：不计入分母（与 score_concept 口径一致）
            st = stats[cfg["id"]]
            st["total"] += 1
            pname, _raw = _find_param(
                categories, cfg["ah_category"], cfg["ah_param"], cfg.get("match", "contains")
            )
            r = extract_concept(cfg["id"], categories, spec_id)
            if r.get("tier", -1) >= 0:
                st["hit"] += 1
                if pname:
                    st["matched"][pname] += 1
            else:
                note = r.get("note")
                if note == "快照无此参数":
                    st["miss"]["快照无此参数"] += 1
                elif note == "该版型无此参数":
                    st["miss"]["该版型无此参数"] += 1
                else:
                    st["miss"]["归不了档"] += 1

    report: dict = {}
    for cfg in configs:
        st = stats[cfg["id"]]
        total = st["total"]
        report[cfg["id"]] = {
            "name": cfg["name"],
            "hit_rate": round(st["hit"] / total, 4) if total else None,
            "hit_n": st["hit"],
            "total": total,
            "miss_reasons": dict(st["miss"]),
            "matched_params": dict(st["matched"].most_common(8)),
        }
    return report


def print_summary(report: dict) -> None:
    rows = sorted(
        ((v["hit_rate"] if v["hit_rate"] is not None else -1, k) for k, v in report.items()),
    )
    print(f"共 {len(rows)} 项，按命中率升序（最差 15 项）：\n")
    print(f"{'ID':<5}{'名称':<14}{'命中率':>8}  {'hit/total':>10}  miss_reasons")
    for rate, cid in rows[:15]:
        v = report[cid]
        rate_s = "  n/a " if rate < 0 else f"{rate:6.1%}"
        miss = "; ".join(f"{k}={n}" for k, n in v["miss_reasons"].items()) or "-"
        print(f"{cid:<5}{v['name']:<14}{rate_s}  {v['hit_n']:>4}/{v['total']:<5}  {miss}")


def print_compare(before: dict, after: dict) -> None:
    print("\n==== 修正前后对比（仅列变化项）====")
    print(f"{'ID':<5}{'名称':<14}{'前':>8}{'后':>8}{'Δ(pp)':>8}")
    changed = 0
    for cid in sorted(after, key=lambda c: (before.get(c, {}).get("hit_rate") or 0)):
        a, b = before.get(cid), after[cid]
        if not a or a["hit_rate"] is None or b["hit_rate"] is None:
            continue
        delta = b["hit_rate"] - a["hit_rate"]
        if abs(delta) < 1e-9:
            continue
        changed += 1
        print(f"{cid:<5}{b['name']:<14}{a['hit_rate']:>7.1%}{b['hit_rate']:>7.1%}"
              f"{delta * 100:>+7.1f}")
    if not changed:
        print("（无变化）")
    print(f"\n共 {changed} 项命中率变化。")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="61 项概念配置映射校对")
    ap.add_argument("--snapshots-dir", default=str(REPO / "data" / "config_snapshots"),
                    help="快照 JSON 目录（默认 data/config_snapshots）")
    ap.add_argument("--out", default=str(REPO / "docs" / "concept_mapping_audit.json"),
                    help="报告输出路径")
    ap.add_argument("--compare", default=None,
                    help="修正前报告路径：复跑时输出前后对比")
    args = ap.parse_args()

    report = audit(Path(args.snapshots_dir))
    out = Path(args.out)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已写入 {out}")
    print_summary(report)
    if args.compare:
        before = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        print_compare(before, report)


if __name__ == "__main__":
    main()
