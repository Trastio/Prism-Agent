"""车质网 seriesId 查找/补齐脚本（remove-oneapi T2.5）。

背景：ChezhiwangCollector.SERIES_ID_MAP 只配了 4 车，其余在监车型
resolve_series_id 返回 None 被静默跳过（投诉数据全缺）。

seriesId 权威来源：车质网前端字典 brandsHaveSeries.js
（https://www.12365auto.com/js/brandsHaveSeries.js，GBK 编码，~880KB），
结构：brand.config[].config[] = {seriesId, seriesName, ...}，全网车系
一网打尽——比按车名搜车系页稳（搜索页有同名车系歧义）。

用法（conda base python）：
    python scripts/find_chezhiwang_seriesids.py             # 查找+验证
    python scripts/find_chezhiwang_seriesids.py --refresh   # 强制重下字典
    python scripts/find_chezhiwang_seriesids.py --no-verify # 跳过 BBS 探活

流程：
1. 拉（或读缓存 data/brandsHaveSeries.js）字典 → 展平 {seriesId, seriesName,
   brandsName} 索引；
2. 读 DB vehicles，按「紧凑名精确 → 包含（series ⊂ vehicle）」两级匹配；
3. --verify：逐 sid 探 BBS 列表页 title + 帖子链接数（0.5s 礼貌间隔），
   人工核对 title 车名防张冠李戴（实测抓到 Model Y 3511=斯达泰克 的错配）；
4. 与现有 SERIES_ID_MAP 交叉对账，输出冲突与可直接粘贴的补齐块。

歧义裁决（MANUAL_PICKS）：同名拆分车系（如银河A7 拆 EM/EV）取投诉量大的
主销版；依据 BBS 探活实测帖子数，理由随行注释。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.collectors.chezhiwang_collector import SERIES_ID_MAP  # noqa: E402

DICT_URL = "https://www.12365auto.com/js/brandsHaveSeries.js"
DICT_CACHE = Path("data/brandsHaveSeries.js")
LIST_URL = "https://bbs.12365auto.com/seriesforum/{sid}-1-0-0.shtml"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 歧义车系人工裁决：vehicle 名 → (seriesId, 理由)。查到多个候选时以此定夺。
MANUAL_PICKS: dict[str, tuple[int, str]] = {
    # 银河A7 在车质网拆 EM(4283)/EV(4512) 两个车系；BBS 实测 EM 20 帖、
    # EV 1 帖 → 主销 EM 版承投诉主体。
    "银河A7": (4283, "拆分车系取主销 EM 版（BBS 实测 EM 20 帖 vs EV 1 帖）"),
}


def _compact(s: str) -> str:
    """紧凑名：去空白/分隔符 + 小写，容错全半角与大小写差异。"""
    return re.sub(r"[\s·\-_/（）()]+", "", s or "").lower()


def load_series_dict(refresh: bool = False) -> list[dict]:
    """拉取/缓存 brandsHaveSeries.js → 展平的车系行列表。"""
    raw: bytes
    if refresh or not DICT_CACHE.exists():
        with httpx.Client(timeout=30, headers={"User-Agent": UA},
                          follow_redirects=True) as client:
            resp = client.get(DICT_URL)
            resp.raise_for_status()
            raw = resp.content
        DICT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        DICT_CACHE.write_bytes(raw)
        print(f"字典已下载: {DICT_CACHE} ({len(raw)} bytes)")
    else:
        raw = DICT_CACHE.read_bytes()
        print(f"字典读缓存: {DICT_CACHE} ({len(raw)} bytes)")

    # 前缀 "var brandsHaveSeries = "，尾部可能有 ";"；GBK 编码
    text = raw.decode("gbk", errors="replace")
    payload = text.split("=", 1)[1].strip().rstrip(";")
    tree = json.loads(payload)

    rows: list[dict] = []
    for brand in tree:
        brand_name = brand.get("name") or ""
        for sub in brand.get("config") or []:
            sub_name = sub.get("brandsName") or brand_name
            for s in sub.get("config") or []:
                rows.append({
                    "seriesId": s.get("seriesId"),
                    "seriesName": s.get("seriesName") or "",
                    "brandsName": sub_name,
                })
    return rows


def match_vehicle(name: str, index: dict[str, dict]) -> tuple[dict | None, list[dict], str]:
    """两级匹配：紧凑名精确 → series ⊂ vehicle 包含（防品牌前缀差异）。

    Returns (命中行 or None, 候选列表, 匹配方式)。
    """
    cv = _compact(name)
    if cv in index:
        return index[cv], [], "exact"
    # 包含匹配：车名常带品牌前缀（"特斯拉model 3" ⊃ "Model 3"）。
    # 最短 4 字符护栏：防 "Model Y" 命中 "Model Y L" 这类短前缀误伤——
    # 先按长度降序排，长的车系名优先（更具体的赢）。
    contains = [r for c, r in index.items()
                if len(c) >= 4 and c in cv]
    if contains:
        contains.sort(key=lambda r: len(_compact(r["seriesName"])), reverse=True)
        return contains[0], contains[1:], "contains"
    return None, [], ""


async def verify_sid(client: httpx.AsyncClient, sid: int) -> tuple[str, int]:
    """探 BBS 列表页：返回 (页面 title, 帖子链接数)。title 车名供人工核对。"""
    try:
        resp = await client.get(LIST_URL.format(sid=sid))
        text = resp.content.decode("utf-8", errors="replace")
        m = re.search(r"<title>\s*([^<]+?)\s*</title>", text)
        title = (m.group(1) if m else "").replace(" - 车质网", "").strip()
        links = len(re.findall(r"threadforum/\d{8}/\d+\.shtml", text))
        return title, links
    except Exception as e:
        return f"探活失败: {e}", -1


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="强制重下字典")
    parser.add_argument("--no-verify", action="store_true",
                        help="跳过 BBS 探活（不核 title/帖子数）")
    args = parser.parse_args()

    rows = load_series_dict(refresh=args.refresh)
    index: dict[str, dict] = {}
    for r in rows:
        index.setdefault(_compact(r["seriesName"]), r)

    db_path = os.getenv("DB_PATH", "data/vehicle_sentiment.db")
    con = sqlite3.connect(db_path)
    vehicles = [r[0] for r in con.execute(
        "SELECT name FROM vehicles ORDER BY name").fetchall()]
    con.close()
    print(f"\n在监车辆 {len(vehicles)} 辆：\n")

    results: list[tuple[str, dict | None, str]] = []
    for name in vehicles:
        hit, cands, how = match_vehicle(name, index)
        if name in MANUAL_PICKS:
            sid, reason = MANUAL_PICKS[name]
            hit = next((r for r in rows if r["seriesId"] == sid), None)
            how = f"manual ({reason})"
            # 同名拆分车系全部列出（银河A7 → EM/EV），裁决理由见 MANUAL_PICKS
            prefix = _compact(name)
            cands = [r for r in rows if _compact(r["seriesName"]).startswith(prefix)
                     and r["seriesId"] != sid]
        results.append((name, hit, how))
        if hit:
            extra = f"；候选 {len(cands)} 个" if cands else ""
            print(f"  {name:12s} -> {hit['seriesId']:5d} "
                  f"({hit['seriesName']} @ {hit['brandsName']}) [{how}]{extra}")
        else:
            print(f"  {name:12s} -> 未收录（车质网无该车系，可能无投诉）")

    if not args.no_verify:
        print("\nBBS 探活（title 核对 + 首页帖子数）：")
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": UA},
                                     follow_redirects=True) as client:
            for name, hit, how in results:
                if not hit:
                    continue
                title, links = await verify_sid(client, hit["seriesId"])
                print(f"  sid={hit['seriesId']:5d} title={title!r} 首页帖数={links}")
                await asyncio.sleep(0.5)

    # 与现有 SERIES_ID_MAP 对账：既有条目查得的 id 不一致 = 疑似错配
    print("\n与现有 SERIES_ID_MAP 对账：")
    conflicts = []
    for key, old_sid in SERIES_ID_MAP.items():
        hit, _, how = match_vehicle(key, index)
        if hit and hit["seriesId"] != old_sid:
            conflicts.append((key, old_sid, hit))
    if conflicts:
        for key, old_sid, hit in conflicts:
            print(f"  ⚠ {key}: map={old_sid} vs 查得={hit['seriesId']} "
                  f"({hit['seriesName']} @ {hit['brandsName']}) —— 现值疑错配，需替换")
    else:
        print("  既有条目全部一致 ✓")

    # 可直接粘贴的补齐块
    print("\n# ── SERIES_ID_MAP 补齐（查得值，粘贴前人工过目）─────────────────")
    for name, hit, how in results:
        if hit:
            print(f'    "{name}": {hit["seriesId"]},')
    missing = [name for name, hit, _ in results if not hit]
    if missing:
        print(f"# 未收录（无 seriesId，resolve_series_id 跳过）：{missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
