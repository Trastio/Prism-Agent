"""dashboards-tri-polish B方案：重新采集口碑 + 顺便抓详情页完整原文。

遍历车系调口碑 API → 每条用 showId 抓详情页 → 一步完成重新采集 + 回填
best_full_text/worst_full_text。review_id 改用 k_{showId}（长字符串），详情页
view_{showId}.html 才是正确 URL（旧 k_{Koubeigid} 短数字 404 是 backfill 失败根因）。

每个车系采用 delete+insert：先删该车系旧 owner_reviews（CASCADE 级联删 review_tags），
再插入新数据，避免新旧 review_id 共存导致口碑数翻倍。

新能源车池采集（nevpool T3）新增能力——翻页/详情页解析/打标逻辑一律未动，只加：
- 单车系 cap：--max-reviews N（条数），按页粒度向上取整（20 条/页，300=15 页）；
  实采条数可能略超 cap（最多一页）。不传=不封顶（向后兼容）。
- 名单入参：--pool-file 读 data/nev_pool.json 取 tier=deep 的 series_id 列表；
  文件缺失且未显式指定 --series-ids 时回退 legacy 名单（config_snapshots 全量）。
- 启动守卫（fail-closed）：目标车系与存量分析池（owner_reviews 按 model_id 计数
  ≥100）求交集，非空立即拒跑并列出冲突车系——delete+insert 会删它们的数据。
- 门控：默认 dry-run（只打印将采名单与逐系预估请求量=页数+条数，零写入零出网）；
  env PRISM_COLLECT_LIVE=1 才真采。live 模式还要求 data/backups/ 下存在
  autohome-pre-nevpool-*.db 备份（无备份不跑）。
- progress 断点续跑：逐车系完成态追加写 data/recollect_deep_progress.jsonl
  （--progress-file 可改）；重跑自动跳过 status=done/empty 的车系。

用法：
  .venv/Scripts/python.exe scripts/recollect_koubei_with_full.py [--series-ids=id1,id2] [--limit-series N]
    [--max-reviews 300] [--pool-file data/nev_pool.json] [--progress-file path.jsonl]
    [--mode full|incremental] [--budget-reviews N]
  --series-ids：指定车系（逗号分隔）
  --limit-series：只跑前 N 个车系（取自 config_snapshots，legacy 名单路径）
  --max-reviews：单车系条数 cap（页粒度取整）；不传=不封顶
  --pool-file：名单文件（tier=deep）；缺省 data/nev_pool.json
  --progress-file：断点续跑文件；缺省 data/recollect_deep_progress.jsonl（incremental 缺省 data/weekly_progress.jsonl）
  --mode：full=现役 delete+insert 整系重采（语义零改动）；incremental=周更增量（只插新绝不删）
  --budget-reviews：incremental 全池新入库条数总帽；触顶后未开始车系标 budget_capped 早退（正常终态）

口碑周更增量采集 change（2026-11-01 拍板全池周更）——incremental 模式：
- 名单缺省 = SELECT DISTINCT model_id FROM owner_reviews（库内有口碑全集 ≈96 系）
- 水位停止：从第 1 页翻起，某页 items 的 review_id 全部已知 → 该系停止
  （连续 2 页全已知才停——加固拍板 2026-11-01，防翻页乱序滑深漏采；乱序页继续翻）
- insert-skip：已知 review_id 在列表阶段即跳过（不抓详情页不打标不插入）
- 零删除断言：每系入库前记录行数，入库后 after==before+inserted，不满足 fail-closed
- 不触发 guard_conflicts ≥100 拦截（那守卫防的是 delete 破坏；incremental 无 delete）
- 备份职责在入口层 koubei_weekly_update.py（live 前自动 sqlite backup API），本脚本不再查 NEV 备份
"""
import asyncio
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# 与 main.py / backfill_full_reviews.py 同款 .env 加载：脚本独立运行时也需要环境变量
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# 编码守卫：GBK 控制台（cp936）下中文会 UnicodeEncodeError，才需要 utf-8 包装；
# 已是 utf-8（含 pytest 捕获）则不再重复包裹——重复包裹会在 GC 时关闭底层缓冲。
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import httpx
from sqlalchemy import text

from src.storage.db import init_db, session_scope
from src.models.orm import OwnerReview, ReviewTag
from src.api.autohome_api import AutohomeAPI
from src.api.dashboard_data import list_config_snapshots
from src.nlp.tagger import get_tagger, close_tagger

import logging
logger = logging.getLogger(__name__)

DETAIL_URL = "https://k.autohome.com.cn/detail/view_{kid}.html"
# 详情页 SSR：每条口碑维度用 <p class="kb-item-msg">…</p>，前两个 = 最满意/最不满意
MSG_RE = re.compile(r'<p class="kb-item-msg">([\s\S]*?)</p>')

# ---- nevpool T3 新增常量 ----
PAGE_SIZE = 20                                   # 口碑列表页大小（与 fetch_koubei_page 调用一致）
EXISTING_POOL_THRESHOLD = 100                    # 存量分析池门槛：owner_reviews 按 model_id 计数 ≥100
DEFAULT_POOL_PATH = ROOT / "data" / "nev_pool.json"          # T1 生成件（可能尚不存在）
DEFAULT_PROGRESS_PATH = ROOT / "data" / "recollect_deep_progress.jsonl"
DEFAULT_WEEKLY_PROGRESS_PATH = ROOT / "data" / "weekly_progress.jsonl"  # 周更增量专用
BACKUP_GLOB = "autohome-pre-nevpool-*.db"        # T0 备份命名（无备份不跑）


