"""只读数据看板路由：口碑看板（读库，可筛选）+ 配置看板（实时 API，单车系/多车系对比）。

供最终用户在浏览器使用：
- /dashboard/koubei            口碑总览：级别/价格段/搜索筛选，车系行链接到下钻页
- /dashboard/koubei/series/{model_id}  车型下钻（口碑版型/省份/维度）
- /dashboard/config            配置：单车系版型+参数；勾选 2-6 个车系横向对比差异项；
                               版型级对比（trim=mid:spec,…）+ 配置差价（/config/compare-valued，后端唯一实现）

纪律：本路由主体只读（查询 + 现有工具层函数），不写库、不触发采集。
写例外（新增写端点必须同步 CLAUDE.md 看板读写边界清单）：
- POST /config/refresh-snapshot/{sid}  拉之家 API → upsert config_snapshots
- POST /koubei/series/{id}/insight     不写库，但消耗 LLM（insight_cache 落缓存，
  限流每 IP 10 次/分钟）
（data-layer-tag-system 阶段2：POST /config/prices + /config/policy-prices 已删）
不触碰 agent-loop / chat_routes 的编排逻辑（红线）。
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import date, datetime

from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.storage.db import session_scope
from src.models.orm import SeriesSummary, REVIEW_TAGS_UQ_NAME
from src.tools.config import _render_config_val
from sqlalchemy import text
from sqlalchemy import func, distinct

router = APIRouter(prefix="/dash")
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "web" / "templates"))

_PRICE_RE = re.compile(r"([\d.]+)")


def _fmt_value_for_cmp(v) -> str:
    """配置对比表取值归一：list[{name}]/dict 过 _render_config_val（不泄漏 Python repr），
    标量 str；None/空串归一为空字符串（cmp_view 后续 _fmt 再转 -）。

    P0-7：与 chat/MCP 路径（_render_config_val）保持同一口径，d203e53 同类全路径修复。
    """
    if isinstance(v, (list, dict)):
        return _render_config_val(v)
    return str(v) if v not in (None, "") else ""


def _parse_price_range(price_str: str | None) -> tuple[float | None, float | None]:
    """'10.98-16.89万' → (10.98, 16.89)；解析失败返回 (None, None)。"""
    if not price_str:
        return None, None
    nums = _PRICE_RE.findall(price_str)
    if not nums:
        return None, None
    vals = [float(n) for n in nums if 0 < float(n) < 1000]
    if not vals:
        return None, None
    return vals[0], (vals[-1] if len(vals) > 1 else vals[0])


def _batch_tag_coverage() -> dict[str, dict]:
    """一次性 GROUP BY 取全部车系的标签覆盖率（P3#30 性能：替代逐车系
    _tag_coverage_for_series 的 ~650 次 COUNT——216 系列表页 3s → 2 条查询）。

    两条独立聚合而非一条 LEFT JOIN：join 会让 review_tags 多行复制 taggable
    计数（corrupt 计数）。口径与 _tag_coverage_for_series 一致：
    tagged = 有至少一个标签、且口碑本身有文本的数（与分母同口径交集，
    2026-10-18 修正：老数据只有全文无短文本，此前分子含"无短文本但已被打标"
    的口碑导致 tagged>taggable、覆盖率 >100%），
    taggable = best/worst 短文本或 best/worst 全文有内容的口碑数；coverage 保留 4 位小数。
    """
    with session_scope() as s:
        _text_cond = ("((o.best_review_text IS NOT NULL AND o.best_review_text != '') "
                      "OR (o.worst_review_text IS NOT NULL AND o.worst_review_text != '') "
                      "OR (o.best_full_text IS NOT NULL AND o.best_full_text != '') "
                      "OR (o.worst_full_text IS NOT NULL AND o.worst_full_text != ''))")
        taggable_map = {r[0]: r[1] for r in s.execute(text(
            "SELECT model_id, COUNT(*) FROM owner_reviews o "
            "WHERE " + _text_cond + " "
            "GROUP BY model_id")).fetchall()}
        tagged_map = {r[0]: r[1] for r in s.execute(text(
            "SELECT t.model_id, COUNT(DISTINCT t.review_id) FROM review_tags t "
            "JOIN owner_reviews o ON o.review_id = t.review_id AND o.model_id = t.model_id "
            "WHERE " + _text_cond + " "
            "GROUP BY t.model_id")).fetchall()}
    out: dict[str, dict] = {}
    for mid, taggable in taggable_map.items():
        tagged = tagged_map.get(mid, 0)
        out[mid] = {"tagged": tagged, "taggable": taggable,
                    "coverage": round(tagged / taggable, 4) if taggable else 0.0}
    return out


# P3#32：AI 总结端点限流（每次调用触发一次 LLM，付费，可被脚本循环刷）。
# {ip: [window_start, count]}，窗口 60s 内超过 10 次 → 429。
_INSIGHT_RATE: dict[str, list] = {}
_INSIGHT_RATE_LIMIT = 10
_INSIGHT_RATE_WINDOW = 60.0

# dashboard-v10 Task 1.2：写端点限流（防脚本循环刷写库/写文件）。
# 与 _INSIGHT_RATE 独立计数——10 次 insight 不应阻断 config/prices 写。
_WRITE_RATE: dict[str, list] = {}


def _rate_limited(ip: str | None, rate: dict[str, list] | None = None) -> bool:
    """滑动窗口计数（每 IP 每分钟 _INSIGHT_RATE_LIMIT 次）。非线程安全——
    本端点为 async 单事件循环内计数，无并发写竞争。
    rate 参数可传独立计数器（_WRITE_RATE），默认 _INSIGHT_RATE。"""
    bucket = rate if rate is not None else _INSIGHT_RATE
    now = time.monotonic()
    ip = ip or "unknown"
    # 顺手清理过期窗口，防 dict 无限增长
    for k in [k for k, v in bucket.items() if now - v[0] >= _INSIGHT_RATE_WINDOW]:
        bucket.pop(k, None)
    rec = bucket.get(ip)
    if rec is None or now - rec[0] >= _INSIGHT_RATE_WINDOW:
        bucket[ip] = [now, 1]
        return False
    rec[1] += 1
    return rec[1] > _INSIGHT_RATE_LIMIT


@router.get("/")
async def dashboard_index(request: Request):
    # P1-13：口碑车系数动态计数（查库），不再硬编码
    # P0-4/3.4：两看板车系集合不一致披露（快照有/口碑无 + 口碑有/快照无）
    with session_scope() as s:
        koubei_ids = {r[0] for r in s.execute(text(
            "SELECT DISTINCT model_id FROM owner_reviews")).fetchall()}
        config_ids = {r[0] for r in s.execute(text(
            "SELECT series_id FROM config_snapshots")).fetchall()}
    koubei_series_n = len(koubei_ids)
    config_series_n = len(config_ids)
    # 集合差异：快照有/口碑无（配置看板独有）+ 口碑有/快照无（口碑看板独有）
    snap_only = config_ids - koubei_ids
    koubei_only = koubei_ids - config_ids
    # v8 Task 3.3：启动/请求自检黄牌（快照陈旧等；series_alias 检查已随该表退役移除）
    from src.api.selfcheck import selfcheck_warnings
    return _templates.TemplateResponse(request, "dash_index.html", {
        "request": request,
        "koubei_series_n": koubei_series_n,
        "config_series_n": config_series_n,
        "snap_only_n": len(snap_only),
        "koubei_only_n": len(koubei_only),
        "selfcheck_warnings": selfcheck_warnings(),
    })


@router.get("/koubei")
async def koubei_dashboard(request: Request, level: str | None = None,
                           price_min: float | None = None, price_max: float | None = None,
                           price: str | None = None, q: str | None = None,
                           sort: str | None = None):
    """口碑看板：全部数据实测自 SQLite；车系行链接到下钻页（详情不内嵌）。

    P2#21+#22：筛选/排序进 URL（服务端过滤，可分享/可刷新/可后退）——
    level 精确匹配；price_min/price_max 按车系最低价（万）过滤，price 桶
    （"10-15"/"30-"/"unknown"）是表单下拉的便捷写法；q 车系名包含；
    sort ∈ reviews|score|coverage（默认 reviews）。"""
    with session_scope() as s:
        per_series_raw = {
            r[0]: {"db_reviews": r[1], "last_fetched": str(r[2])[:16] if r[2] else "-",
                   "last_post": str(r[3])[:10] if r[3] else "-"}
            for r in s.execute(text(
                "SELECT model_id, COUNT(*), MAX(fetched_at), MAX(post_date) "
                "FROM owner_reviews GROUP BY model_id")).fetchall()
        }
        summary_map = {x.series_id: x for x in s.query(SeriesSummary).all()}

        # 数据质量（change-1 实证）：dup/orphan 查询保留（工程排查口径），
        # P2#27 起不再上页面——页面只呈现 PM 视角的覆盖率分布/陈旧车系。
        tag_total = s.execute(text("SELECT COUNT(*) FROM review_tags")).scalar()
        idx = s.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=:n"),
            {"n": REVIEW_TAGS_UQ_NAME}).fetchone()

    rows = []
    today = date.today()
    cov_map = _batch_tag_coverage()  # P3#30：两条 GROUP BY 替代逐系 3×COUNT
    _zero = {"tagged": 0, "taggable": 0, "coverage": 0.0}
    for mid, raw in per_series_raw.items():
        cov = cov_map.get(mid, _zero)
        summ = summary_map.get(mid)
        if summ is None:
            # 无档案卡的 id 不进列表（如 Atuohome 时代遗留测试数据：122=英菲尼迪FX35）——
            # 渲染不出名字与维度，只会显示"未知车系"误导用户。
            continue
        pmin, pmax = _parse_price_range(summ.price_range if summ else None)
        # P1#15：价格区间缺「万」后缀时补上（仅在能解析出数字时，防"暂无"类文案误加）
        price_str = (summ.price_range or "-") if summ else "-"
        if price_str != "-" and "万" not in price_str and pmin is not None:
            price_str += "万"
        # P1#14：陈旧（最新发帖 >180 天）/低覆盖（<50%）黄牌；日期缺失/不可解析不判陈旧
        stale = False
        try:
            stale = (today - datetime.strptime(raw["last_post"], "%Y-%m-%d").date()).days > 180
        except ValueError:
            pass
        rows.append({
            "model_id": mid,
            # K-11：缺名回退为纯中文占位（不再拼接数字 ID，避免数字 ID 泄漏）
            "name": (summ.series_name if summ else "未知车系"),
            "level": (summ.level_name or "其他") if summ else "其他",
            "price": price_str,
            "pmin": pmin, "pmax": pmax,
            "score": summ.average_score if summ else None,
            "db_reviews": raw["db_reviews"],
            "tagged": cov["tagged"], "taggable": cov["taggable"],
            "coverage": cov["coverage"],
            # P0-4 采集覆盖率（库内/之家标注总数）；缺失→None（模板显"—"）。
            # 2026-10-18 封顶 1.0：onsell_review_count 是之家缓存标注，滞后常见
            # （源站标注 2 条、库内实采 100 → 曾渲染 5000%）。超 1 = "库内 ≥ 源站标注"。
            "onsell_total": (summ.onsell_review_count if summ else None),
            "collection_coverage": (
                min(round(raw["db_reviews"] / summ.onsell_review_count, 4), 1.0)
                if summ and summ.onsell_review_count and summ.onsell_review_count > 0
                else None),
            "stale": stale, "low_cov": cov["coverage"] < 0.5,
            # P0-4/3.3 黄牌：采集覆盖率 <80%
            "low_collection": (
                summ is not None and summ.onsell_review_count is not None
                and summ.onsell_review_count > 0
                and raw["db_reviews"] / summ.onsell_review_count < 0.8),
            "last_fetched": raw["last_fetched"], "last_post": raw["last_post"],
        })
    rows.sort(key=lambda r: (-r["db_reviews"], r["name"]))

    # P2#27 质量面板（PM 视角，全库口径）：覆盖率分布 + 陈旧车系计数
    quality = {
        "cov_high": sum(1 for r in rows if r["coverage"] >= 0.8),
        "cov_mid": sum(1 for r in rows if 0.5 <= r["coverage"] < 0.8),
        "cov_low": sum(1 for r in rows if r["coverage"] < 0.5),
        "stale_n": sum(1 for r in rows if r["stale"]),
        "index_ok": bool(idx), "index_name": REVIEW_TAGS_UQ_NAME,
    }

    # P2#22 服务端筛选：价格桶换算（显式 price_min/price_max 优先，桶仅兜底）
    unknown_only = False
    if price and price_min is None and price_max is None:
        if price == "unknown":
            unknown_only = True
        elif "-" in price:
            lo, _, hi = price.partition("-")
            try:
                price_min = float(lo) if lo else None
                price_max = float(hi) if hi else None
            except ValueError:
                pass
    ql = (q or "").strip().lower()

    def _match(r: dict) -> bool:
        if level and r["level"] != level:
            return False
        if unknown_only:
            if r["pmin"] is not None:
                return False
        elif price_min is not None or price_max is not None:
            # 与旧 JS 同口径：按车系最低价过滤；价格未知的车系在区间筛选下如实排除
            if r["pmin"] is None:
                return False
            if price_min is not None and r["pmin"] < price_min:
                return False
            if price_max is not None and r["pmin"] >= price_max:
                return False
        if ql and ql not in r["name"].lower():
            return False
        return True

    shown = [r for r in rows if _match(r)]

    # P2#21 排序：reviews（默认，口碑数降序）/ score（均分降序，无分排尾）/ coverage
    if sort == "score":
        shown.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), r["name"]))
    elif sort == "coverage":
        shown.sort(key=lambda r: (-r["coverage"], r["name"]))
    else:
        sort = "reviews"

    # 排序表头链接：保留当前筛选参数（跨页状态全部编码在 URL）
    from urllib.parse import urlencode
    base = {k: v for k, v in (("level", level), ("price_min", price_min),
                              ("price_max", price_max), ("price", price), ("q", q))
            if v not in (None, "")}
    sort_urls = {k: "/dash/koubei?" + urlencode({**base, "sort": k})
                 for k in ("reviews", "score", "coverage")}

    levels = sorted({r["level"] for r in rows})
    total_reviews = sum(r["db_reviews"] for r in shown)
    total_taggable = sum(r["taggable"] for r in shown)
    total_tagged = sum(r["tagged"] for r in shown)

    # P2-22：官方均分展示改——86% 落在 4.4-4.6 无区分度，加同级中位数参照。
    # 按级别算中位数（仅用有分车系），供模板显示星级 + 偏离方向。
    from statistics import median as _median
    level_scores: dict[str, list[float]] = {}
    for r in rows:
        if r["score"] is not None:
            level_scores.setdefault(r["level"], []).append(r["score"])
    level_medians = {lv: round(_median(sc), 2) for lv, sc in level_scores.items() if sc}
    for r in shown:
        r["level_median"] = level_medians.get(r["level"])

    return _templates.TemplateResponse(request, "dash_koubei.html", {
        "request": request,
        "rows": shown,
        "levels": levels,
        "q": q or "",
        "level": level or "",
        "price": price or "",
        "sort": sort,
        "sort_urls": sort_urls,
        "filtered": bool(level or price or ql or price_min is not None or price_max is not None),
        # P3#35：价格解析失败的车系数（「未知价格」桶的规模，顶部如实披露）
        "unknown_price_n": sum(1 for r in rows if r["pmin"] is None),
        "overall": {
            "series_n": len(shown), "reviews": total_reviews, "tags": tag_total,
            "coverage": round(total_tagged / total_taggable, 4) if total_taggable else 0.0,
            "tagged": total_tagged, "taggable": total_taggable,
            "max_fetched": max((r["last_fetched"] for r in rows), default="-"),
        },
        "quality": quality,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@router.get("/config")
async def config_dashboard(request: Request, series_id: str | None = None,
                           compare: str | None = None, trim: str | None = None):
    """配置看板：单车系（版型+参数）/ 多车系（2-6 个）差异对比 / 版型级对比
    （trim=mid:spec,…，2-6 对；load=1 允许空 spec_id 自动补首个版型；
    差价口径已下沉 /config/compare-valued 后端唯一实现，本视图不再计价）。"""
    from src.tools.config import get_trims, compare_configs
    from src.api.dashboard_data import (compare_trims_from_snapshots,
                                        get_config_snapshot, list_config_snapshots)

    # 选择器从 config_snapshots 快照表取（specs/dashboards v5 BREAKING）：
    # 扩到 244 系（有快照的车系），不再依赖口碑库 SeriesSummary。
    snapshots_list = list_config_snapshots()
    selector = sorted([{"id": x["id"], "name": x["name"]} for x in snapshots_list],
                      key=lambda r: r["name"])
    sel_names = {x["id"]: x["name"] for x in selector}
    snap_by_id = {x["id"]: x for x in snapshots_list}

    compare_ids = [c for c in (compare or "").split(",") if c][:4] if compare else []
    compare_ids = [c for c in compare_ids if c in sel_names or c.isdigit()]

    trims, cmp_result, err, elapsed = None, None, None, 0.0

    # 版型级对比分支（在 cmp/详情分支之前）：trim 模式下不重复拉单车系详情。
    trim_view, trim_select, trim_options = None, None, {}
    auto_fill = request.query_params.get("load") == "1"
    pairs = []
    for part in (trim or "").split(","):
        if ":" in part:
            m, sp = part.split(":", 1)
            if m in sel_names and (sp or auto_fill):
                pairs.append((m, sp))
    if len(pairs) >= 2:
        pairs = pairs[:8]
        mids_u = list(dict.fromkeys(m for m, _ in pairs))
        # 版型数据本请求只取一遍：auto_fill 补空 spec / compare_trims 列头 / 下拉共用。
        # get_trims 现状内部全兜不抛，try 是防御（未来改动破坏该不变式时 err 面板而非 500）
        try:
            opts = await asyncio.gather(*[get_trims(m) for m in mids_u])
        except Exception as e:
            err = str(e)
            opts = None
        if opts is not None:
            trims_by_mid = dict(zip(mids_u, opts))
            if auto_fill:  # 空 spec_id 自动补版型：同车型多列按顺位取互不相同的版型
                taken: dict[str, set[str]] = {}
                filled = []
                for m, sp in pairs:
                    if sp:
                        filled.append((m, sp))
                        continue
                    trims_l = [str(t.get("spec_id") or "") for t in
                               (trims_by_mid.get(m) or {}).get("trims", [])
                               if t.get("spec_id") is not None]
                    cand = next((t for t in trims_l
                                 if t not in taken.setdefault(m, set())), "")
                    if cand:
                        taken[m].add(cand)
                    filled.append((m, cand))
                pairs = [p for p in filled if p[1]]
                if len(mids_u) == 1 and len(pairs) < 2:
                    # 单车型对比但在售版型不足 2 个：明确提示，不渲染空对比（spec）
                    err = (f"{sel_names.get(mids_u[0], mids_u[0])} 仅 1 个在售版型，"
                           "无法进行版型对比")
                    pairs = []
            if pairs:  # 版型不足被清空 → 不再进对比/下拉（err 已说明，别触对比）
                # trim 模式 cfgs 从快照取（specs/dashboards v5）：预取各 mid 快照，
                # 未采集的 mid 不进 snapshots_by_mid → compare_trims_from_snapshots
                # 会标 cfg_failed（不编造配置）。
                snapshots_by_mid = {}
                for mid in mids_u:
                    snap = get_config_snapshot(mid)
                    if not snap.get("not_collected"):
                        snapshots_by_mid[mid] = snap
                t0 = datetime.now()
                try:
                    # 配置赋值口径改造：fold_prices 折价层已删——差价口径唯一实现在
                    # /config/compare-valued（value_diff.compute_value_diff）。
                    # 本视图保留差异行结构（compare_trims），模板仅消费 cfg_failed 守卫。
                    trim_view = await compare_trims_from_snapshots(
                        pairs, snapshots_by_mid, trims_by_mid=trims_by_mid)
                except Exception as e:
                    err = str(e)
                elapsed = (datetime.now() - t0).total_seconds()
                trim_options = {m: (t.get("trims") or []) for m, t in trims_by_mid.items()}
                trim_select = {"pairs": [{"model_id": m, "spec_id": sp} for m, sp in pairs]}

    if not trim_select:  # trim 模式已出对比表，跳过详情/车系级对比取数
        try:
            t0 = datetime.now()
            if len(compare_ids) >= 2:
                cmp_result = await compare_configs(compare_ids)
            elif series_id:
                # P2#24：不再默认选字典序第一个车系——未选 series_id 时模板渲染引导面板
                trims = await get_trims(series_id)  # get_config 已无消费点（v4 删罗列区）
            elapsed = (datetime.now() - t0).total_seconds()
        except Exception as e:
            err = str(e)

    # 对比数据整形：差异值是"分版本 dict"（spec名→值，两系版本混在一起）——
    # 按 spec 名归属车系（get_trims 的版本名），每系聚合成取值集合，只保留两系集合确有差异的行。
    cmp_view = None
    if cmp_result and cmp_result.get("model_names"):
        names = cmp_result["model_names"]  # {mid: 车系名}
        mids = list(names.keys())
        name_to_mid: dict[str, str] = {}
        try:
            trims_maps = await asyncio.gather(*[get_trims(m) for m in mids])
            for mid, t in zip(mids, trims_maps):
                for item in t.get("trims", []):
                    if item.get("name"):
                        name_to_mid[item["name"]] = mid
        except Exception:
            pass

        def _fmt(vs: set) -> str:
            if not vs:
                return "-"
            s = " / ".join(sorted(vs))
            return s if len(s) <= 48 else s[:45] + "…"

        cats, skipped = [], 0
        for cat, params in (cmp_result.get("differences") or {}).items():
            rows_out = []
            for k, vals in params.items():
                by_mid = {m: set() for m in mids}
                for sname, v in vals.items():
                    m = name_to_mid.get(sname)
                    if m in by_mid and v not in (None, ""):
                        by_mid[m].add(_fmt_value_for_cmp(v))
                sets = [by_mid[m] for m in mids]
                if len({frozenset(x) for x in sets}) <= 1:
                    skipped += 1  # 系内版本有差异、但两系取值集合相同 → 非跨系差异
                    continue
                rows_out.append({"param": k, "vals": [_fmt(s) for s in sets]})
            if rows_out:
                rows_out.sort(key=lambda r: r["param"])
                cats.append({"name": cat, "rows": rows_out})
        cats.sort(key=lambda c: -len(c["rows"]))
        # P1-9/P2-26：扫差异行参数名+值丢字（cmp 走 live API，残缺同源）。
        from src.api.dashboard_data import _detect_font_corruption
        _cmp_pseudo = {c["name"]: {r["param"]: " ".join(r["vals"]) for r in c["rows"]}
                       for c in cats}
        _cmp_fc = _detect_font_corruption(_cmp_pseudo)
        cmp_view = {
            "models": [{"id": m, "name": n} for m, n in names.items()],
            "cats": cats[:10], "skipped": skipped,
            "total_cats": len(cats),
            "source": cmp_result.get("data_source", "-"),
            "font_corrupted_n": _cmp_fc["n"],
        }

    # 快照 fetched_at：展示当前查看车系的快照新鲜度（非全局 max，否则脚注误导）。
    # 当前车系优先级：trim 模式首个 mid > 首个 compare_id > series_id；均无则空（模板显"—"）
    current_sid = None
    if trim_select and trim_select.get("pairs"):
        current_sid = trim_select["pairs"][0].get("model_id")
    elif compare_ids:
        current_sid = compare_ids[0]
    elif series_id:
        current_sid = series_id
    snap_fetched_at = (snap_by_id.get(current_sid, {}) or {}).get("fetched_at") or ""

    # config-dashboard-redesign Task 0.2：四 Tab 已删，横表为唯一主入口，不再传 tab
    ctx = {
        "request": request,
        "selector": selector,
        "sel_names": sel_names,
        "series_id": series_id,
        "series_name": sel_names.get(series_id, series_id or "-"),
        "trims": (trims or {}).get("trims", []),
        "trim_count": (trims or {}).get("count", 0),
        "trims_source": (trims or {}).get("data_source", "-"),
        "cmp": cmp_view,
        "compare_ids": compare_ids,
        "trim_view": trim_view,
        "trim_select": trim_select,
        "trim_options": trim_options,
        "snap_fetched_at": snap_fetched_at,
        "elapsed": round(elapsed, 1),
        "err": err,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return _templates.TemplateResponse(request, "dash_config.html", ctx)


@router.get("/koubei/series/{model_id}")
def koubei_series(request: Request, model_id: str, spec: str | None = None,
                  prov: str | None = None, tag: str | None = None,
                  kw: str | None = None, page: int = 1,
                  year: str | None = None):
    """单车系口碑下钻页（specs/dashboards v5）：多维筛选+诊断+同级分位+原文流。
    原文流筛选参数进 URL（年款同时作用于原文流，与多维筛选命中数一致）。
    同步 handler（线程池）。"""
    from src.api.dashboard_data import review_stream, series_drilldown, series_facts, cross_pivot
    from src.api.dashboard_data import tag_distribution
    from src.insights.compute_insights import diagnose, peer_percentile
    d = series_drilldown(model_id)
    if not d.get("not_collected"):
        d["facts"] = series_facts(model_id)
        d["stream"] = review_stream(model_id, spec=spec, prov=prov, tag=tag,
                                    kw=kw, page=page, year=year)
        d["stream_q"] = {"spec": spec or "", "prov": prov or "", "tag": tag or "",
                         "kw": kw or "", "year": year or ""}
        # v5 洞察数据
        d["pivot"] = cross_pivot(model_id, year=year, spec=spec, prov=prov, kw=kw, limit=100)
        # P0#1/P0-7 截断披露：diagnose 基于 pivot 随机抽样的 100 条子集，UI 必须明示非全量
        # dashboard-v12 Task 1.2：抽样上限 200→100（AI 总结口径收敛）
        d["pivot_truncated"] = d["pivot"].get("truncated", False)
        d["pivot_n"] = d["pivot"].get("n", 0)
        d["pivot_limit"] = 100  # cross_pivot 抽样上限（与 dash_series.html 披露口径一致）
        # diagnose 基于交叉透视筛出的原话子集计算（specs：三维筛选联动，页面各处 n 一致）
        d["diagnose"] = diagnose(model_id, reviews=d["pivot"].get("reviews"))
        # dashboard-v10 Task 5.2 B3：标签分布跟随当前筛选（全量命中集 review_id）
        # round3-fix R2：标签分布改用全量命中集（pivot.all_rids），不再用抽样 100 条，
        # 避免大车系标签分布被抽样稀释。pivot 仍用 limit=100 给 AI 总结。
        all_rids = d["pivot"].get("all_rids", [])
        d["tag_dist"] = tag_distribution(model_id, review_ids=all_rids)
        d["peer"] = peer_percentile(model_id)
        # P2#17 摘要卡素材：情绪比取诊断画像；续航中位数分组时取样本量最大的主组
        diag = d["diagnose"]
        sent = None if diag.get("not_collected") else (diag.get("profile") or {}).get("sentiment")
        range_label = None
        facts = d.get("facts") or {}
        if facts.get("range_by_group"):
            g_name, m = max(facts["range_by_group"].items(), key=lambda kv: kv[1]["n"])
            range_label = f"{m['median']} km（{g_name}主组，n={m['n']}）"
        elif facts.get("range"):
            range_label = ("{median} {unit}（n={n}）"
                           .format(**facts["range"]))
        d["summary"] = {"sentiment": sent, "range_label": range_label}
        # 口碑周更 change：数据时点戳（最近成功周更日期；无记录 None 不渲染）
        d["koubei_last_run"] = _koubei_last_run_label()
        # dashboard-v11 Task 2.2：维度短板对照（注入 peer.dim_compare，additive）
        from src.api.dashboard_data import peer_dim_compare
        dim_cmp = peer_dim_compare(model_id)
        if dim_cmp.get("dims"):
            d["peer"]["dim_compare"] = dim_cmp["dims"]
        # 口碑对比候选：**全库有口碑标签的车系**（不再限于同级）。
        # 原实现要求 `d["peer"]["peer_level"]` 存在且只列同级别车系，导致
        # 无 level_name 的车系（如风云T11/T9L、QQ3 EV 等新采集车系）整块降级为
        # 「暂无同级竞品数据」，且即便有级别也无法跨级别对比。按需求放开为任意车型互比。
        from src.models.orm import SeriesSummary as _SS, ReviewTag as _RT
        from src.storage.db import session_scope as _ss
        with _ss() as _s:
            _tagged = {r[0] for r in _s.query(_RT.model_id).distinct().all()}
            _opts = (_s.query(_SS.series_id, _SS.series_name)
                     .filter(_SS.series_id.in_(_tagged))
                     .order_by(_SS.series_name).all()) if _tagged else []
        # K-11：缺名回退为中文占位（原 `r[1] or r[0]` 会把数字 ID 泄露到竞品下拉）
        # 当前车系置首位：模板 `selected if o.id == d.model_id` 才会生效，
        # 使首屏即「本车 vs 另选一车」，无需用户先手动选 A 车
        d["peer_options"] = (
            [{"id": model_id, "name": d.get("series_name") or "未知车系"}]
            + [{"id": r[0], "name": r[1] or "未知车系"} for r in _opts
               if r[0] != model_id])
    return _templates.TemplateResponse(request, "dash_series.html",
                                       {"request": request, "d": d})


@router.get("/koubei/peer-compare-v2")
def koubei_peer_compare_v2(a_mid: str, a_spec: str = "",
                           b_mid: str = "", b_spec: str = "",
                           granularity: str = "year"):
    """竞品口碑对比 v2 JSON（data-layer-tag-system 阶段3）。

    双车 + 年款/版型锁定 + 样本守卫 + 可比性体检 + 分类层兜底。
    返回 {ok, compare:{sample_guard, comparability, category_compare, tag_details, names}}。
    """
    if not a_mid or not b_mid:
        return JSONResponse({"ok": False, "error": "需提供 a_mid 与 b_mid"},
                            status_code=400)
    from src.api.dashboard_data import peer_tag_compare_v2
    out = peer_tag_compare_v2(a_mid, a_spec, b_mid, b_spec, granularity)
    if out.get("error"):
        return JSONResponse({"ok": False, "error": out["error"]}, status_code=400)
    return JSONResponse({"ok": True, "compare": out})


@router.get("/koubei/series/{model_id}/data")
def koubei_series_data(model_id: str, spec: str | None = None, tag: str | None = None,
                       kw: str | None = None, page: int = 1, year: str | None = None):
    """单车系口碑下钻 JSON（agent 工具通道，2026-10-08 迁移适配）。

    与 /koubei/series/{id} HTML 页同数据层（dashboard_data），但不含
    diagnose/pivot/peer 等重计算（那是看板 AI 总结的事，agent 不需要）。
    供 Prism extension 四工具消费：get_model_detail / get_review_analysis
    （tag_dist）/ search_reviews（kw 原文流）/ get_dimension_reviews（tag 原文流）。
    """
    from src.api.dashboard_data import review_stream, series_drilldown, series_facts, tag_distribution
    d = series_drilldown(model_id)
    if d.get("not_collected"):
        return JSONResponse({"ok": False, "error": "该车型未采集口碑"}, status_code=404)
    d["facts"] = series_facts(model_id)
    d["tag_dist"] = tag_distribution(model_id)
    d["stream"] = review_stream(model_id, spec=spec, tag=tag, kw=kw, page=page, year=year)
    d["stream_q"] = {"spec": spec or "", "tag": tag or "", "kw": kw or "", "year": year or ""}
    return JSONResponse({"ok": True, **d})


@router.get("/koubei/last-run")
def koubei_last_run():
    """最近一次成功周更时点（口碑周更增量采集 change）。只读。

    看板「口碑更新至」数据源；表不存在（旧库未跑过周更）返回 ok:false 而非 500。
    finished_at 为 naive UTC（func.now()），此处转 Asia/Shanghai 展示。"""
    from src.models.orm import CollectionRun
    try:
        with session_scope() as s:
            row = (s.query(CollectionRun)
                   .filter(CollectionRun.mode == "weekly",
                           CollectionRun.status == "success",
                           CollectionRun.finished_at.isnot(None))
                   .order_by(CollectionRun.finished_at.desc()).first())
    except Exception:
        return JSONResponse({"ok": False, "error": "collection_runs 未就绪（从未跑过周更）"})
    if not row:
        return JSONResponse({"ok": False, "error": "尚无成功周更记录"})
    from datetime import timezone, timedelta
    cn = timezone(timedelta(hours=8))
    fin = row.finished_at.replace(tzinfo=timezone.utc).astimezone(cn) if row.finished_at else None
    return JSONResponse({"ok": True, "last_run": {
        "finished_at": fin.strftime("%Y-%m-%d %H:%M") if fin else None,
        "finished_at_iso": fin.isoformat() if fin else None,
        "new_reviews": row.new_reviews,
        "series_done": row.series_done,
        "series_budget_capped": row.series_budget_capped,
        "run_id": row.run_id,
    }})


def _koubei_last_run_label() -> str | None:
    """下钻页模板用：『口碑更新至 X 月 X 日』文案（无记录返回 None 不渲染）。"""
    from src.models.orm import CollectionRun
    try:
        with session_scope() as s:
            row = (s.query(CollectionRun)
                   .filter(CollectionRun.mode == "weekly",
                           CollectionRun.status == "success",
                           CollectionRun.finished_at.isnot(None))
                   .order_by(CollectionRun.finished_at.desc()).first())
    except Exception:
        return None
    if not row or not row.finished_at:
        return None
    from datetime import timezone, timedelta
    cn = timezone(timedelta(hours=8))
    fin = row.finished_at.replace(tzinfo=timezone.utc).astimezone(cn)
    return fin.strftime("%m 月 %d 日")


@router.get("/koubei/series/{model_id}/spec-facets")
def koubei_spec_facets(model_id: str):
    """车系版型/年款分面 JSON（data-layer-tag-system 阶段3）。
    供竞品 v2 picker 的 trim 下拉动态加载。未采集 → 404。"""
    from src.api.dashboard_data import spec_facets
    out = spec_facets(model_id)
    if out.get("not_collected"):
        return JSONResponse({"ok": False, "error": "该车型未采集口碑"},
                            status_code=404)
    return JSONResponse({"ok": True, "facets": out})


@router.get("/koubei/series/{model_id}/export")
def koubei_series_export(model_id: str, spec: str | None = None,
                         prov: str | None = None, tag: str | None = None,
                         kw: str | None = None, year: str | None = None):
    """导出当前筛选口碑 CSV（P2#28）：与原文流同一筛选口径，输出全量命中行
    （不分页）。列为 review_id/post_date/spec/city/best/worst/buy_price；
    best/worst 全文不截断。未采集车型 404。"""
    import csv
    import io
    from fastapi.responses import Response
    from src.api.dashboard_data import export_stream
    out = export_stream(model_id, spec=spec, prov=prov, tag=tag, kw=kw, year=year)
    if out.get("not_collected"):
        return JSONResponse({"ok": False, "error": "该车型未采集口碑"}, status_code=404)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["review_id", "post_date", "spec", "city", "best", "worst", "buy_price"])
    for r in out["rows"]:
        w.writerow([r["review_id"], r["post_date"], r["spec"], r["city"],
                    r["best"], r["worst"], r["buy_price"]])
    # BOM：Excel 打开 UTF-8 CSV 中文不乱码
    return Response(content=chr(0xFEFF) + buf.getvalue(),
                    media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="koubei_{model_id}.csv"'})


@router.post("/koubei/series/{model_id}/insight")
async def koubei_series_insight(request: Request, model_id: str):
    """AI 总结按需触发端点（specs/dashboards v5：不自动跑，用户显式触发）。
    body: {year, spec, prov, kw}（筛选条件）。限流：每 IP 10 次/分钟（P3#32）。"""
    # 限流在最前：无论后续命中缓存/404/400，都计一次请求（防脚本循环刷）
    if _rate_limited(request.client.host if request.client else None):
        return JSONResponse(
            {"ok": False, "error": "请求过于频繁（每分钟最多 10 次），请稍后再试"},
            status_code=429)
    from src.api.dashboard_data import cross_pivot
    from src.insights.compute_insights import ai_summarize

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "请求体必须是 JSON"}, status_code=400)
    filt = {"year": str(body.get("year") or ""), "spec": str(body.get("spec") or ""),
            "prov": str(body.get("prov") or ""), "kw": str(body.get("kw") or "")}
    pivot = cross_pivot(model_id, year=filt["year"] or None, spec=filt["spec"] or None,
                        prov=filt["prov"] or None, kw=filt["kw"] or None, limit=100)
    if pivot.get("not_collected"):
        return JSONResponse({"ok": False, "error": "该车型未采集口碑"}, status_code=404)
    out = await ai_summarize(model_id, filt, pivot["reviews"])
    if out.get("status") == "error":
        return JSONResponse({"ok": False, "error": out.get("error")}, status_code=502)
    # status=="insufficient_citations" 是可恢复的软失败：透传给前端展示
    return {"ok": True, "insight": out, "n": pivot["n"]}


