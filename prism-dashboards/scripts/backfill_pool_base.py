"""T2 底座批：新能源车池已绑定车系的 壳(series_summaries) + 配置(config_snapshots) 缺口补齐。

名单真值：data/nev_pool.json——只取 series_id 非空 且 binding != 'manual_review' 的项
（T1 产物，当前 269 项 / 224 个唯一 series_id，共壳车系同一 id 对多个 sales 名）。

行为：
- 只补缺：不在表内的 id 才采；已有行不主动刷新（写时已存在则按非 None 字段合并，幂等）。
- 补壳：逐 id 调 api.get_series_summary → upsert SeriesSummary。列映射按 ORM；
  API 没给的列留 NULL，绝不编造；min/max_price 为 0/缺 → NULL（0 元不是真实价）。
- 补配置：collect_snapshots(series_ids=缺配置名单, metadata_map, max_age_days=None)。
  metadata_map[sid] = {maker, energy, level}（键名按 upsert_config_snapshot 实际列；
  maker=nev_pool.manufacturer 原文（self-check Gap6 拍板：sales_trim 直取优于别名猜测）；
  energy 归一到表内既有词表 纯电/插混/增程；level=CAM 车级字母原样落）。
- 门控：默认 dry-run（打印两份名单+逐项计划+总预估）；env PRISM_COLLECT_LIVE=1 才真跑。
- 写冲突防护：engine 挂 PRAGMA busy_timeout=30000（≥30s）；遇 database locked 等 60s
  重试，最多 10 次（打标批并行写 review_tags 时的共存约束）。
- 逐 id progress 打印；失败记清单继续跑，不中断。
- 只写 series_summaries / config_snapshots 两表；不碰 owner_reviews / review_tags。

用法：
    python scripts/backfill_pool_base.py                 # dry-run
    PRISM_COLLECT_LIVE=1 python scripts/backfill_pool_base.py   # live
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_POOL = ROOT / "data" / "nev_pool.json"
DEFAULT_DB = ROOT / "data" / "autohome.db"

# nev_pool.energy_type（sales_trim 词表）→ config_snapshots.energy 既有词表（142 纯电/76 插混/30 增程）
ENERGY_NORM = {"纯电动": "纯电", "插电式混合": "插混", "增程式混合": "增程"}

SHELL_RETRY_WAIT_S = 60     # 遇 database locked 的等待
MAX_LOCKED_RETRY = 10
BUSY_TIMEOUT_MS = 30000     # ≥30s：与打标批（写 review_tags）共存


# ---------- 名单与缺口 ----------

def load_bound_items(pool_path: Path | str = DEFAULT_POOL) -> list[dict]:
    """nev_pool.json → 已绑定项（series_id 非空 且 binding != 'manual_review'），保持文件序。"""
    with open(pool_path, "r", encoding="utf-8") as f:
        pool = json.load(f)
    return [it for it in pool.get("series", [])
            if it.get("series_id") and it.get("binding") != "manual_review"]


def load_db_ids(db_path: Path | str = DEFAULT_DB) -> tuple[set[str], set[str]]:
    """只读连接取两表现有 series_id 集合（dry-run 也不产生写）。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        shell = {str(r[0]) for r in conn.execute("SELECT series_id FROM series_summaries")}
        cfg = {str(r[0]) for r in conn.execute("SELECT series_id FROM config_snapshots")}
    finally:
        conn.close()
    return shell, cfg


def compute_gaps(bound_items: list[dict], shell_ids: set[str],
                 cfg_ids: set[str]) -> dict:
    """缺口计算（只补缺，不刷新已有）。唯一 sid 保序去重（共壳多 sales 名 → 一项）。"""
    order: list[str] = []
    names: dict[str, list[str]] = {}
    for it in bound_items:
        sid = str(it["series_id"])
        if sid not in names:
            order.append(sid)
            names[sid] = []
        names[sid].append(it.get("sales_name") or sid)
    missing_shell = [sid for sid in order if sid not in shell_ids]
    missing_cfg = [sid for sid in order if sid not in cfg_ids]
    return {"order": order, "names": names,
            "missing_shell": missing_shell, "missing_config": missing_cfg,
            "bound_items": len(bound_items), "unique_ids": len(order)}