def _clean(s: str) -> str:
    """去 HTML 标签 + 规范空白。"""
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _extract_full_texts(html: str) -> tuple[str | None, str | None]:
    """从详情页 HTML 提取最满意/最不满意完整原文（<p class="kb-item-msg"> 前两个）。

    无 kb-item-msg → (None, None)；仅 1 条 → (clean, None)。
    """
    msgs = MSG_RE.findall(html)
    if not msgs:
        return (None, None)
    if len(msgs) == 1:
        return (_clean(msgs[0]), None)
    return (_clean(msgs[0]), _clean(msgs[1]))


async def _fetch_full(client: httpx.AsyncClient, show_id: str, retries: int = 3) -> tuple[str | None, str | None]:
    """抓单条详情页，重试 3 次。返回 (best_full, worst_full)。"""
    url = DETAIL_URL.format(kid=show_id)
    for _ in range(retries):
        try:
            r = await client.get(url, timeout=15)
            if r.status_code == 200 and "kb-item-msg" in r.text:
                return _extract_full_texts(r.text)
        except Exception:
            pass
        await asyncio.sleep(1)
    return (None, None)


# ---------------- nevpool T3：cap / 名单 / 守卫 / 预估 / progress ----------------

def pages_for(max_reviews: int | None, page_size: int = PAGE_SIZE) -> int | None:
    """条数 cap → 页数上限（页粒度向上取整）。None/非正数 → None（不封顶，向后兼容）。

    300 条 / 20 条页 = 15 页；1 条 = 1 页；21 条 = 2 页。"""
    if not max_reviews or max_reviews <= 0:
        return None
    return (max_reviews + page_size - 1) // page_size


def load_pool_series_ids(path: str | Path, tier: str = "deep") -> list[str]:
    """读 nev_pool.json，取指定 tier 的 series_id 列表（红线#6：ID 直接来自文件，不人工转写）。

    容忍三种外壳：裸 list / {"pool": [...]} / {"series": [...]}/...（键序 pool→series→
    items→entries）；条目取 series_id（或 id）字段；文件缺失抛 FileNotFoundError。
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = None
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        for key in ("pool", "series", "items", "entries"):
            if isinstance(data.get(key), list):
                entries = data[key]
                break
        if entries is None:
            # {sid: {tier: ...}} 映射形式
            entries = [{"series_id": k, **v} for k, v in data.items()
                       if isinstance(v, dict)]
    if entries is None:
        raise ValueError(f"nev_pool 结构无法解析：{path}")
    out: list[str] = []
    for e in entries:
        if not isinstance(e, dict) or e.get("tier") != tier:
            continue
        sid = e.get("series_id", e.get("id"))
        if sid is not None:
            out.append(str(sid))
    return out


def find_pool_conflicts(target_ids: list[str], count_fn, threshold: int = EXISTING_POOL_THRESHOLD) -> list[tuple[str, int]]:
    """启动守卫：目标车系 ∩ 存量分析池（owner_reviews 计数 ≥ threshold）。

    返回冲突 [(series_id, count)]；空列表 = 放行。count_fn(sid) -> int。"""
    conflicts: list[tuple[str, int]] = []
    for sid in target_ids:
        c = count_fn(str(sid))
        if c is not None and c >= threshold:
            conflicts.append((str(sid), int(c)))
    return conflicts


def guard_conflicts(series_ids: list[str], count_fn, progress_map: dict | None = None,
                    threshold: int = EXISTING_POOL_THRESHOLD) -> list[tuple[str, int]]:
    """守卫判定（nevpool T3 终版语义）：计数 ≥ threshold 拦截，例外=本管线自有写入。

    首批深采入库后车系即过 100 门槛，字面守卫会把 T4 断点续跑/失败重跑永久锁死；
    故 progress 终态 done/empty 且库内行数与记录精确相等（证明行就是本管线
    delete+insert 写的）的车系豁免。任何外部变动（行数对不上）仍拦截，fail-closed
    属性保留：无 progress 记录的车系照旧 ≥100 即拒。"""
    progress_map = progress_map or {}
    conflicts: list[tuple[str, int]] = []
    for sid in series_ids:
        sid = str(sid)
        c = count_fn(sid)
        if c is None or c < threshold:
            continue
        rec = progress_map.get(sid) or {}
        if rec.get("status") in ("done", "empty") and rec.get("collected", -1) == c:
            continue
        conflicts.append((sid, int(c)))
    return conflicts


def _db_review_count(sid: str) -> int:
    """owner_reviews 中该车系（model_id=series_id）行数。"""
    from sqlalchemy import func
    with session_scope() as s:
        return int(s.query(func.count(OwnerReview.review_id))
                   .filter(OwnerReview.model_id == str(sid)).scalar() or 0)


def _db_source_counts(series_ids: list[str]) -> dict[str, int | None]:
    """从 series_summaries 批量取源站口碑量（review_count），dry-run 预估用（不出网）。

    表中无该系的 sid 不出现在返回 dict；review_count 为 NULL 也记 None。"""
    from sqlalchemy import select
    from src.models.orm import SeriesSummary
    id_list = [str(x) for x in series_ids]
    if not id_list:
        return {}
    with session_scope() as s:
        rows = s.execute(
            select(SeriesSummary.series_id, SeriesSummary.review_count)
            .where(SeriesSummary.series_id.in_(id_list))).fetchall()
    return {sid: cnt for sid, cnt in rows}


def estimate_requests(series_ids: list[str], max_reviews: int | None,
                      source_counts: dict[str, int | None]) -> list[dict]:
    """逐系预估（纯函数）：available=源站口碑量；capped=min(available, cap)；
    pages=ceil(capped/20)（capped=0 → 0）；requests=pages+capped（详情页逐条抓）。"""
    out: list[dict] = []
    for sid in series_ids:
        sid = str(sid)
        avail = source_counts.get(sid)
        row = {"series_id": sid, "available": avail,
               "capped": None, "pages": None, "requests": None}
        if avail is not None:
            capped = min(avail, max_reviews) if (max_reviews and max_reviews > 0) else avail
            pages = (capped + PAGE_SIZE - 1) // PAGE_SIZE if capped > 0 else 0
            row.update(capped=capped, pages=pages, requests=pages + capped)
        out.append(row)
    return out


def find_backup(backups_dir: str | Path | None = None) -> Path | None:
    """T0 备份探测：data/backups/ 下最新一份 autohome-pre-nevpool-*.db；无 → None。"""
    d = Path(backups_dir) if backups_dir else (ROOT / "data" / "backups")
    if not d.is_dir():
        return None
    hits = sorted(d.glob(BACKUP_GLOB))
    return hits[-1] if hits else None


def load_progress(path: str | Path) -> dict[str, dict]:
    """读 progress jsonl → {series_id: record}（跳过损坏行）；文件缺失 → {}。"""
    p = Path(path)
    if not p.is_file():
        return {}
    out: dict[str, dict] = {}
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                sid = rec.get("series_id")
                if sid:
                    out[str(sid)] = rec  # 后写覆盖前写（同系多行取最新态）
            except json.JSONDecodeError:
                continue
    return out


def append_progress(path: str | Path, record: dict) -> None:
    """逐车系完成态追加一行 jsonl。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _tagged_distinct(model_id: str) -> int:
    """该车系 review_tags distinct review_id 数（打标覆盖口径）。"""
    from sqlalchemy import func
    with session_scope() as s:
        return int(s.query(func.count(func.distinct(ReviewTag.review_id)))
                   .filter(ReviewTag.model_id == str(model_id)).scalar() or 0)