@router.post("/config/refresh-snapshot/{series_id}")
async def config_refresh_snapshot(request: Request, series_id: str):
    """手动刷新单系配置快照（collector 式写库，specs/dashboards v5）。
    拉之家实时配置 → upsert config_snapshots。看板只读，刷新走此端点。"""
    # dashboard-v10 Task 1.2：写端点限流（防脚本循环触发之家 API）
    if _rate_limited(request.client.host if request.client else None, _WRITE_RATE):
        return JSONResponse({"ok": False, "error": "请求过于频繁，请稍后再试"},
                            status_code=429)
    import time
    from src.api.autohome_api import get_autohome_api
    from src.models.orm import upsert_config_snapshot
    try:
        api = await get_autohome_api()
        cfg = await api.get_full_config(series_id)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=502)
    # 拒空 categories：缺失或空都视为拉取失败（避免存空快照诱导编造）
    if not cfg.get("categories"):
        return JSONResponse({"ok": False, "error": cfg.get("error", "拉取失败")}, status_code=502)
    fetched_at = time.strftime("%Y-%m-%d %H:%M:%S")
    # 补元数据：get_full_config 不回传 name/level，单独取 get_series_info（已缓存，
    # get_full_config 内部已调过）。失败不阻断写库——categories 已是真实数据。
    try:
        info = await api.get_series_info(series_id)
    except Exception:
        info = {}
    series_name = info.get("name") or None
    level = info.get("level") or None
    # upsert 走共用 helper（/simplify 归一）：None 字段不覆盖既有值。
    data = {"series_name": series_name, "level": level,
            "categories": cfg.get("categories", {}), "fetched_at": fetched_at}
    # dashboard-v10 Task 1.1：存 decode_hit_rate 供 selfcheck 查
    dhr = cfg.get("decode_hit_rate")
    if dhr is not None:
        data["decode_hit_rate"] = dhr
    with session_scope() as s:
        upsert_config_snapshot(s, series_id, data)
    return {"ok": True, "series_id": series_id, "fetched_at": fetched_at}


