"""nevpool T5：存量车系口碑 tag-only 补打标。

目标：owner_reviews 中没有任何 review_tags 行的口碑（按 review_id 差集反查），逐条跑
get_tagger 语义打标，把新标签 INSERT 进 review_tags——**只写 review_tags**，零 UPDATE
零 DELETE，绝不触碰 owner_reviews（self-check Gap5：recollect 是 delete+insert，对存量系
重采会 CASCADE 清掉已有标签，禁入本路径）。

安全设计：
- 对象身份前置核验（红线#7）：目标名单按 series_summaries.series_name **精确匹配**解析
  series_id；唯一命中才认；找不到/多义 → 记入 unresolved 清单跳过（不猜 ID）。
  T1 绑定器（nev_pool.json）对同批的 海狮06 DM-i / 海狮06 EV / 风云T11 CEM 亦判
  manual_review（series_id=null），与名称解析失败互相印证，人工拍板后可用
  --series-ids 显式通道补跑。
- 批前后对账：每系 owner_reviews 行数写前写后必须相等，不等=事故，立即停止全部后续
  车系并以退出码 1 结束（报告标红）。
- 门控：默认 dry-run（只打印逐系缺口与预估，零写入零出网）；PRISM_COLLECT_LIVE=1 才
  真跑；live 要求 data/backups/autohome-pre-nevpool-*.db 备份在位（T0 前置，无备份不跑）。
- 逐系 progress 打印；单系失败记录后继续下一系；单条失败不中断本系。
- 打标输入：优先 best/worst_review_text（列表页短文本），为空回退 best/worst_full_text
  （详情页全文；存量行普遍短文本空而全文在）。两侧皆空=无料可打（纯图片口碑），
  物理跳过并计数——这是 coverage_total 的结构性上限来源。

覆盖口径双报（验收口径与可打标分母口径分开呈现，不混用）：
- coverage_total = distinct 有标签 review_id / 该系 owner_reviews 总行数（验收口径，
  目标 ≥70%；纯图片无文本口碑会压低其上限）
- coverage_text = distinct 有标签 review_id / 有任一文本行数

用法：
  python scripts/backfill_tags_pool.py                    # dry-run（默认 5 个 T5 目标名）
  PRISM_COLLECT_LIVE=1 python scripts/backfill_tags_pool.py --names "海狮05 EV"
  python scripts/backfill_tags_pool.py --series-ids 7982  # 人工拍板通道（跳过名称解析）

退出码：0=全部达标；1=owner_reviews 对账事故；2=存在 unresolved 名称 / 跑批失败 /
有系未达 ≥70%（含结构性不可达，如纯图片口碑——如实报告，不静默放行）。
"""
import asyncio
import io
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# 与 recollect_koubei_with_full.py 同款 .env 加载（tagger 需要 LLM_API_KEY 等环境变量）
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# GBK 控制台编码守卫（与 recollect 同款；已是 utf-8 不重复包裹）
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from sqlalchemy import func, select

from src.models.orm import OwnerReview, ReviewTag, SeriesSummary
from src.nlp.tagger import close_tagger, get_tagger
from src.storage.db import init_db, session_scope

# T5 任务单默认目标名（tasks.md T5 原文名；解析不到的进 unresolved，不猜 ID）
DEFAULT_TARGET_NAMES = ["元UP", "海狮05 EV", "海狮06 DM-i", "海狮06 EV", "风云T11 CEM"]
COVERAGE_TARGET = 0.70
BACKUP_GLOB = "autohome-pre-nevpool-*.db"
EST_SEC_PER_REVIEW = 1.2   # tagger 速率实测参考（T5 任务单给值）
PROGRESS_EVERY = 20
EMPTY_STREAK_ABORT = 12    # 连续空返回熔断阈值（断网静默空跑防线，见 TaggerUnreachable）


# ---------------- 纯函数（单测覆盖面） ----------------