# ---------------- 口碑周更增量采集 change：incremental 模式 ----------------

# 加固拍板（2026-11-01 用户）：
# - 水位=连续 2 页全已知才停（防翻页乱序把新口碑滑入深页漏采；代价 ~+1 页/系）
WATERMARK_CONFIRM_PAGES = 2
# - 未打标补扫每系每周上限（增量下打标失败的条目下周即"已知 ID"被跳过，永不再补的兜底）
BACKFILL_TAG_LIMIT = 20


def page_all_known(page_review_ids: list[str], known_ids: set[str]) -> bool:
    """水位停止判定（纯函数）：某页全部 review_id 已知 → 停该系。

    连续 2 页全已知才停（加固拍板 2026-11-01）：之家翻页非严格稳定排序（10-16 铂智3X 实证同条相邻页重复），
    部分已知/乱序页必须继续翻，否则漏新口碑。空页返回 False（P2-1 更正：调用方
    在 items 为空时已提前走自然停止路径，本函数不会收到空页）。
    """
    return bool(page_review_ids) and all(rid in known_ids for rid in page_review_ids)


def _known_review_ids(model_id: str) -> set[str]:
    """库内该车系已有 review_id 集合（水位基准 + insert-skip 双保险）。"""
    with session_scope() as s:
        rows = s.execute(
            text("SELECT review_id FROM owner_reviews WHERE model_id = :mid"),
            {"mid": str(model_id)}).fetchall()
    return {r[0] for r in rows}


def _db_series_review_count(model_id: str) -> int:
    """库内该车系行数（零删除断言用）。"""
    from sqlalchemy import func
    with session_scope() as s:
        return int(s.query(func.count(OwnerReview.review_id))
                   .filter(OwnerReview.model_id == str(model_id)).scalar() or 0)


async def recollect_series_incremental(api: AutohomeAPI, client: httpx.AsyncClient,
                                        series_id: str, semaphore: asyncio.Semaphore,
                                        known_ids: set[str]) -> dict:
    """增量采集单车系：只收集未知 review_id 的新条目，连续 2 页全已知才停。

    返回 {new: [parsed...], pages_fetched: int, stopped: str}
    stopped ∈ all_known（连续 2 页全已知水位停）/ pagecount（翻尽）/ natural（空页自然尽）。
    限流空响应冷却 20s 重试语义与 full 模式一致（P1-3）。
    已知 id 不抓详情页（请求量 ∝ 新增量）。
    本轮已见（seen）只用于去重——之家翻页非严格稳定排序，同一条新口碑相邻页
    复现时只收集首现（full 模式同款语义）。水位判定严格用"库内既有"known_ids
    （不含本轮已收）：新条目出现在页里说明后面可能还有新的，必须继续翻；
    若把本轮已收也算水位，全新车系第 1 页全为新条目时会误停漏采。
    """
    new_results: list[dict] = []
    seen: set[str] = set()
    page = 1
    pages_fetched = 0
    stopped = "natural"
    consecutive_known = 0   # 加固拍板：连续 2 页全已知才停（单页已知继续翻）
    while True:
        async with semaphore:
            data = await api.fetch_koubei_page(series_id, page, page_size=PAGE_SIZE)
        if not data:
            # P1-3 同款：None 可能是限流空响应而非自然尽头——冷却重试一次仍空则抛错
            await asyncio.sleep(20)
            async with semaphore:
                data = await api.fetch_koubei_page(series_id, page, page_size=PAGE_SIZE)
            if not data:
                raise RuntimeError(
                    f"page {page} 连续空响应（疑似限流）——按失败处理，冷却后可重扫")
        pages_fetched += 1
        items = data.get("list", [])
        if not items:
            stopped = "natural"
            break
        page_rids: list[str] = []
        for item in items:
            parsed = AutohomeAPI.parse_koubei_item(item, series_display_name=item.get("seriesname", ""))
            rid = parsed["review_id"]
            page_rids.append(rid)
            if rid in known_ids or rid in seen:
                continue  # insert-skip + 本轮去重（跳过：不抓详情不打标不插入）
            seen.add(rid)
            show_id = (rid[2:]
                       if rid.startswith("k_") and not rid.startswith("k_api_")
                       else "")
            if show_id:
                best_full, worst_full = await _fetch_full(client, show_id)
                parsed["best_full_text"] = best_full
                parsed["worst_full_text"] = worst_full
            else:
                parsed["best_full_text"] = None
                parsed["worst_full_text"] = None
            new_results.append(parsed)
        if page_all_known(page_rids, known_ids):
            consecutive_known += 1
            if consecutive_known >= WATERMARK_CONFIRM_PAGES:
                stopped = "all_known"
                break
        else:
            consecutive_known = 0
        page_count = data.get("pagecount", 1)
        if page >= page_count:
            stopped = "pagecount"
            break
        page += 1
    return {"new": new_results, "pages_fetched": pages_fetched, "stopped": stopped}