def build_metadata_map(bound_items: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    """bound 项 → metadata_map（供 collect_snapshots 的 docs-metadata 兜底通道）。

    - 键名对齐 upsert_config_snapshot 实际字段：maker/energy/level（不传 series_name：
      壳名以之家 API 返回为准，避免 CAM sales 名转写覆盖源站名——红线#6）。
    - energy 归一到表内既有词表；未知值原样落（不编造）。
    - 同一 sid 多个 sales 名（共壳）metadata 不一致 → 首见项落库，冲突如实进披露清单。
    """
    meta: dict[str, dict] = {}
    conflicts: list[dict] = []
    for it in bound_items:
        sid = str(it["series_id"])
        raw_energy = it.get("energy_type")
        energy = ENERGY_NORM.get(raw_energy, raw_energy)
        m = {"maker": it.get("manufacturer"), "energy": energy, "level": it.get("level")}
        if sid not in meta:
            meta[sid] = m
            continue
        diff = {k: {"kept": meta[sid][k], "dropped": v}
                for k, v in m.items() if v != meta[sid].get(k)}
        if diff:
            conflicts.append({"series_id": sid, "sales_name": it.get("sales_name"),
                              "diff": diff})
    return meta, conflicts


# ---------- 补壳：API → SeriesSummary 列映射 ----------

def map_summary_to_columns(summary: dict) -> dict | None:
    """get_series_summary 返回 → SeriesSummary 列字典。error 形态返回 None。

    纪律：API 没给的列 → None（绝不编造）；min/max_price 0/缺 → None（0 不是真实价）。
    """
    if not isinstance(summary, dict) or "error" in summary:
        return None

    def _price(v):
        if v in (None, "", 0, 0.0):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "series_id": str(summary.get("series_id", "")) or None,
        "series_name": summary.get("series_name") or None,
        "brand_name": summary.get("brand_name") or None,
        "brand_id": summary.get("brand_id") or None,
        "level_name": summary.get("level_name") or None,
        "level_id": summary.get("level_id") or None,
        "level_rank": summary.get("level_rank"),
        "level_series_count": summary.get("level_series_count"),
        "price_range": summary.get("price_range") or None,
        "min_price": _price(summary.get("min_price")),
        "max_price": _price(summary.get("max_price")),
        "average_score": summary.get("average_score"),
        "dimension_scores": summary.get("dimension_scores"),
        "review_count": summary.get("review_count"),
        "onsell_review_count": summary.get("onsell_review_count"),
        "pph": summary.get("pph"),
        "powertype": summary.get("powertype"),
        "cmp_scores": summary.get("cmp_scores"),
        "cmp_pph": summary.get("cmp_pph"),
        "consumption": summary.get("consumption") or None,
        "consumption_battery": summary.get("consumption_battery") or None,
        "spec_groups": summary.get("spec_groups"),
    }


def upsert_series_summary(session, cols: dict) -> str:
    """按列字典 upsert SeriesSummary。已存在 → 更新非 None 字段（不擦旧值）；新 → 插入。
    返回 "inserted" | "updated"。"""
    from src.models.orm import SeriesSummary
    sid = cols["series_id"]
    row = session.get(SeriesSummary, sid)
    if row is None:
        row = SeriesSummary(series_id=sid)
        for k, v in cols.items():
            if k != "series_id" and v is not None:
                setattr(row, k, v)
        session.add(row)
        return "inserted"
    for k, v in cols.items():
        if k != "series_id" and v is not None:
            setattr(row, k, v)
    return "updated"


def is_locked_error(e: Exception) -> bool:
    s = str(e).lower()
    return "locked" in s or "busy" in s


def with_locked_retry(fn, wait_s: float = SHELL_RETRY_WAIT_S,
                      max_retry: int = MAX_LOCKED_RETRY,
                      sleep=time.sleep):
    """执行 fn()；遇 database locked 等 wait_s 重试，最多 max_retry 次。"""
    for attempt in range(1, max_retry + 1):
        try:
            return fn()
        except Exception as e:
            if is_locked_error(e) and attempt < max_retry:
                print(f"  ⚠ database locked，{wait_s:.0f}s 后重试"
                      f"（第 {attempt}/{max_retry} 次）: {str(e)[:60]}", flush=True)
                sleep(wait_s)
                continue
            raise
    raise RuntimeError("unreachable")