def resolve_names(names: list[str], lookup_fn) -> tuple[dict, dict]:
    """名称 → series_id 精确解析：唯一命中才认；0 命中=not_found，>1=ambiguous。

    lookup_fn(name) -> list[series_id]。返回 (resolved{name: sid}, unresolved{name: info})。
    禁止子串/前缀猜测（红线#6：名称字段禁止人工转写与模糊绑定）。"""
    resolved: dict[str, str] = {}
    unresolved: dict[str, dict] = {}
    for name in names:
        hits = lookup_fn(name)
        if len(hits) == 1:
            resolved[name] = str(hits[0])
        elif not hits:
            unresolved[name] = {"reason": "not_found", "candidates": []}
        else:
            unresolved[name] = {"reason": "ambiguous",
                                "candidates": sorted({str(h) for h in hits})}
    return resolved, unresolved


def untagged_ids(all_review_ids: list[str], tagged_review_ids: list[str]) -> list[str]:
    """差集：owner_reviews 里有、review_tags 里没有的 review_id（保序）。"""
    tagged = set(tagged_review_ids)
    return [rid for rid in all_review_ids if rid not in tagged]


def coverage_ratio(tagged_distinct: int, total: int) -> float:
    """打标覆盖 = distinct 有标签 review_id / 总行数；总行数 0 → 0.0。"""
    if total <= 0:
        return 0.0
    return tagged_distinct / total


def meets_target(ratio: float, target: float = COVERAGE_TARGET) -> bool:
    return ratio >= target


def pick_tag_input(best_short: str | None, worst_short: str | None,
                   best_full: str | None, worst_full: str | None) -> tuple[str, str]:
    """打标输入选择：短文本优先，空则回退详情页全文（逐侧独立回退）。"""
    best = (best_short or "").strip() or (best_full or "").strip()
    worst = (worst_short or "").strip() or (worst_full or "").strip()
    return best, worst


# ---------------- DB 读取 ----------------

def make_name_lookup():
    """series_summaries 精确名索引 lookup_fn（唯一真值源，逐名查询）。"""
    def lookup(name: str) -> list[str]:
        with session_scope() as s:
            rows = s.execute(select(SeriesSummary.series_id)
                             .where(SeriesSummary.series_name == name)).fetchall()
        return [str(r[0]) for r in rows]
    return lookup


def count_owner_reviews(model_id: str) -> int:
    with session_scope() as s:
        return int(s.query(func.count(OwnerReview.review_id))
                   .filter(OwnerReview.model_id == str(model_id)).scalar() or 0)


def count_text_having(model_id: str) -> int:
    """该系有任一文本（短文本或全文任一非空）的行数（coverage_text 分母）。"""
    with session_scope() as s:
        return int(s.query(func.count(OwnerReview.review_id))
                   .filter(OwnerReview.model_id == str(model_id))
                   .filter((func.coalesce(OwnerReview.best_review_text, "") != "")
                           | (func.coalesce(OwnerReview.worst_review_text, "") != "")
                           | (func.coalesce(OwnerReview.best_full_text, "") != "")
                           | (func.coalesce(OwnerReview.worst_full_text, "") != ""))
                   .scalar() or 0)


def tagged_distinct_count(model_id: str) -> int:
    with session_scope() as s:
        return int(s.query(func.count(func.distinct(ReviewTag.review_id)))
                   .filter(ReviewTag.model_id == str(model_id)).scalar() or 0)


def load_untagged_rows(model_id: str) -> list[dict]:
    """该系无任何标签的口碑行（owner_reviews 反查 review_tags 差集，anti-join）。

    每行含打标所需全部字段；按 review_id 排序保证可复算。"""
    with session_scope() as s:
        rows = s.execute(
            select(OwnerReview.review_id, OwnerReview.owner_id,
                   OwnerReview.model_full_name, OwnerReview.model_id,
                   OwnerReview.best_review_text, OwnerReview.worst_review_text,
                   OwnerReview.best_full_text, OwnerReview.worst_full_text)
            .outerjoin(ReviewTag, ReviewTag.review_id == OwnerReview.review_id)
            .where(OwnerReview.model_id == str(model_id),
                   ReviewTag.review_id.is_(None))
            .order_by(OwnerReview.review_id)).fetchall()
    return [dict(r._mapping) for r in rows]