def _build_review_row(r: dict, model_id: str) -> OwnerReview:
    """parsed dict → OwnerReview 行（字段与 full 的 _save_series_reviews 一致）。

    口碑周更 change：为守住"full 路径零改动"红线，此构造是增量侧独立复制
    （full 侧不动），字段口径逐一对齐；两处若需演进，先在 review 处裁决再同步。
    """
    purchase_date = r.get("purchase_date")
    if isinstance(purchase_date, str) and purchase_date:
        try:
            for fmt in ("%Y-%m-%d", "%Y-%m", "%Y.%m.%d", "%Y.%m"):
                try:
                    purchase_date = datetime.strptime(
                        purchase_date.replace(".", "-"), fmt).date()
                    break
                except ValueError:
                    continue
            else:
                purchase_date = None
        except (ValueError, TypeError):
            purchase_date = None
    elif not isinstance(purchase_date, date):
        purchase_date = None

    raw_item = r.get("_raw_item", {})
    post_date = raw_item.get("posttime", "") or ""
    if isinstance(post_date, str):
        post_date = post_date.strip()

    return OwnerReview(
        review_id=r["review_id"],
        owner_id=r.get("owner_id"),
        model_full_name=r["model_full_name"],
        spec_name=r.get("spec_name"),
        spec_id=r.get("spec_id"),
        model_id=model_id,
        purchase_date=purchase_date,
        post_date=post_date,
        best_review_text=r.get("best_review_text", ""),
        worst_review_text=r.get("worst_review_text", ""),
        best_full_text=r.get("best_full_text"),
        worst_full_text=r.get("worst_full_text"),
        score=r.get("score"),
        dimensions=r.get("dimensions"),
        buy_price=r.get("buy_price"),
        fuel_consumption=r.get("fuel_consumption"),
        mileage=r.get("mileage"),
        city=r.get("city"),
        use_purposes=r.get("use_purposes"),
        dimension_reviews=r.get("dimension_reviews"),
        exinfo=r.get("exinfo"),
        raw_json=r,
    )


async def _save_new_reviews(new_reviews: list[dict], model_id: str,
                            known_ids: set[str], tagger=None) -> int:
    """增量入库：只插新（insert-skip），绝不 UPDATE/DELETE，附零删除断言。

    - 插入前再查一次主键存在（known_ids 之外的本轮内重复/竞态双保险），已存在跳过不报错
    - 零删除断言：入库前记录该车系行数，入库后断言 after == before + inserted，
      不满足抛 RuntimeError → 调用方 fail-closed（SystemExit 2）——增量模式唯一
      允许的库变化就是"净增"
    - 打标只对本轮实际插入成功的条目（有原文才打，D13 口径同 full）
    """
    from datetime import date as date_type  # noqa: F401 （与 full 侧 import 形态对齐）

    before = _db_series_review_count(model_id)
    inserted: list[dict] = []
    with session_scope() as s:
        for r in new_reviews:
            rid = r["review_id"]
            if rid in known_ids:
                continue
            if s.get(OwnerReview, rid) is not None:
                continue  # 双保险：本轮内重复/竞态已存在 → skip
            s.add(_build_review_row(r, model_id))
            inserted.append(r)
        s.commit()

    after = _db_series_review_count(model_id)
    if after != before + len(inserted):
        raise RuntimeError(
            f"零删除断言失败：{model_id} 行数 before={before} inserted={len(inserted)} "
            f"after={after}（期望 {before + len(inserted)}）——库出现非净增变化，fail-closed")

    if tagger:
        for r in inserted:
            if not (r.get("best_review_text") or r.get("worst_review_text")):
                continue  # 无原文跳过（D13）
            try:
                tags = await tagger.extract_tags(
                    r.get("best_review_text", ""), r.get("worst_review_text", ""))
                if tags:
                    with session_scope() as ts:
                        for tag in tags:
                            ts.add(ReviewTag(
                                review_id=r["review_id"],
                                owner_id=r.get("owner_id", ""),
                                model_full_name=r.get("model_full_name", ""),
                                model_id=model_id,
                                tag_name=tag.get("tag_name", ""),
                                sentiment=tag.get("sentiment", "pro"),
                                source_text=tag.get("source_text", ""),
                                confidence=tag.get("confidence", 0.8),
                                tag_category=tag.get("tag_category", ""),
                            ))
                        ts.commit()
            except Exception as e:
                logger.warning(f"标签提取失败 {r['review_id'][:20]}: {e}")
    return len(inserted)