async def backfill_shells(missing_ids: list[str], names: dict[str, list[str]],
                          delay: float = 1.0,
                          wait_s: float = SHELL_RETRY_WAIT_S,
                          max_retry: int = MAX_LOCKED_RETRY) -> dict:
    """逐 id 调 get_series_summary → upsert。请求间隔 ≥delay 秒；失败记清单继续跑。"""
    from src.api.autohome_api import close_autohome_api, get_autohome_api
    from src.storage.db import init_db, session_scope

    init_db()
    setup_busy_timeout()
    api = await get_autohome_api()
    inserted = updated = failed = 0
    fails: list[tuple[str, str]] = []
    t0 = time.time()
    total = len(missing_ids)
    try:
        for i, sid in enumerate(missing_ids, 1):
            label = " / ".join(names.get(sid, [sid]))
            try:
                summary = await api.get_series_summary(sid)
                cols = map_summary_to_columns(summary)
                if cols is None:
                    raise ValueError(f"API 返回 error/非 dict: {str(summary)[:60]}")
                cols["series_id"] = sid  # 以名单 id 为准（API 回显 id 应一致）

                def _write(cols=cols):
                    with session_scope() as s:
                        return upsert_series_summary(s, cols)

                res = with_locked_retry(_write, wait_s=wait_s, max_retry=max_retry)
                if res == "inserted":
                    inserted += 1
                else:
                    updated += 1
                print(f"  [壳 {i}/{total}] {sid} {label} → {res}"
                      f" name={cols.get('series_name')}", flush=True)
            except Exception as e:
                failed += 1
                fails.append((sid, str(e)[:80]))
                print(f"  [壳 {i}/{total}] {sid} {label} → FAIL {str(e)[:60]}",
                      flush=True)
            if delay:
                await asyncio.sleep(delay)
    finally:
        try:
            await close_autohome_api()
        except Exception:
            pass
    return {"inserted": inserted, "updated": updated, "failed": failed,
            "total": total, "fails": fails, "elapsed": time.time() - t0}


# ---------- 补配置：collect_snapshots + locked 重试 ----------

def backfill_configs(missing_ids: list[str], metadata_map: dict,
                     delay: float = 1.0, concurrency: int = 3,
                     wait_s: float = SHELL_RETRY_WAIT_S,
                     max_retry: int = MAX_LOCKED_RETRY) -> dict:
    """collect_snapshots（max_age_days=None 全采，名单=缺配置项）。
    失败里 locked 类等 wait_s 后只对失败子集重试；其余失败直接进清单。"""
    from collect_config_snapshots import collect_snapshots

    remaining = list(missing_ids)
    done = 0
    fails: list[tuple[str, str]] = []
    t0 = time.time()
    attempt = 0
    while remaining:
        attempt += 1
        stats = collect_snapshots(series_ids=remaining, metadata_map=metadata_map,
                                  max_age_days=None, concurrency=concurrency,
                                  delay=delay)
        done += stats["done"]
        locked = [(sid, err) for sid, err in stats["fails"] if is_locked_error(RuntimeError(err))]
        other = [(sid, err) for sid, err in stats["fails"] if not is_locked_error(RuntimeError(err))]
        fails.extend(other)
        if locked and attempt < max_retry:
            print(f"  ⚠ 配置批 {len(locked)} 系遇 database locked，{wait_s:.0f}s 后"
                  f"只对失败子集重试（第 {attempt}/{max_retry} 轮）", flush=True)
            time.sleep(wait_s)
            remaining = [sid for sid, _ in locked]
            continue
        fails.extend(locked)
        remaining = []
    return {"done": done, "failed": len(fails), "total": len(missing_ids),
            "fails": fails, "elapsed": time.time() - t0, "attempts": attempt}


# ---------- 写连接防护 ----------

def setup_busy_timeout(ms: int = BUSY_TIMEOUT_MS) -> None:
    """给全局 engine 的所有新连接挂 PRAGMA busy_timeout（≥30s）。
    不改 db.py：以事件监听方式挂载，dispose 连接池使已建连接重建后生效。"""
    from sqlalchemy import event
    from src.storage.db import _engine
    if _engine is None:
        return

    def _set_busy(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute(f"PRAGMA busy_timeout={ms}")
        cur.close()

    event.listen(_engine, "connect", _set_busy)
    _engine.dispose()


def table_counts(db_path: Path | str = DEFAULT_DB) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("series_summaries", "config_snapshots",
                          "owner_reviews", "review_tags")}
    finally:
        conn.close()


# ---------- main ----------