def split_taggable(rows: list[dict]) -> tuple[list[tuple[dict, str, str]], int]:
    """按打标输入可得性切分：可打 (row, best, worst) / 无文本计数。"""
    taggable: list[tuple[dict, str, str]] = []
    no_text = 0
    for row in rows:
        best, worst = pick_tag_input(row["best_review_text"], row["worst_review_text"],
                                     row["best_full_text"], row["worst_full_text"])
        if best or worst:
            taggable.append((row, best, worst))
        else:
            no_text += 1
    return taggable, no_text


# ---------------- 写入（仅 review_tags） ----------------

def insert_tags(row: dict, tags: list[dict], model_id: str) -> int:
    """单条口碑的标签写入 review_tags；返回实际插入行数。

    防撞唯一索引 (review_id, tag_name, sentiment)：批内去重 + 库内已存在跳过
    （幂等，重放安全）。非法 sentiment/空名过滤（与 tagger 出口纪律一致）。"""
    rid = row["review_id"]
    with session_scope() as s:
        existing = set(s.execute(select(ReviewTag.tag_name, ReviewTag.sentiment)
                                 .where(ReviewTag.review_id == rid)).all())
        added = 0
        seen: set[tuple[str, str]] = set()
        for tag in tags:
            name = (tag.get("tag_name") or "").strip()
            senti = tag.get("sentiment")
            if not name or senti not in ("pro", "con"):
                continue
            key = (name, senti)
            if key in seen or key in existing:
                continue
            seen.add(key)
            try:
                confidence = float(tag.get("confidence", 0.8))
            except (TypeError, ValueError):
                confidence = 0.8
            s.add(ReviewTag(
                review_id=rid,
                owner_id=row.get("owner_id") or "",
                model_full_name=row.get("model_full_name") or "",
                model_id=str(model_id),
                tag_name=name,
                sentiment=senti,
                source_text=(tag.get("source_text") or "")[:100],
                confidence=max(0.0, min(1.0, confidence)),
                tag_category=(tag.get("tag_category") or "").strip(),
            ))
            added += 1
        s.commit()
    return added


# ---------------- 批跑 ----------------

class TaggerUnreachable(RuntimeError):
    """tagger 连续多条返回空（疑似 API 不可达/异常）触发的熔断异常。

    extract_tags 对网络错误吞错返回 []（tagger 自身语义），若不熔断，断网时
    整批会静默空跑（0 插入但 0 失败）。合法"封闭标签表无匹配"连续 12 条的概率
    极低（首次实跑 403 条仅 5 条零产出），熔断阈值取 12。"""

async def backfill_series(model_id: str, tagger, label: str = "") -> dict:
    """单车系 tag-only 补打标。绝不写 owner_reviews；返回统计 dict。"""
    model_id = str(model_id)
    pre_count = count_owner_reviews(model_id)
    rows = load_untagged_rows(model_id)
    taggable, no_text = split_taggable(rows)
    print(f"  [{label}] {model_id}: 共 {pre_count} 条，未打标 {len(rows)} 条"
          f"（可打 {len(taggable)}，无文本 {no_text}）", flush=True)

    inserted = newly_tagged = failed = 0
    empty_streak = 0
    t0 = time.perf_counter()
    for i, (row, best, worst) in enumerate(taggable, 1):
        try:
            tags = await tagger.extract_tags(best, worst)
        except Exception as e:  # 单条失败不中断本系
            failed += 1
            print(f"    单条失败 {row['review_id'][:24]}: {e}", flush=True)
            continue
        if not tags:
            empty_streak += 1
            if empty_streak >= EMPTY_STREAK_ABORT:
                raise TaggerUnreachable(
                    f"tagger 连续 {empty_streak} 条返回空，疑似 API 不可达/异常，本系中止"
                    f"（已插 {inserted} 标签、新覆盖 {newly_tagged} 条，差集断点可续跑）")
            continue
        empty_streak = 0
        try:
            n = insert_tags(row, tags, model_id)
            if n:
                inserted += n
                newly_tagged += 1
        except Exception as e:  # 写库失败不中断本系
            failed += 1
            print(f"    单条失败 {row['review_id'][:24]}: {e}", flush=True)
        if i % PROGRESS_EVERY == 0 or i == len(taggable):
            rate = i / max(time.perf_counter() - t0, 1e-6)
            print(f"    [{label}] 进度 {i}/{len(taggable)}，新标签 {inserted}，"
                  f"失败 {failed}，{rate:.1f} 条/s", flush=True)

    post_count = count_owner_reviews(model_id)
    return {"model_id": model_id, "pre_count": pre_count, "post_count": post_count,
            "untagged": len(rows), "taggable": len(taggable), "no_text": no_text,
            "inserted": inserted, "newly_tagged": newly_tagged, "failed": failed,
            "invariant_ok": pre_count == post_count,
            "elapsed_s": round(time.perf_counter() - t0, 1)}