async def _backfill_untagged(model_id: str, tagger, limit: int = BACKFILL_TAG_LIMIT) -> int:
    """未打标补扫（加固拍板 2026-11-01）：有原文但无标签的口碑 → 补打标。

    增量模式下打标失败的条目下周即为"已知 ID"被跳过、永不再补——本函数兜底。
    语义：每系每周至多 limit 条；关键词优先零成本，LLM 兜底仅关键词未命中者；
    extract 成功但返回空标签的条目下周仍会重试（无标记位可写，bounded 噪音由
    limit 封顶）；单条失败 warning 不中断。返回成功补打（拿到标签）的条数。
    """
    if not tagger:
        return 0
    with session_scope() as s:
        rows = s.execute(
            text("SELECT review_id, owner_id, model_full_name, best_review_text, "
                 "worst_review_text FROM owner_reviews "
                 "WHERE model_id = :mid AND (TRIM(COALESCE(best_review_text,'')) != '' "
                 "OR TRIM(COALESCE(worst_review_text,'')) != '') "
                 "AND review_id NOT IN (SELECT DISTINCT review_id FROM review_tags "
                 "WHERE model_id = :mid) "
                 "ORDER BY review_id LIMIT :lim"),
            {"mid": str(model_id), "lim": limit}).fetchall()
    done = 0
    for rid, owner_id, mfn, best, worst in rows:
        try:
            tags = await tagger.extract_tags(best or "", worst or "")
            if tags:
                with session_scope() as ts:
                    for tag in tags:
                        ts.add(ReviewTag(
                            review_id=rid,
                            owner_id=owner_id or "",
                            model_full_name=mfn or "",
                            model_id=str(model_id),
                            tag_name=tag.get("tag_name", ""),
                            sentiment=tag.get("sentiment", "pro"),
                            source_text=tag.get("source_text", ""),
                            confidence=tag.get("confidence", 0.8),
                            tag_category=tag.get("tag_category", "")))
                    ts.commit()
                done += 1
        except Exception as e:
            logger.warning(f"补打标失败 {str(rid)[:20]}: {e}")
    return done


def _pool_series_ids_from_db() -> list[str]:
    """增量名单：库内有口碑的车系全集（DISTINCT model_id，剔 NULL/空——P2-5）。"""
    with session_scope() as s:
        rows = s.execute(
            text("SELECT DISTINCT model_id FROM owner_reviews "
                 "WHERE model_id IS NOT NULL AND TRIM(model_id) != '' "
                 "ORDER BY model_id")).fetchall()
    return [r[0] for r in rows]


# ---------------- 采集主流程（翻页/详情/打标逻辑未动） ----------------

async def recollect_series(api: AutohomeAPI, client: httpx.AsyncClient,
                           series_id: str, semaphore: asyncio.Semaphore,
                           max_reviews: int | None = None) -> list[dict]:
    """采集单车系口碑 + 抓详情页原文。返回 parsed list（含 best_full_text/worst_full_text）。

    max_reviews：单车系条数 cap，页粒度向上取整（300→15 页）；None=不封顶（原行为）。
    实采条数可能略超 cap（最多多一页，页内整页保留）。"""
    results: list[dict] = []
    page = 1
    max_pages = pages_for(max_reviews)
    while True:
        async with semaphore:
            data = await api.fetch_koubei_page(series_id, page, page_size=PAGE_SIZE)
        if not data:
            # P1-3（2026-10-18）：None 可能是限流空响应而非自然尽头——冷却 20s 重试一次，
            # 仍空则抛错走 failures（可断点重扫），不再静默记 empty/截断（配合 P1-2 原子事务：
            # 要么整系完整落库，要么原数据原封不动）。
            await asyncio.sleep(20)
            async with semaphore:
                data = await api.fetch_koubei_page(series_id, page, page_size=PAGE_SIZE)
            if not data:
                raise RuntimeError(
                    f"page {page} 连续空响应（疑似限流）——按失败处理，冷却后可重扫")
        items = data.get("list", [])
        if not items:
            break
        for item in items:
            parsed = AutohomeAPI.parse_koubei_item(item, series_display_name=item.get("seriesname", ""))
            rid = parsed["review_id"]
            show_id = rid[2:] if rid.startswith("k_") and not rid.startswith("k_api_") else ""
            if show_id:
                best_full, worst_full = await _fetch_full(client, show_id)
                parsed["best_full_text"] = best_full
                parsed["worst_full_text"] = worst_full
            else:
                parsed["best_full_text"] = None
                parsed["worst_full_text"] = None
            results.append(parsed)
        page_count = data.get("pagecount", 1)
        if page >= page_count:
            break
        if max_pages is not None and page >= max_pages:
            break
        page += 1

    # nevpool T3 实测修复：之家翻页非严格稳定排序，同一条口碑可能在相邻页重复返回，
    # results 内 review_id 重复 → owner_reviews 主键冲突整批回滚（2026-10-16 铂智3X 实证）。
    # 按 review_id 去重保首现，不改变翻页/解析/打标语义。
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in results:
        rid = r.get("review_id")
        if rid in seen:
            continue
        seen.add(rid)
        deduped.append(r)
    if len(deduped) < len(results):
        logger.warning(f"{series_id}: 翻页重复 {len(results) - len(deduped)} 条已去重"
                       f"（{len(results)} → {len(deduped)}）")
    return deduped


