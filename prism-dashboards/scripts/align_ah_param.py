"""C1：用 v9 解码后字段名重扫 244 系快照，对齐 concept_configs.json 的 ah_param。
输出：每项 concept 的命中字段名（取众数/最全者）+ 落空项清单。
用法：.venv/Scripts/python.exe scripts/align_ah_param.py [--write]
不传 --write 只打印报告；传 --write 更新 data/concept_configs.json。"""
import json, sys
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from src.insights.concept_config import _load_configs, _find_param
from src.storage.db import init_db, session_scope
from src.models.orm import ConfigSnapshot

init_db()  # 建表/连接（幂等），脚本独立运行需自举 DB


def _broader_find(categories, ah_cat, ah_param):
    """C1 兜底：ah_param contains 匹配不上时，扫该类别下所有字段名，
    取与 ah_param 双向 contains 的最长字段名（解码后完整名）。
    例：ah_param='CLTC纯电续航'（残缺）→ 命中快照 'CLTC纯电续航里程(km)'（完整）。"""
    best_p, best_len = None, 0
    for cat, params in categories.items():
        if cat != ah_cat and not (ah_cat in cat or cat in ah_cat):
            continue
        for p in params:
            if ah_param in p or p in ah_param:
                if len(p) > best_len:
                    best_p, best_len = p, len(p)
    return best_p


def scan_all_snapshots():
    """返回 {concept_id: Counter({field_name: hit_count})} + 落空统计。"""
    configs = _load_configs()
    hits = {c["id"]: Counter() for c in configs}
    miss = {c["id"]: 0 for c in configs}
    total = 0
    with session_scope() as s:
        rows = s.query(ConfigSnapshot.series_id, ConfigSnapshot.categories).all()
        for sid, cats in rows:
            if not cats:
                continue
            total += 1
            for cfg in configs:
                pname, _ = _find_param(cats, cfg["ah_category"], cfg["ah_param"],
                                       cfg.get("match", "contains"))
                if pname is None:
                    # C1 兜底：用双向 contains 扫字段名取最长匹配（解码后完整名）
                    pname = _broader_find(cats, cfg["ah_category"], cfg["ah_param"])
                if pname:
                    hits[cfg["id"]][pname] += 1
                else:
                    miss[cfg["id"]] += 1
    return hits, miss, total


def report():
    hits, miss, total = scan_all_snapshots()
    configs = {c["id"]: c for c in _load_configs()}
    print(f"扫描 {total} 个车系快照")
    print(f"{'id':<6}{'name':<20}{'当前 ah_param':<30}{'命中字段(众数)':<30}{'落空率':<10}")
    align = []
    for cid, counter in hits.items():
        cfg = configs[cid]
        cur = cfg["ah_param"]
        if counter:
            top_field, top_n = counter.most_common(1)[0]
            miss_rate = miss[cid] / total if total else 1
            print(f"{cid:<6}{cfg['name'][:18]:<20}{cur[:28]:<30}{top_field[:28]:<30}{miss_rate:.0%}")
            if top_field != cur and top_n > total * 0.5:
                align.append((cid, cur, top_field))
        else:
            print(f"{cid:<6}{cfg['name'][:18]:<20}{cur[:28]:<30}{'(全落空)':<30}100%")
    print(f"\n需对齐 {len(align)} 项（命中字段与众数 >50% 一致但 ah_param 不同）")
    if "--write" in sys.argv:
        cfgs = _load_configs()
        for cid, old, new in align:
            for c in cfgs:
                if c["id"] == cid:
                    c["ah_param"] = new
                    break
        with open(ROOT / "data" / "concept_configs.json", "w", encoding="utf-8") as f:
            json.dump(cfgs, f, ensure_ascii=False, indent=2)
        print(f"已更新 data/concept_configs.json（{len(align)} 项 ah_param）")
    else:
        print("(传 --write 更新 concept_configs.json)")
    total_miss = sum(miss.values())
    total_items = len(hits) * total
    print(f"\n整体落空率: {total_miss}/{total_items} = {total_miss/total_items:.0%}")


if __name__ == "__main__":
    report()