def find_backup(backups_dir: str | Path | None = None) -> Path | None:
    """T0 备份探测：data/backups/ 下最新一份 autohome-pre-nevpool-*.db；无 → None。"""
    d = Path(backups_dir) if backups_dir else (ROOT / "data" / "backups")
    if not d.is_dir():
        return None
    hits = sorted(d.glob(BACKUP_GLOB))
    return hits[-1] if hits else None


async def run_backfill(names: list[str] | None = None,
                       series_ids: list[str] | None = None,
                       live: bool | None = None) -> dict:
    """T5 补账主流程：解析 → 逐系跑 → 对账 → 覆盖率。默认 dry-run。"""
    init_db()
    if live is None:
        live = os.environ.get("PRISM_COLLECT_LIVE", "") == "1"
    if names is None:
        names = list(DEFAULT_TARGET_NAMES)

    unresolved: dict[str, dict] = {}
    resolved: dict[str, str] = {}
    if series_ids:
        # 人工拍板通道：显式 series_id 跳过名称解析（如 unresolved 名称事后拍板补跑）
        resolved = {f"显式{sid}": str(sid) for sid in series_ids}
    else:
        resolved, unresolved = resolve_names(names, make_name_lookup())
        for name, info in unresolved.items():
            cands = info["candidates"]
            print(f"✋ 未解析 {name}: {info['reason']}"
                  + (f"，候选={cands}（歧义需人工拍板）" if cands
                     else "（series_summaries 无精确同名，不猜 ID）"), flush=True)

    # 去重保序（理论上两个名可解析到同一 sid）
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, sid in resolved.items():
        if sid not in seen:
            seen.add(sid)
            targets.append((sid, label))

    if not targets:
        print("无可跑目标（全部未解析或名单为空）。", flush=True)
        return {"live": live, "targets": [], "unresolved": unresolved,
                "stats": [], "failures": [], "incident": None,
                "below_target": [], "exit_code": 2 if unresolved else 0}

    if not live:
        # ---- dry-run（默认）：零写入零出网，打印逐系缺口与预估 ----
        print(f"[DRY-RUN] 可跑 {len(targets)} 系（真跑请 PRISM_COLLECT_LIVE=1）", flush=True)
        below_dry: list[tuple[str, float]] = []
        for sid, label in targets:
            total = count_owner_reviews(sid)
            tagged = tagged_distinct_count(sid)
            taggable, no_text = split_taggable(load_untagged_rows(sid))
            cur_cov = coverage_ratio(tagged, total)
            ceiling = coverage_ratio(tagged + len(taggable), total)
            est_min = len(taggable) * EST_SEC_PER_REVIEW / 60
            flag = "" if meets_target(ceiling) else "  ⚠ 结构性低于70%（含无文本行，tag-only不可达）"
            print(f"  {label} {sid}: 总 {total}，已打 {tagged}（{cur_cov * 100:.1f}%），"
                  f"未打 {len(taggable) + no_text}（可打 {len(taggable)} / 无文本 {no_text}），"
                  f"预估 {est_min:.0f} 分钟，补后上限 {ceiling * 100:.1f}%{flag}", flush=True)
            if not meets_target(ceiling):
                below_dry.append((sid, ceiling))
        print(f"[DRY-RUN] 预估合计 {sum(len(split_taggable(load_untagged_rows(s))[0]) for s, _ in targets)} 条"
              f"打标调用；未解析 {len(unresolved)} 名；"
              f"上限<70% 系 {len(below_dry)} 个", flush=True)
        exit_code = 2 if (unresolved or below_dry) else 0
        return {"live": False, "targets": targets, "unresolved": unresolved,
                "stats": [], "failures": [], "incident": None,
                "below_target": below_dry, "exit_code": exit_code}

    # ---- live：无备份不跑 ----
    backup = find_backup()
    if backup is None:
        print(f"✋ 守卫拦截：data/backups/ 下无 {BACKUP_GLOB} 备份（T0 前置），拒跑。", flush=True)
        raise SystemExit(2)
    print(f"[LIVE] 真跑 {len(targets)} 系，备份 {backup.name}"
          f"（只 INSERT review_tags，不碰 owner_reviews）", flush=True)

    stats: list[dict] = []
    failures: list[tuple[str, str]] = []
    incident: dict | None = None
    tagger = await get_tagger()
    try:
        for i, (sid, label) in enumerate(targets, 1):
            try:
                st = await backfill_series(sid, tagger, label=f"{i}/{len(targets)} {label}")
                st["tagged_distinct"] = tagged_distinct_count(sid)
                st["coverage_total"] = coverage_ratio(st["tagged_distinct"], st["post_count"])
                st["coverage_text"] = coverage_ratio(st["tagged_distinct"],
                                                     count_text_having(sid))
                stats.append(st)
                print(f"  [{i}/{len(targets)}] {label} {sid}: 补 {st['inserted']} 标签 / "
                      f"新覆盖 {st['newly_tagged']} 条，coverage_total="
                      f"{st['coverage_total'] * 100:.1f}%，coverage_text="
                      f"{st['coverage_text'] * 100:.1f}%，owner_reviews "
                      f"{st['pre_count']}→{st['post_count']}", flush=True)
                if not st["invariant_ok"]:
                    incident = st
                    print(f"🚨 事故：{label} {sid} owner_reviews 行数变化 "
                          f"{st['pre_count']}→{st['post_count']}，立即停止全部后续车系。", flush=True)
                    break
            except Exception as e:  # 单系失败记录继续下一系
                failures.append((sid, str(e)))
                print(f"  [{i}/{len(targets)}] {label} {sid}: 失败 {e}", flush=True)
    finally:
        await close_tagger()

    below = [(st["model_id"], st["coverage_total"]) for st in stats
             if st.get("coverage_total") is not None and not meets_target(st["coverage_total"])]
    if incident:
        exit_code = 1
    elif unresolved or failures or below:
        exit_code = 2
    else:
        exit_code = 0
    print(f"T5 补账结束：live 处理 {len(stats)} 系，失败 {len(failures)}，"
          f"事故 {1 if incident else 0}，未达 70% 系 {len(below)}，exit={exit_code}", flush=True)
    return {"live": True, "targets": targets, "unresolved": unresolved,
            "stats": stats, "failures": failures, "incident": incident,
            "below_target": below, "exit_code": exit_code}


def _parse_args(argv: list[str]) -> dict:
    """支持 --flag value 与 --flag=value 两种形式。"""
    args: dict = {"names": None, "series_ids": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if "=" in a:
            key, val = a.split("=", 1)
        else:
            key = a
            val = None
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                val = argv[i + 1]
                i += 1
        if key == "--names" and val:
            args["names"] = [x.strip() for x in val.split(",") if x.strip()]
        elif key == "--series-ids" and val:
            args["series_ids"] = [x.strip() for x in val.split(",") if x.strip()]
        i += 1
    return args


if __name__ == "__main__":
    _args = _parse_args(sys.argv[1:])
    _stats = asyncio.run(run_backfill(names=_args["names"],
                                      series_ids=_args["series_ids"]))
    sys.exit(_stats["exit_code"])