# ---------- Task 4: 阶梯连线对比路由（specs/dashboards v5） ----------

def _config_selector() -> list[dict]:
    """各 Tab 共用的车系选择器（id/name，按名排序）。
    用户只知道车名不知 series_id → 下拉选择后 JS 跳转到带 series_id 的 Tab URL。"""
    from src.api.dashboard_data import list_config_snapshots
    snapshots_list = list_config_snapshots()
    return sorted([{"id": x["id"], "name": x["name"]} for x in snapshots_list],
                  key=lambda r: r["name"])


@router.get("/config/trims/{series_id}")
async def config_get_trims(series_id: str):
    """版型列表 JSON（specs/dashboards v5）：阶梯/作战室 Tab 选版型用。
    用户只知道版型名 → 前端拉此端点渲染 <select>，option.value=spec_id。
    复用 src.tools.config.get_trims（实时之家 API + 缓存 + fallback）。
    P2#29：附带 is_main 标注（sales_trim 主销版型，无销量数据时全 False，
    前端回退第一个版型）+ main_spec_id，供作战室"从该车带入"。"""
    from src.api.dashboard_data import main_trim_spec_id
    from src.tools.config import get_trims
    trims = await get_trims(series_id)
    trim_list = trims.get("trims", [])
    main_sid = main_trim_spec_id(series_id, trim_list)
    for t in trim_list:
        t["is_main"] = bool(main_sid) and str(t.get("spec_id") or "") == main_sid
    return {"trims": trim_list, "count": trims.get("count", 0),
            "main_spec_id": main_sid}