def _print_plan(gaps: dict, metadata_map: dict) -> None:
    names = gaps["names"]
    print(f"\n== 逐项计划（缺壳 {len(gaps['missing_shell'])} 项）==")
    for sid in gaps["missing_shell"]:
        print(f"  PLAN-SHELL {sid} {' / '.join(names[sid])}: "
              f"GET get_series_summary → INSERT series_summaries")
    print(f"\n== 逐项计划（缺配置 {len(gaps['missing_config'])} 项）==")
    for sid in gaps["missing_config"]:
        m = metadata_map.get(sid, {})
        print(f"  PLAN-CFG {sid} {' / '.join(names[sid])}: "
              f"GET get_full_config → UPSERT config_snapshots "
              f"(maker={m.get('maker')}, energy={m.get('energy')}, level={m.get('level')})")


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    import argparse
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="T2 底座批：壳+配置缺口补齐（默认 dry-run）")
    p.add_argument("--pool", default=str(DEFAULT_POOL))
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--delay", type=float, default=1.0, help="每请求间隔秒数（限速）")
    args = p.parse_args(argv)

    live = os.environ.get("PRISM_COLLECT_LIVE") == "1"
    mode = "LIVE" if live else "DRY-RUN"
    print(f"=== T2 底座批 backfill_pool_base · mode={mode} ===")

    items = load_bound_items(args.pool)
    shell_ids, cfg_ids = load_db_ids(args.db)
    gaps = compute_gaps(items, shell_ids, cfg_ids)
    metadata_map, conflicts = build_metadata_map(items)

    print(f"名单：绑定 {gaps['bound_items']} 项 / 唯一 series_id {gaps['unique_ids']} 个"
          f"（共壳重复 {gaps['bound_items'] - gaps['unique_ids']} 项）")
    print(f"\n== 缺壳名单（{len(gaps['missing_shell'])} 系，将 INSERT series_summaries）==")
    for sid in gaps["missing_shell"]:
        print(f"  {sid}  {' / '.join(gaps['names'][sid])}")
    print(f"\n== 缺配置名单（{len(gaps['missing_config'])} 系，将 UPSERT config_snapshots）==")
    for sid in gaps["missing_config"]:
        print(f"  {sid}  {' / '.join(gaps['names'][sid])}")
    if conflicts:
        print(f"\n== 共壳 metadata 冲突披露（{len(conflicts)} 条，首见项落库）==")
        for c in conflicts:
            print(f"  {c['series_id']} {c['sales_name']}: {json.dumps(c['diff'], ensure_ascii=False)}")

    est_min = (len(gaps["missing_shell"]) + len(gaps["missing_config"])) * (args.delay + 1.5) / 60
    print(f"\n== 预估 ==：请求 ≈{len(gaps['missing_shell'])}（壳）+ "
          f"≈{len(gaps['missing_config'])}（配置，每系 1-3 请求）次，"
          f"delay={args.delay}s 限速下 ≈{est_min:.0f}-{est_min * 2:.0f} 分钟")

    if not live:
        _print_plan(gaps, metadata_map)
        print("\nDRY-RUN 结束（未写库）。真跑：PRISM_COLLECT_LIVE=1 python scripts/backfill_pool_base.py")
        return 0

    from src.storage.db import init_db
    init_db()
    setup_busy_timeout()

    before = table_counts(args.db)
    print(f"\n== 跑前四表行数 == {json.dumps(before, ensure_ascii=False)}")

    print(f"\n== 补壳开始（{len(gaps['missing_shell'])} 系，间隔 {args.delay}s）==")
    stats_shell = asyncio.run(backfill_shells(
        gaps["missing_shell"], gaps["names"], delay=args.delay))
    print(f"补壳 DONE: insert={stats_shell['inserted']} update={stats_shell['updated']} "
          f"fail={stats_shell['failed']} / {stats_shell['total']}，"
          f"用时 {stats_shell['elapsed']:.0f}s")
    for sid, err in stats_shell["fails"]:
        print(f"  SHELL-FAIL {sid}: {err}")

    print(f"\n== 补配置开始（{len(gaps['missing_config'])} 系，delay={args.delay}，"
          f"concurrency=3）==")
    stats_cfg = backfill_configs(gaps["missing_config"], metadata_map,
                                 delay=args.delay)
    print(f"补配置 DONE: {stats_cfg['done']} 新采 / {stats_cfg['failed']} 失败 / "
          f"{stats_cfg['total']} 总，{stats_cfg['attempts']} 轮，"
          f"用时 {stats_cfg['elapsed']:.0f}s")
    for sid, err in stats_cfg["fails"]:
        print(f"  CFG-FAIL {sid}: {err}")

    after = table_counts(args.db)
    print(f"\n== 跑后四表行数 == {json.dumps(after, ensure_ascii=False)}")
    print(f"== 对账 == series_summaries {before['series_summaries']}→{after['series_summaries']}"
          f"（Δ={after['series_summaries'] - before['series_summaries']}），"
          f"config_snapshots {before['config_snapshots']}→{after['config_snapshots']}"
          f"（Δ={after['config_snapshots'] - before['config_snapshots']}），"
          f"owner_reviews Δ={after['owner_reviews'] - before['owner_reviews']}"
          f"（应为 0），review_tags Δ={after['review_tags'] - before['review_tags']}"
          f"（本脚本应为 0；并行打标批写入除外）")

    print(f"\n== 失败清单（{len(stats_shell['fails'])} 壳 + {len(stats_cfg['fails'])} 配置）==")
    if not stats_shell["fails"] and not stats_cfg["fails"]:
        print("  （无）")
    return 0 if not stats_shell["fails"] and not stats_cfg["fails"] else 1


if __name__ == "__main__":
    sys.exit(main())