async def _save_series_reviews(reviews: list[dict], model_id: str, tagger=None) -> int:
    """delete+insert：先删该车系旧 owner_reviews（CASCADE 删 review_tags），再插新数据。

    旧 review_id=k_{Koubeigid} 与新 k_{showId} 不冲突，若不删会共存导致口碑数翻倍。
    同步触发标签提取（R1 根因修复，V1 修复：补 owner_id + model_full_name NOT NULL）。
    """
    from datetime import date as date_type, datetime

    with session_scope() as s:
        # 删旧：CASCADE 级联删 review_tags（FK ondelete=CASCADE）
        # P1-2（2026-10-18）：去掉中途 commit——delete+insert 同事务，任一行插入失败
        # 整体回滚（旧数据原封不动），不再出现"删了没插进去"的车系清零。
        s.query(OwnerReview).filter(OwnerReview.model_id == model_id).delete()

        count = 0
        for r in reviews:
            purchase_date = r.get("purchase_date")
            if isinstance(purchase_date, str) and purchase_date:
                try:
                    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y.%m.%d", "%Y.%m"):
                        try:
                            purchase_date = datetime.strptime(
                                purchase_date.replace(".", "-"), fmt
                            ).date()
                            break
                        except ValueError:
                            continue
                    else:
                        purchase_date = None
                except (ValueError, TypeError):
                    purchase_date = None
            elif not isinstance(purchase_date, date_type):
                purchase_date = None

            raw_item = r.get("_raw_item", {})
            post_date = raw_item.get("posttime", "") or ""
            if isinstance(post_date, str):
                post_date = post_date.strip()

            review = OwnerReview(
                review_id=r["review_id"],
                owner_id=r.get("owner_id"),
                model_full_name=r["model_full_name"],
                spec_name=r.get("spec_name"),
                spec_id=r.get("spec_id"),
                model_id=model_id,
                purchase_date=purchase_date,
                post_date=post_date,
                best_review_text=r.get("best_review_text", ""),
                worst_review_text=r.get("worst_review_text", ""),
                best_full_text=r.get("best_full_text"),
                worst_full_text=r.get("worst_full_text"),
                score=r.get("score"),
                dimensions=r.get("dimensions"),
                buy_price=r.get("buy_price"),
                fuel_consumption=r.get("fuel_consumption"),
                mileage=r.get("mileage"),
                city=r.get("city"),
                use_purposes=r.get("use_purposes"),
                dimension_reviews=r.get("dimension_reviews"),
                exinfo=r.get("exinfo"),
                raw_json=r,
            )
            s.add(review)
            count += 1
        s.commit()

    # 同步标签提取（R1 根因修复，V1 修复：补 owner_id + model_full_name NOT NULL）
    if tagger:
        for r in reviews:
            if not (r.get("best_review_text") or r.get("worst_review_text")):
                continue  # 无原文跳过（D13）
            try:
                tags = await tagger.extract_tags(
                    r.get("best_review_text", ""), r.get("worst_review_text", ""))
                if tags:
                    with session_scope() as ts:
                        for tag in tags:
                            ts.add(ReviewTag(
                                review_id=r["review_id"],
                                owner_id=r.get("owner_id", ""),
                                model_full_name=r.get("model_full_name", ""),
                                model_id=model_id,
                                tag_name=tag.get("tag_name", ""),
                                sentiment=tag.get("sentiment", "pro"),
                                source_text=tag.get("source_text", ""),
                                confidence=tag.get("confidence", 0.8),
                                tag_category=tag.get("tag_category", ""),
                            ))
                        ts.commit()
            except Exception as e:
                logger.warning(f"标签提取失败 {r['review_id'][:20]}: {e}")
    return count


