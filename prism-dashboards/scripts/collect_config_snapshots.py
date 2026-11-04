"""通用配置快照重采脚本（dashboard-v8 Task 3.2）。

取代 v5 时期硬编码 208 系 + 依赖 docs/30w以下能源类型扫描.json 输入的版本：
- 默认查 config_snapshots 表 series_id 列表（244 系），不依赖 docs 输入
- 逐系调之家配置页 API（autohome_api.get_full_config）采集，upsert 覆盖旧快照
- 断点续采：fetched_at 新于 --max-age-days 阈值 → 跳过
- 限速：每系间隔 --delay 秒，并发 --concurrency
- 进度：每 20 系打印一次
- 保留 --from-docs 路径作为 fallback（新系入库时带 maker/energy/level metadata）

用法：
    # 重采库里全部 244 系（跳过 7 天内采过的）
    python scripts/collect_config_snapshots.py --max-age-days 7

    # 从 docs 扫描名单采（首次入库 / 补采新系）
    python scripts/collect_config_snapshots.py --from-docs docs/30w以下能源类型扫描-2026-09-26.json

可作模块导入：
    collect_snapshots(series_ids=[...], fetch_func=async_fn, max_age_days=7) -> stats dict
    collect_snapshots_from_docs(docs_path, fetch_func=..., max_age_days=...) -> stats dict
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 13 主机厂别名（与 v5 首采脚本同源，--from-docs 路径用）
_MAKERS_ALIASES = {
    '吉利': ['吉利', '领克', '极氪', '银河', '几何', '睿蓝', '枫叶'],
    '比亚迪': ['比亚迪', 'BYD', '腾势', '方程豹', '仰望', '海豚', '海豹', '秦',
              '宋', '元', '汉', '唐', '驱逐舰', '海洋'],
    '零跑': ['零跑'], '小鹏': ['小鹏'], '小米': ['小米'], '理想': ['理想'],
    '蔚来': ['蔚来', 'ONVO', '乐道', '萤火虫'],
    '上汽': ['上汽', '荣威', '名爵', 'MG', '飞凡', '智己'],
    '广汽': ['广汽', '埃安', 'AION', '传祺', '昊铂', 'Hyper'],
    '长安': ['长安', '深蓝', '阿维塔', '启源', '逸动', 'UNI', '奔奔', '凯程'],
    '特斯拉': ['特斯拉', 'Tesla', 'Model'],
    '华为': ['问界', '智界', '享界', '尊界'],
    '奇瑞': ['奇瑞', '星途', '捷途', 'iCAR', '开瑞', '凯翼', '风云', '瑞虎',
            '艾瑞泽', 'QQ冰淇淋'],
}
_TARGET_ENERGY = {'纯电', '增程', '插混'}
_EXCLUDE_LEVELS = {'皮卡', '微面', '微卡', '轻客'}


def _match_maker(name: str) -> str | None:
    for m, kws in _MAKERS_ALIASES.items():
        for kw in kws:
            if kw in name:
                return m
    return None


def _parse_fetched_at(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def _list_series_from_db() -> list[str]:
    """查 config_snapshots 表全部 series_id。"""
    from sqlalchemy import select

    from src.models.orm import ConfigSnapshot
    from src.storage.db import _engine, init_db, session_scope
    if _engine is None:
        init_db()
    with session_scope() as s:
        return [r[0] for r in s.execute(
            select(ConfigSnapshot.series_id)).fetchall()]



def _fresh_set(series_ids: list[str], max_age_days: int | None) -> set[str]:
    """一次性预读 fetched_at，返回新于阈值的 sid 集合（跳过集）。
    单次查询替代逐系开 session，避免 244 次 DB 往返。"""
    if max_age_days is None:
        return set()
    threshold = datetime.now() - timedelta(days=max_age_days)
    from sqlalchemy import select

    from src.models.orm import ConfigSnapshot
    from src.storage.db import session_scope
    fresh: set[str] = set()
    id_set = set(series_ids)
    with session_scope() as s:
        for sid, fa in s.execute(
                select(ConfigSnapshot.series_id, ConfigSnapshot.fetched_at)).fetchall():
            if sid not in id_set:
                continue
            dt = _parse_fetched_at(fa)
            if dt and dt > threshold:
                fresh.add(sid)
    return fresh


async def _collect_async(series_ids, fetch_func, max_age_days,
                         concurrency, delay, metadata_map):
    fresh = _fresh_set(series_ids, max_age_days)
    sem = asyncio.Semaphore(concurrency)
    done = failed = skipped = 0
    fail_list = []
    t0 = time.time()
    total = len(series_ids)
    dropped_total = 0  # Task 6.1: 跨车系汇总解析失败丢弃数

    async def one(sid):
        nonlocal done, failed, skipped, dropped_total
        if sid in fresh:
            skipped += 1
            return
        async with sem:
            try:
                cfg = await fetch_func(sid)
                cats = cfg.get("categories") if isinstance(cfg, dict) else None
                if not cats:
                    raise ValueError("no categories")
                # Task 6.1: 汇总解析失败丢弃计数（autohome_api.get_full_config 返回）
                dp = cfg.get("dropped_params") if isinstance(cfg, dict) else None
                if isinstance(dp, int) and dp:
                    dropped_total += dp
                data = {
                    "categories": cats,
                    "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                # dashboard-v10 Task 1.1：存 decode_hit_rate 供 selfcheck 查
                dhr = cfg.get("decode_hit_rate") if isinstance(cfg, dict) else None
                if dhr is not None:
                    data["decode_hit_rate"] = dhr
                # API 可能带回 name/level/price_range
                for k_src, k_dst in (("name", "series_name"), ("level", "level"),
                                     ("price_range", "price_range")):
                    v = cfg.get(k_src)
                    if v:
                        data[k_dst] = v
                # docs metadata 兜底
                if metadata_map and sid in metadata_map:
                    data.update(metadata_map[sid])
                from src.storage.db import session_scope
                from src.models.orm import upsert_config_snapshot
                with session_scope() as s:
                    upsert_config_snapshot(s, sid, data)
                done += 1
                if done % 20 == 0:
                    print(f"  进度 done={done} skip={skipped} fail={failed} "
                          f"/ {total} 用时{time.time()-t0:.0f}s", flush=True)
            except Exception as e:
                failed += 1
                fail_list.append((sid, str(e)[:60]))
        if delay:
            await asyncio.sleep(delay)

    await asyncio.gather(*[one(sid) for sid in series_ids])
    if dropped_total:
        print(f"  ⚠ {dropped_total} 个参数因名称解析失败丢弃（需补 baike ID 映射）", flush=True)
    return {"done": done, "skipped": skipped, "failed": failed,
            "total": total, "fails": fail_list, "elapsed": time.time() - t0,
            "dropped_params": dropped_total}



def collect_snapshots(series_ids=None, fetch_func=None, max_age_days=None,
                      concurrency=3, delay=0.0, metadata_map=None) -> dict:
    """通用重采。

    - series_ids: None → 查 config_snapshots 表全部 series_id（244 系）
    - fetch_func: async (sid) -> dict（含 "categories"）；None → 用 autohome_api.get_full_config
    - max_age_days: fetched_at 新于该天数 → 跳过（断点续采）；None → 全采
    - metadata_map: {sid: {maker, energy, level, price_range, series_name}}（docs 路径用）
    返回 {done, skipped, failed, total, fails, elapsed}。
    """
    if series_ids is None:
        series_ids = _list_series_from_db()
    if not series_ids:
        return {"done": 0, "skipped": 0, "failed": 0, "total": 0,
                "fails": [], "elapsed": 0.0}

    if fetch_func is None:
        from src.api.autohome_api import close_autohome_api, get_autohome_api

        async def _real_fetch(sid):
            api = await get_autohome_api()
            return await api.get_full_config(sid)

        fetch_func = _real_fetch
        _close = True
    else:
        _close = False

    try:
        stats = asyncio.run(_collect_async(
            series_ids, fetch_func, max_age_days, concurrency, delay,
            metadata_map))
    finally:
        if _close:
            try:
                asyncio.run(close_autohome_api())
            except Exception:
                pass
    print(f"\nDONE: {stats['done']} 新采 / {stats['skipped']} 跳过 / "
          f"{stats['failed']} 失败 / {stats['total']} 总，"
          f"用时{stats['elapsed']:.0f}s", flush=True)
    if stats["fails"]:
        for sid, err in stats["fails"]:
            print(f"  FAIL {sid}: {err}", flush=True)
    return stats


def _metadata_from_docs(docs_path: str) -> tuple[list[str], dict]:
    """从 docs 扫描 json 构建 (series_ids, metadata_map)。

    沿用 v5 首采口径：纯电/增程/插混 + 在售 + 13 主机厂 + 排除皮卡/微面等。
    metadata_map[sid] = {maker, energy, level, price_range, series_name}。
    """
    with open(docs_path, "r", encoding="utf-8") as f:
        d = json.load(f)
    out_ids, meta = [], {}
    for sid, r in d["series"].items():
        if r.get("energy") not in _TARGET_ENERGY:
            continue
        if r.get("sale_state") != "在售":
            continue
        name = r.get("name", "")
        m = _match_maker(name)
        if not m:
            continue
        lv = r.get("level", "") or ""
        if any(x in lv for x in _EXCLUDE_LEVELS):
            continue
        out_ids.append(sid)
        meta[sid] = {
            "maker": m,
            "energy": r["energy"],
            "level": lv,
            "price_range": r.get("price_range", ""),
            "series_name": name,
        }
    return out_ids, meta


def collect_snapshots_from_docs(docs_path, fetch_func=None, max_age_days=None,
                                concurrency=3, delay=0.0) -> dict:
    """--from-docs 路径：series 列表 + metadata 来自 docs 扫描 json。"""
    series_ids, metadata_map = _metadata_from_docs(docs_path)
    print(f"docs 名单：{len(series_ids)} 系，开始采集", flush=True)
    return collect_snapshots(series_ids=series_ids, fetch_func=fetch_func,
                             max_age_days=max_age_days, concurrency=concurrency,
                             delay=delay, metadata_map=metadata_map)


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    import argparse
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="通用配置快照重采")
    p.add_argument("--from-docs", default=None,
                   help="从 docs 扫描 json 取 series 列表（首次入库/补采用）")
    p.add_argument("--max-age-days", type=int, default=None,
                   help="fetched_at 新于该天数则跳过（断点续采）；不传=全采")
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--delay", type=float, default=0.0,
                   help="每系采集后间隔秒数（限速）")
    p.add_argument("--db", default=None,
                   help="SQLite 库路径（F3，2026-11-02：默认走 DATABASE_URL/开发库）")
    args = p.parse_args(argv)

    # 显式指定库时，必须在 init_db() 之前设置 DATABASE_URL
    if args.db:
        os.environ["DATABASE_URL"] = f"sqlite:///{args.db}"

    from src.storage.db import init_db
    init_db()

    if args.from_docs:
        stats = collect_snapshots_from_docs(
            args.from_docs, max_age_days=args.max_age_days,
            concurrency=args.concurrency, delay=args.delay)
    else:
        stats = collect_snapshots(max_age_days=args.max_age_days,
                                  concurrency=args.concurrency,
                                  delay=args.delay)
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