# ---------- Task 6: 配置作战室 what-if 路由（specs/config-workshop v5） ----------

@router.get("/config/concept-configs")
def config_concept_configs():
    """返回 concept_configs.json（61 项概念配置清单），供前端渲染 61 个档位选择器。
    看板作战室 Tab 加载时拉此 JSON 动态生成下拉。"""
    from src.insights.concept_config import _load_configs
    return {"configs": _load_configs()}


@router.get("/config/compare-horizontal")
async def config_compare_horizontal(request: Request, sel: list[str] = Query(default=[])):
    """之家式横向对比表 JSON（specs/config-dashboard-redesign）。
    sel 格式：series_id:spec_id，2-6 个。
    供 ③Tab 选完版型后 fetch 刷新。"""
    from src.api.dashboard_data import spec_compare_horizontal, get_config_snapshot
    from src.tools.config import get_trims
    selections = []
    for s in sel:
        if ":" not in s:
            continue
        mid, sid = s.split(":", 1)
        selections.append((mid, sid))
    if not (2 <= len(selections) <= 6):  # dashboards-design-system 列数 6（原 8）
        return {"error": "请提供 2-6 个 series:spec 组合"}
    snapshots = {mid: get_config_snapshot(mid) for mid, _ in selections}
    if any(s.get("not_collected") for s in snapshots.values()):
        return {"error": "部分车系未采集快照",
                "missing": [mid for mid, s in snapshots.items() if s.get("not_collected")]}
    # config-dashboard-redesign：调 get_trims 填 trim_name（版型名，非 spec_id）
    trims_by_mid: dict[str, dict[str, str]] = {}
    for mid in {mid for mid, _ in selections}:
        try:
            t = await get_trims(mid)
            trims_by_mid[mid] = {t2["spec_id"]: t2["name"] for t2 in t.get("trims", [])}
        except Exception:
            trims_by_mid[mid] = {}
    return await spec_compare_horizontal(selections, snapshots, trims_by_mid=trims_by_mid)