async def recollect_all(series_ids: list[str] | None = None, limit_series: int = 0,
                        max_reviews: int | None = None,
                        live: bool | None = None,
                        progress_path: str | Path | None = None,
                        force: bool = False, inter_series_sleep: float = 0.0,
                        mode: str = "full", budget_reviews: int | None = None) -> dict:
    """重新采集口碑 + 详情页原文（nevpool T3 后：默认 dry-run 门控 + 守卫 + cap + 断点）。

    - live=None → 读 env PRISM_COLLECT_LIVE（==1 才真采）；False → dry-run（零写入零出网）。
    - max_reviews：单车系条数 cap（页粒度取整）；None=不封顶（向后兼容）。
    - progress_path：断点续跑 jsonl；live 模式逐系追加，done/empty 跳过；
      force=True 忽略该跳过（补足/重扫场景，守卫豁免仍按精确对账）。
      inter_series_sleep：系间冷却秒数（防持续请求触发限流空响应）。
    - mode：full=现役 delete+insert（语义零改动）；incremental=周更增量（只插新绝不删，
      名单缺省=库内有口碑全集，守卫不适用，progress 缺省 weekly_progress.jsonl）
    - budget_reviews：incremental 全池新入库总帽；None=不封顶。触顶后未开始车系标
      budget_capped 早退（正常终态）。
    返回 stats dict；守卫/备份拦截 raise SystemExit(2)。"""
    if mode not in ("full", "incremental"):
        raise SystemExit(f"--mode 取值非法（full|incremental）: {mode}")
    init_db()
    if not series_ids:
        if mode == "incremental":
            series_ids = _pool_series_ids_from_db()
        else:
            snapshots = list_config_snapshots()
            series_ids = [s["id"] for s in snapshots]
        if limit_series:
            series_ids = series_ids[:limit_series]
    series_ids = [str(x) for x in series_ids]

    if live is None:
        live = os.environ.get("PRISM_COLLECT_LIVE", "") == "1"
    if progress_path is None:
        progress_path = (DEFAULT_WEEKLY_PROGRESS_PATH if mode == "incremental"
                         else DEFAULT_PROGRESS_PATH)
    progress_path = Path(progress_path)
    done_map = load_progress(progress_path)

    # 启动守卫（fail-closed）：delete+insert 禁入存量分析池（计数 ≥100），dry-run 同样拦截；
    # 例外=本管线自有写入（progress 终态 + 库内行数与记录相等），语义见 guard_conflicts。
    # incremental 无 delete，不适用此守卫（防的是 delete 破坏）。
    if mode == "full":
        conflicts = guard_conflicts(series_ids, _db_review_count, done_map)
        if conflicts:
            print("✋ 守卫拦截：目标车系与存量分析池（owner_reviews 计数≥"
                  f"{EXISTING_POOL_THRESHOLD}）交集非空，delete+insert 会删存量数据，拒跑。", flush=True)
            for sid, c in conflicts:
                print(f"  冲突车系 {sid}: 现有 {c} 条", flush=True)
            raise SystemExit(2)

    if not live:
        # ---- dry-run（默认）：只打印名单+预估，零写入零出网 ----
        if mode == "incremental":
            print(f"[DRY-RUN|incremental] 待增量 {len(series_ids)} 个车系"
                  f"（budget={'不限' if not budget_reviews else budget_reviews} 条）。"
                  "每系从第 1 页探测（连续 2 页全已知才停）；真采请设 PRISM_COLLECT_LIVE=1", flush=True)
            done_ids = [sid for sid, recd in done_map.items()
                        if recd.get("status") in ("done", "empty") and sid in set(series_ids)]
            if done_ids:
                print(f"  progress 断点：已完成 {len(done_ids)} 系（live 时将跳过）", flush=True)
            print(f"[DRY-RUN|incremental] 预估打底请求 ≈ {len(series_ids)} 页列表"
                  "（详情页与打标请求 ∝ 实际新增量）", flush=True)
            return {"status": "dry-run", "mode": mode, "series_ids": series_ids,
                    "budget_reviews": budget_reviews, "conflicts": []}
        print(f"[DRY-RUN] 待采 {len(series_ids)} 个车系（cap={'不限' if not max_reviews else max_reviews}）。"
              "真采请设 PRISM_COLLECT_LIVE=1", flush=True)
        done_ids = [sid for sid, recd in done_map.items()
                    if recd.get("status") in ("done", "empty") and sid in set(series_ids)]
        if done_ids:
            print(f"  progress 断点：已完成 {len(done_ids)} 系（live 时将跳过）", flush=True)
        source = _db_source_counts(series_ids)
        est = estimate_requests(series_ids, max_reviews, source)
        unknown = 0
        for row in est:
            if row["requests"] is None:
                unknown += 1
                print(f"  {row['series_id']}: 源站量未知（series_summaries 无该系）", flush=True)
            else:
                print(f"  {row['series_id']}: 源站约 {row['available']} 条 → 采 {row['capped']} 条"
                      f"（{row['pages']} 页列表 + {row['capped']} 详情）≈ {row['requests']} 请求", flush=True)
        known = [r for r in est if r["requests"] is not None]
        total_req = sum(r["requests"] for r in known)
        print(f"[DRY-RUN] 预估合计 ≈ {total_req} 请求（{len(known)} 系可估"
              f"{'，' + str(unknown) + ' 系源站量未知' if unknown else ''}）", flush=True)
        return {"status": "dry-run", "series_ids": series_ids, "estimate": est,
                "total_requests": total_req, "conflicts": []}

    # ---- live ----
    # full：无 NEV 备份不跑（T0 前置）；incremental：备份职责在入口层
    # koubei_weekly_update.py（live 前自动 sqlite backup API），此处不查。
    backup_name = ""
    if mode == "full":
        backup = find_backup()
        if backup is None:
            print(f"✋ 守卫拦截：data/backups/ 下无 {BACKUP_GLOB} 备份（T0 前置），拒跑。", flush=True)
            raise SystemExit(2)
        backup_name = backup.name
    # P1-1（2026-10-18）：共壳双 sales 名会让 pool 名单产出重复 sid——单轮双跑
    # （双倍请求；二遍限流截断还会把一遍的 300 条覆盖成残次）。保序去重。
    series_ids = list(dict.fromkeys(series_ids))
    print(f"[LIVE|{mode}] 真采 {len(series_ids)} 个车系"
          f"（cap={'不限' if not max_reviews else max_reviews}），"
          + (f"备份 {backup_name}" if backup_name else "备份由入口层负责"), flush=True)

    pending = [sid for sid in series_ids
               if force or done_map.get(sid, {}).get("status") not in ("done", "empty")]
    skipped = len(series_ids) - len(pending)
    if skipped:
        print(f"  progress 断点：跳过已完成 {skipped} 系，实跑 {len(pending)} 系", flush=True)
    elif force and series_ids:
        print("  --force：忽略断点 done/empty，全部重跑", flush=True)

    t_all = time.perf_counter()
    api = AutohomeAPI()
    semaphore = asyncio.Semaphore(3)
    failures: list[tuple[str, str]] = []
    tagger = await get_tagger()
    budget_capped_series: list[str] = []
    total_new = 0
    total_backfilled = 0

    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
        for i, sid in enumerate(pending):
            if i and inter_series_sleep:
                time.sleep(inter_series_sleep)
            t0 = time.perf_counter()
            try:
                if mode == "incremental":
                    # 预算帽：触顶后未开始车系标 budget_capped 早退（正常终态，照舆情语义）
                    if budget_reviews is not None and total_new >= budget_reviews:
                        budget_capped_series.append(sid)
                        append_progress(progress_path, {
                            "series_id": sid, "status": "budget_capped",
                            "budget_used": total_new,
                            "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                        continue
                    known = _known_review_ids(sid)
                    res = await recollect_series_incremental(api, client, sid, semaphore, known)
                    inserted = 0
                    tagged = None
                    if res["new"]:
                        inserted = await _save_new_reviews(res["new"], sid, known, tagger=tagger)
                        tagged = _tagged_distinct(sid)
                        total_new += inserted
                    backfilled = await _backfill_untagged(sid, tagger)
                    total_backfilled += backfilled
                    elapsed = time.perf_counter() - t0
                    print(f"  [{i + 1}/{len(pending)}] {sid}: 新增 {inserted} 条"
                          f"（{res['pages_fetched']} 页，{res['stopped']}），"
                          f"打标覆盖 {tagged if tagged is not None else '—'}，"
                          f"补打标 {backfilled} 条，耗时 {elapsed:.0f}s",
                          flush=True)
                    append_progress(progress_path, {
                        "series_id": sid, "status": "done", "new": inserted,
                        "pages": res["pages_fetched"], "stopped": res["stopped"],
                        "tagged_distinct": tagged, "backfilled_tags": backfilled,
                        "elapsed_s": round(elapsed, 1),
                        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                else:
                    results = await recollect_series(api, client, sid, semaphore,
                                                     max_reviews=max_reviews)
                    if not results:
                        print(f"  [{i + 1}/{len(pending)}] {sid}: 无口碑", flush=True)
                        append_progress(progress_path, {
                            "series_id": sid, "status": "empty", "collected": 0,
                            "elapsed_s": round(time.perf_counter() - t0, 1),
                            "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
                        continue
                    saved = await _save_series_reviews(results, sid, tagger=tagger)
                    tagged = _tagged_distinct(sid)
                    elapsed = time.perf_counter() - t0
                    full_hits = sum(1 for r in results if r.get("best_full_text"))
                    print(f"  [{i + 1}/{len(pending)}] {sid}: 采集 {saved} 条，详情页原文命中 {full_hits}，"
                          f"打标覆盖 {tagged} 条，耗时 {elapsed:.0f}s", flush=True)
                    append_progress(progress_path, {
                        "series_id": sid, "status": "done", "collected": saved,
                        "tagged_distinct": tagged, "full_hits": full_hits,
                        "elapsed_s": round(elapsed, 1),
                        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            except Exception as e:
                failures.append((sid, str(e)))
                print(f"  [{i + 1}/{len(pending)}] {sid}: 失败 {e}", flush=True)
                append_progress(progress_path, {
                    "series_id": sid, "status": "failed", "error": str(e)[:200],
                    "elapsed_s": round(time.perf_counter() - t0, 1),
                    "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

    await api.close()
    await close_tagger()

    if failures:
        with open(ROOT / "data" / "recollect_failures.json", "w", encoding="utf-8") as f:
            json.dump(failures, f, ensure_ascii=False)
    elapsed_all = time.perf_counter() - t_all
    print(f"完成。失败 {len(failures)} 个车系，总耗时 {elapsed_all:.0f}s", flush=True)
    stats: dict = {"status": "live", "mode": mode, "series_ids": series_ids,
                   "pending": pending, "skipped_by_progress": skipped,
                   "failures": failures, "elapsed_s": round(elapsed_all, 1),
                   "progress_path": str(progress_path)}
    if mode == "incremental":
        stats.update({"new_reviews_total": total_new,
                      "backfilled_tags_total": total_backfilled,
                      "budget_capped_series": budget_capped_series})
        if budget_capped_series:
            print(f"预算帽 {budget_reviews} 触顶：{len(budget_capped_series)} 系未跑（budget_capped）",
                  flush=True)
    return stats


def _parse_args(argv: list[str]) -> dict:
    """支持 --flag value 与 --flag=value 两种形式。"""
    args: dict = {"series_ids": None, "limit_series": 0, "max_reviews": None,
                  "pool_file": None, "progress_file": None, "force": False,
                  "series_delay": 0.0, "mode": "full", "budget_reviews": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        val: str | None = None
        if "=" in a:
            key, val = a.split("=", 1)
        else:
            key = a
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                val = argv[i + 1]
                i += 1
        if key == "--series-ids" and val:
            args["series_ids"] = [x for x in val.split(",") if x]
        elif key == "--limit-series" and val:
            args["limit_series"] = int(val)
        elif key == "--max-reviews" and val:
            args["max_reviews"] = int(val)
        elif key == "--pool-file" and val:
            args["pool_file"] = val
        elif key == "--progress-file" and val:
            args["progress_file"] = val
        elif key == "--force":
            args["force"] = True
        elif key == "--series-delay" and val:
            args["series_delay"] = float(val)
        elif key == "--mode" and val:
            args["mode"] = val.strip().lower()
        elif key == "--budget-reviews" and val:
            args["budget_reviews"] = int(val)
        i += 1
    return args


if __name__ == "__main__":
    _args = _parse_args(sys.argv[1:])

    # 名单解析：--series-ids 显式优先；否则 --pool-file（缺省 data/nev_pool.json）取 tier=deep
    _series_ids = _args["series_ids"]
    _pool_explicit = _args["pool_file"] is not None
    _pool_path = Path(_args["pool_file"]) if _pool_explicit else DEFAULT_POOL_PATH
    if not _series_ids:
        if _args["mode"] == "incremental" and not _pool_explicit:
            # P1-1（Step8）：incremental 名单缺省=库内有口碑全集，由 recollect_all 内部
            # 解析——不读 pool 文件（tier=deep 71 系 ≠ 库内全集，CLI 直跑会漏 27 系）；
            # --pool-file 显式给定时照旧尊重（用户点名名单）。
            _series_ids = None
            print("名单缺省：库内有口碑全集（incremental 模式，由 recollect_all 解析）", flush=True)
        elif _pool_path.is_file():
            _series_ids = load_pool_series_ids(_pool_path, tier="deep")
            print(f"名单来源 {_pool_path}: tier=deep 共 {len(_series_ids)} 系", flush=True)
        elif _pool_explicit:
            print(f"✋ pool-file 不存在：{_pool_path}。请改用 --series-ids 显式指定名单。", flush=True)
            raise SystemExit(2)
        else:
            print(f"提示：默认名单文件不存在（{_pool_path}，T1 尚未生成？）。"
                  "回退 legacy 名单（config_snapshots 全量）；如需指定请用 --series-ids。", flush=True)

    _stats = asyncio.run(recollect_all(
        series_ids=_series_ids, limit_series=_args["limit_series"],
        max_reviews=_args["max_reviews"], progress_path=_args["progress_file"],
        force=_args["force"], inter_series_sleep=_args["series_delay"],
        mode=_args["mode"], budget_reviews=_args["budget_reviews"]))
    sys.exit(1 if _stats.get("failures") else 0)