# ---------- 配置赋值口径改造：差价后端唯一实现（design D3） ----------

@router.get("/config/compare-valued")
async def config_compare_valued_get(request: Request, sel: list[str] = Query(default=[])):
    return await _compare_valued_impl(request, sel)


@router.post("/config/compare-valued")
async def config_compare_valued_post(request: Request, sel: list[str] = Query(default=[])):
    """POST 带 {"manual_prices": {param: 元}}：手填覆盖优先（内存态，不落库）。"""
    return await _compare_valued_impl(request, sel)


async def _compare_valued_impl(request: Request, sel: list[str]) -> dict:
    """配置差价对比：spec_compare_horizontal 同源取数 + value_diff 差价引擎
    （后端唯一实现，原前端 _computeDiffCells 已删）+ get_trims 指导价（拉平价）。
    get_trims 失败仅降级指导价/拉平价，逐项差价不受阻；缺规则项拒绝汇总（不脑补）。
    幂等只读，不落任何库。"""
    from src.api.dashboard_data import get_config_snapshot, parse_wan, spec_compare_horizontal
    from src.insights.value_diff import compute_value_diff, load_pricing_table

    body: dict = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
    raw_manual = body.get("manual_prices")
    manual_prices: dict[str, float] = {}
    import math as _math
    if isinstance(raw_manual, dict):
        for k, v in raw_manual.items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue  # 非法手填价丢弃（前端已校验，此处是 API 防线）
            if fv >= 0 and _math.isfinite(fv):  # isfinite 挡 Infinity（审查 P0-1）
                manual_prices[str(k)] = fv

    selections = []
    for s in sel:
        if ":" not in s:
            continue
        mid, sid = s.split(":", 1)
        selections.append((mid, sid))
    if not (2 <= len(selections) <= 6):
        return {"error": "请提供 2-6 个 series:spec 组合"}
    snapshots = {mid: get_config_snapshot(mid) for mid, _ in selections}
    if any(s.get("not_collected") for s in snapshots.values()):
        return {"error": "部分车系未采集快照",
                "missing": [mid for mid, s in snapshots.items() if s.get("not_collected")]}

    # 版型名 + 指导价（活接口，失败降级：guide_prices=None → 拉平价不出，差价照常）
    trims_by_mid: dict[str, dict[str, str]] = {}
    guide_prices: dict[str, float | None] | None = None
    try:
        from src.tools.config import get_trims
        mids_u = list(dict.fromkeys(mid for mid, _ in selections))
        opts = await asyncio.gather(*[get_trims(m) for m in mids_u])
        msrp: dict[tuple[str, str], float | None] = {}
        for mid, t in zip(mids_u, opts):
            trims_by_mid[mid] = {str(t2.get("spec_id")): (t2.get("name") or "")
                                 for t2 in t.get("trims", [])}
            for t2 in t.get("trims", []):
                msrp[(mid, str(t2.get("spec_id")))] = parse_wan(t2.get("price"))
        guide_prices = {f"{mid}:{sid}": msrp.get((mid, sid)) for mid, sid in selections}
    except Exception:
        guide_prices = None

    pricing = load_pricing_table()
    hc = await spec_compare_horizontal(selections, snapshots,
                                       trims_by_mid=trims_by_mid or None)
    diff = compute_value_diff(hc.get("rows") or [], pricing,
                              manual_prices=manual_prices)
    items = diff.get("items") or {}
    for row in hc.get("rows", []):
        it = items.get(str(row.get("id")))
        if it:
            row["verdict"] = it.get("verdict")
            row["amount"] = it.get("amount")
            row["unit_price"] = it.get("unit_price")
            row["price_source"] = it.get("price_source")
            row["basis"] = it.get("basis")
            row["diff_note"] = it.get("note")

    # 拉平指导价优势 = 配置优势 + (基准指导价 − 对方指导价) × 10000（design D3；
    # 与 carkit「自品视角」公式经视角对齐后同式）。2 列且未 blocked 且双方指导价齐才出。
    flat_adv, flat_adv_reason = None, ""
    if len(selections) == 2:
        if diff.get("blocked"):
            flat_adv_reason = "存在缺规则项，差价汇总已拒绝"
        elif not guide_prices:
            flat_adv_reason = "指导价不可得（版型接口失败）"
        else:
            ca = diff.get("config_adv")
            if ca is None:
                # "差价值不可用"不得被 or 0 吞成 0 元（审查 P1-1）
                flat_adv_reason = "配置差价不可用（无可比数据）"
            else:
                (m1, s1), (m2, s2) = selections
                p1 = guide_prices.get(f"{m1}:{s1}")
                p2 = guide_prices.get(f"{m2}:{s2}")
                if p1 is None or p2 is None:
                    flat_adv_reason = "指导价不可得"
                else:
                    flat_adv = round(ca + (p1 - p2) * 10000, 2)
    diff["flat_adv"] = flat_adv
    diff["flat_adv_reason"] = flat_adv_reason

    as_of = {"pricing_table": pricing.get("version"),
             "snapshots_fetched_at": {mid: s.get("fetched_at")
                                      for mid, s in snapshots.items()}}
    return {**hc, "diff": diff, "guide_prices": guide_prices, "as_of": as_of}
