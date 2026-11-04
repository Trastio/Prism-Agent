"""看板下钻数据层（specs/dashboards）：只读聚合，不写库、不触发采集/打标。

- series_drilldown: 单车型口碑下钻（总览/版型/省份/维度双层）
- compare_trims / _trim_diff_rows: 版型级配置对比（2-4 个车型×版型，仅差异成行）
- 配置差价：已迁 src/insights/value_diff.py（compute_value_diff，配置赋值口径改造，
  端点 /config/compare-valued；原 fold_prices presence-only 折价层已删）
"""
from __future__ import annotations

import random
import re
import statistics
from collections import defaultdict

from sqlalchemy import func, not_, or_, select

from src.storage.db import session_scope
from src.models.orm import OwnerReview, ReviewTag, SeriesSummary, ConfigSnapshot
from src.tools._geo import province_of, display_city
from src.tools.reviews import _tag_coverage_for_series
from src.tools.reviews import COVERAGE_OK, COVERAGE_MIN
from src.api.option_prices import is_finite_number
from src.insights.normalize_filter import extract_year, filter_hash, _UNKNOWN_YEAR

TOP_N = 6
_SPEC_BLANK = "未填写版型"


def _usable_dim_val(dv) -> bool:
    """维度值守卫（Task-4/5 审查加固项 6.8）：bool（int 子类）/ NaN / inf
    不进维度聚合（手改库/上游坏数据防线）。数值口径与价格过滤同源
    （is_finite_number），别处不要另抄一份。"""
    return is_finite_number(dv)


def _parse_first_float(raw, lo: float, hi: float) -> float | None:
    """取字符串第一个数值，越界/找不到/非有限数返回 None（宁可无样本，不造均值）。"""
    if not isinstance(raw, str):
        return None
    m = re.search(r"\d+(?:\.\d+)?", raw)
    if not m:
        return None
    v = float(m.group())
    return v if lo < v < hi and is_finite_number(v) else None


def parse_wan(raw) -> float | None:
    """'10.98万' → 10.98（万元）。区间 (0, 1000) 万 sanity。"""
    return _parse_first_float(raw, 0, 1000)


def parse_km(raw) -> float | None:
    """'330km' → 330。区间 (0, 3000) km sanity。"""
    return _parse_first_float(raw, 0, 3000)


def parse_kwh(raw) -> float | None:
    """'15.5kWh' → 15.5。区间 (0, 100) sanity。"""
    return _parse_first_float(raw, 0, 100)


def _power_group(spec_name: str | None) -> str:
    """按 spec_name 判动力形式分组（P1#9，防不同动力形式混池算中位数）：
    DM-i/DM-p → 插混；EV/纯电 → 纯电；其余/缺失 → 其他。"""
    s = spec_name or ""
    if "DM-i" in s or "DM-p" in s:
        return "插混"
    if "EV" in s or "纯电" in s:
        return "纯电"
    return "其他"


def series_facts(model_id: str) -> dict:
    """续航事实统计素材（specs/dashboards v8：Task7 删事实统计面板后仅 range
    路径被路由消费——拼 range_label）。每项自带 n；解析失败条目不进分母；
    全库无该字段的车系不产出该键（不渲染 n=0 的空统计）。
    P1#9：>1 个动力形式组（按 spec_name 判 插混/纯电/其他）时额外产出
    range_by_group 分组中位数（同系 DM-i 112km 级与 EV 635km 级混池取中位数
    会得出两头不是的值）；flat 全池 range 键保留向后兼容。"""
    with session_scope() as s:
        rows = s.query(OwnerReview.exinfo, OwnerReview.spec_name).filter(
            OwnerReview.model_id == model_id).all()
    facts: dict = {}
    rng = sorted(v for v in (parse_km((r[0] or {}).get("夏季满电续航"))
                             for r in rows if isinstance(r[0], dict)) if v is not None)
    if rng:
        facts["range"] = {"median": round(statistics.median(rng), 1), "n": len(rng), "unit": "km"}

    # P1#9：按动力形式分组的中位数（>1 组有值才产出，避免单组冗余）
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[_power_group(r[1])].append(r)

    def _range_stats(rs):
        vals = sorted(v for v in (parse_km((r[0] or {}).get("夏季满电续航"))
                                  for r in rs if isinstance(r[0], dict)) if v is not None)
        if not vals:
            return None
        return {"median": round(statistics.median(vals), 1), "n": len(vals)}

    g = {name: _range_stats(rs) for name, rs in groups.items()}
    g = {k: v for k, v in g.items() if v is not None}
    if len(g) > 1:
        facts["range_by_group"] = g
    return facts


def _page_window(cur: int, total_pages: int) -> list:
    """分页页码窗口（P3#38）：1 … n-1 n n+1 … N（None = 省略号）。
    ≤7 页全列不省略；cur 超出范围时窗口仍收敛到合法页码集。"""
    if total_pages <= 7:
        return list(range(1, total_pages + 1))
    keep = {p for p in (1, total_pages, cur - 1, cur, cur + 1) if 1 <= p <= total_pages}
    out: list = []
    prev = 0
    for p in sorted(keep):
        if prev and p - prev > 1:
            out.append(None)
        out.append(p)
        prev = p
    return out


def _contains(col, needle: str):
    """字面 LIKE 包含（%/_ 转义，防 URL 直传通配符注入）。"""
    esc = needle.replace("/", "//").replace("%", "/%").replace("_", "/_")
    return col.like(f"%{esc}%", escape="/")


def _stream_query(s, model_id: str, spec: str | None, prov: str | None,
                  tag: str | None, kw: str | None, year: str | None):
    """原文流共用筛选查询（P2#28 导出与页面流复用同一口径）。
    年款按 spec_name 字面包含"XXXX款"过滤（与 extract_year 正则取首个匹配
    同源；筛选下拉的选项本身来自 extract_year 分面，不会出现奇异值）。
    "未知年款"特殊口径（Task8 review）：= spec_name 无年款（None/空/不含
    "20XX款"），与 cross_pivot 的 extract_year=="未知年款" 完全同口径——否则
    透视命中 N 条而原文流/导出 0 条，页面三处 n 不一致。项目 SQLite 未注册
    REGEXP 函数，用 LIKE '20__款' 通配（_ 单字符）近似 (20\\d{2})款。"""
    q = s.query(OwnerReview.review_id, OwnerReview.spec_name, OwnerReview.city,
                OwnerReview.post_date, OwnerReview.best_review_text,
                OwnerReview.worst_review_text, OwnerReview.buy_price
                ).filter(OwnerReview.model_id == model_id)
    if year:
        if year == _UNKNOWN_YEAR:
            q = q.filter(or_(OwnerReview.spec_name.is_(None),
                             OwnerReview.spec_name == "",
                             not_(OwnerReview.spec_name.ilike("%20__款%"))))
        else:
            q = q.filter(_contains(OwnerReview.spec_name, year))
    if spec:
        if spec == _SPEC_BLANK:
            q = q.filter(or_(OwnerReview.spec_name.is_(None), OwnerReview.spec_name == ""))
        else:
            q = q.filter(OwnerReview.spec_name == spec)
    if prov:
        cities = {r[0] for r in s.query(OwnerReview.city).filter(
            OwnerReview.model_id == model_id,
            OwnerReview.city.isnot(None),
            OwnerReview.city != "").distinct().all()}
        q = q.filter(OwnerReview.city.in_([c for c in cities if province_of(c) == prov]))
    if tag:
        # EXISTS 语义而非 JOIN：review_tags 唯一索引是 (rid, tag, sentiment)
        # 三元组，同口碑同 tag 的 pro+con 两行会让 JOIN 重复计数（spec 审查）
        q = q.filter(OwnerReview.review_id.in_(
            select(ReviewTag.review_id).where(
                ReviewTag.review_id == OwnerReview.review_id,
                ReviewTag.tag_name == tag)))
    if kw:
        like = f"%{kw}%"
        q = q.filter(or_(OwnerReview.best_review_text.ilike(like),
                         OwnerReview.worst_review_text.ilike(like)))
    return q


def _fetch_full_texts(session, review_ids: list[str]) -> dict[str, tuple[str, str]]:
    """批量查 best_full_text/worst_full_text 新列（dashboards-tri-polish）。
    回退：新列空则由调用方用 best_review_text/worst_review_text 兜底。"""
    if not review_ids:
        return {}
    rows = session.query(
        OwnerReview.review_id, OwnerReview.best_full_text, OwnerReview.worst_full_text
    ).filter(OwnerReview.review_id.in_(review_ids)).all()
    return {r[0]: (r[1] or "", r[2] or "") for r in rows}


def review_stream(model_id: str, spec: str | None = None, prov: str | None = None,
                  tag: str | None = None, kw: str | None = None,
                  page: int = 1, size: int = 10, year: str | None = None) -> dict:
    """口碑原文流（证据层，specs/dashboards v4）：年款×版型×省份×标签×关键词筛选，
    post_date 倒序分页（size 上限 10，dashboards-design-system §04 原文佐证 10 条）。
    省份过滤按 province_of 归省口径（先取本车系城市集再筛）；标签过滤走相关子查询
    （EXISTS 语义）。P3#38：附带 total_pages + page_window（1 … n-1 n n+1 … N），
    供模板渲染页码。"""
    page, size = max(1, page), max(1, min(size, 10))
    with session_scope() as s:
        q = _stream_query(s, model_id, spec, prov, tag, kw, year)
        total = q.count()
        rows = q.order_by(OwnerReview.post_date.desc(),
                          OwnerReview.review_id.desc()
                          ).offset((page - 1) * size).limit(size).all()
        tags_by_rid: dict[str, list] = defaultdict(list)
        if rows:
            for rid, tname, senti in s.query(
                    ReviewTag.review_id, ReviewTag.tag_name, ReviewTag.sentiment
            ).filter(ReviewTag.review_id.in_([r[0] for r in rows]),
                     ReviewTag.sentiment.in_(("pro", "con"))
            ).order_by(ReviewTag.sentiment.desc(), ReviewTag.tag_name).all():
                tags_by_rid[rid].append({"name": tname, "senti": senti})
        # dashboards-tri-polish：best_full/worst_full 读新列（完整原文），回退原 best_review_text
        full_texts = _fetch_full_texts(s, [r[0] for r in rows])
    items = [{"review_id": r[0], "spec": r[1] or _SPEC_BLANK,
              "city": display_city(r[2]) or "-",
              "post_date": r[3] or "-", "best": (r[4] or "")[:100],
              "worst": (r[5] or "")[:100], "buy_price": r[6] or "-",
              "tags": tags_by_rid.get(r[0], []),
              # dashboards-tri-polish：完整原文供「查看全文」展开；新列空则回退 best_review_text
              "best_full": full_texts.get(r[0], (r[4] or ""))[0] or (r[4] or ""),
              "worst_full": full_texts.get(r[0], (r[5] or ""))[1] or (r[5] or "")} for r in rows]
    total_pages = (total - 1) // size + 1 if total else 1
    return {"rows": items, "total": total, "page": page, "size": size,
            "total_pages": total_pages, "page_window": _page_window(page, total_pages)}


def export_stream(model_id: str, spec: str | None = None, prov: str | None = None,
                  tag: str | None = None, kw: str | None = None,
                  year: str | None = None) -> dict:
    """口碑原文导出（P2#28）：与 review_stream 同一筛选口径，但不分页取全部命中行。
    best/worst 不截断（导出供离线分析，节选 100 字仅是页面展示约束）。
    库内无该 model_id 口碑返回 {"not_collected": True}。"""
    with session_scope() as s:
        rows = (_stream_query(s, model_id, spec, prov, tag, kw, year)
                .order_by(OwnerReview.post_date.desc(), OwnerReview.review_id.desc())
                .all())
        if not rows:
            # 与 series_drilldown 同守卫：无口碑 = 未采集（导出空 CSV 会伪装"0 条证据"）
            got = s.query(OwnerReview.review_id).filter(
                OwnerReview.model_id == model_id).limit(1).count()
            if not got:
                return {"not_collected": True, "model_id": model_id}
        # dashboards-tri-polish：best_full/worst_full 读新列（完整原文），回退原 best_review_text
        full_texts = _fetch_full_texts(s, [r[0] for r in rows])
    items = [{"review_id": r[0], "spec": r[1] or _SPEC_BLANK,
              "city": display_city(r[2]) or "-",
              "post_date": r[3] or "-", "best": r[4] or "", "worst": r[5] or "",
              "buy_price": r[6] or "-",
              # dashboards-tri-polish：附完整原文；新列空则回退 best_review_text
              "best_full": full_texts.get(r[0], (r[4] or ""))[0] or (r[4] or ""),
              "worst_full": full_texts.get(r[0], (r[5] or ""))[1] or (r[5] or "")} for r in rows]
    return {"rows": items, "total": len(items)}


def main_trim_spec_id(series_id: str, trims: list[dict]) -> str | None:
    """主销版型 spec_id（P2#29 作战室一键带入）：sales_trim 该系最新月
    is_main='是' 的版型 → 匹配到看板版型列表；无销量数据/版型名对不上 → None
    （前端回退第一个版型）。只读，不编造。

    fix-main-trim-spec-id（2026-10-07）双层修复：
    - L1 字段优先级：model_name 优先（version 是生命周期分类"小改款/换代"等
      非版型名，永远匹配不上看板 trim.name）。version 仅在 model_name 为空时 fallback。
    - L2 匹配链：MSRP 精确匹配优先（CAM msrp ↔ 之家 trim.price，元单位，容差<1元）
      → 多义/无命中进 token 消歧（_extract_trim_tokens 交集最大且唯一）
      → 仍多义/无命中返回 None（数据真实性硬底线，不猜）。
    - 主销行选择：同 (series,year,month) 多行 is_main='是' 时取 mix 最大者。

    P0-4 同家族根治（I-2）：snapshot series_name 经 _series_alias_names 得到匹配名，
    SalesTrim.series IN(names)（v7 单表化后退化为精确单名；非 LIKE，
    防"汉"串"汉L"）。限定最大年（最新批次），月份内用 _cam_month_key 排序。"""
    from src.models.orm import SalesTrim
    snap = get_config_snapshot(series_id)
    if snap.get("not_collected"):
        return None
    name = snap.get("series_name") or series_id
    with session_scope() as s:
        # P0-4：精确 IN（防 LIKE 串系；v7 单表化后退化为精确单名）
        names = _series_alias_names(s, name)
        # 限定最大年（最新批次）
        max_year = s.execute(
            select(func.max(SalesTrim.year)).where(
                SalesTrim.is_main == "是", SalesTrim.series.in_(names))
        ).scalar()
        if max_year is None:
            return None
        # 取最新月的所有 is_main 行（含 model_name/msrp/mix/version）
        rows = s.execute(
            select(SalesTrim.model_name, SalesTrim.msrp, SalesTrim.mix,
                   SalesTrim.version, SalesTrim.month, SalesTrim.year)
            .where(SalesTrim.is_main == "是", SalesTrim.series.in_(names),
                   SalesTrim.year == max_year)
        ).fetchall()
    if not rows:
        return None
    # 取最新月（rows 已按 max_year 过滤，月份内 _cam_month_key 排序）。
    # 用 _cam_month_key 分组而非原始字符串——"10月中"与"10月"映射同 key (10,0)，
    # 按字符串过滤会丢同 key 的另一月高 mix 行。
    latest_row = max(rows, key=lambda r: _cam_month_key(r[4]))
    latest_key = _cam_month_key(latest_row[4])
    # 同月（同 _cam_month_key）可能多行 is_main——取 mix 最大者作权威主销行
    same_month = [r for r in rows if _cam_month_key(r[4]) == latest_key]
    cam_row = max(same_month, key=lambda r: r[2] or 0)
    cam_name = (cam_row[0] or "").strip()
    cam_msrp = cam_row[1]
    # L1 字段优先级：model_name 优先，version 仅 fallback（model_name 为空时）
    if not cam_name:
        cam_name = (cam_row[3] or "").strip()
    if not cam_name and cam_msrp is None:
        return None

    # ---- L2 匹配链：MSRP 优先 → token 消歧 → None ----
    # 1. MSRP 精确匹配
    msrp_hits = []
    for t in trims:
        tp = _parse_price(t.get("price"))
        if tp is not None and cam_msrp is not None and abs(tp - cam_msrp) < 1:
            msrp_hits.append(t)
    if len(msrp_hits) == 1:
        sid = str(msrp_hits[0].get("spec_id") or "")
        if sid:
            return sid
        # spec_id 空——MSRP 信号识别了 trim 但不可用，继续 token 消歧找可用 spec_id
    # 2. token 消歧（MSRP 多义或无命中）
    #    候选池：MSRP 命中时只在 msrp_hits 内消歧；MSRP 无命中时在全部 trims 内
    #    年款 token（"25款"）是同车系通用特征，几乎必然共享，无判别力——
    #    消歧时排除年款 token，要求至少 1 个非年款 token 交集。
    pool = msrp_hits if msrp_hits else trims
    cam_toks = _extract_trim_tokens(cam_name)
    # 排除年款 token（以"款"结尾）
    cam_toks_no_year = {t for t in cam_toks if not t.endswith("款")}
    scored = []
    for t in pool:
        z_toks = _extract_trim_tokens(t.get("name") or "")
        z_toks_no_year = {t2 for t2 in z_toks if not t2.endswith("款")}
        inter = len(cam_toks_no_year & z_toks_no_year)
        if inter > 0:
            scored.append((inter, str(t.get("spec_id") or "")))
    if not scored:
        return None
    scored.sort(reverse=True)
    top = scored[0][0]
    # set 去重：trims 理论上可能含同 spec_id 重复条目，去重后判并列
    top_ids = list({sid for sc, sid in scored if sc == top})
    # 唯一最高分 → 返回；并列 → None（不猜）
    if len(top_ids) == 1:
        return top_ids[0] or None
    return None


def _series_alias_names(session, name: str) -> list[str]:
    """车系名匹配（v7 单表化）：对 SalesTrim.series 精确 IN 匹配，防 LIKE 串系
    （P0-4：选"汉"不并入"汉L"）。与 market_data._series_names 同口径，本地复制
    避免看板数据层对市场模块的导入耦合（dashboard_data 不依赖 market_data）。

    旧实现：查 series_alias 归一（name → series_key → source=trim 下所有 raw_name），
    用于把配置快照车系名映射到版型表原名。v7 退役 series_alias 与加权表后，市场侧
    只剩 sales_trim 单表，归一层已无存在意义，故退化为**精确单名**匹配。
    **函数名与签名保留**（main_trim_spec_id 与 test_main_trim_match 均按此调用），
    未命中的名字由 SalesTrim.series IN(names) 自然落空；空/空白名 → []。
    """
    n = str(name or "").strip()
    return [n] if n else []


def _cam_month_key(month_str) -> tuple:
    """'10月末' → (10, 1)；'1月中' → (1, 0)。与 market_data._month_key 同口径
    （本地复制避免看板数据层对市场模块的导入耦合）。"""
    m = re.search(r"(\d+)", str(month_str or ""))
    num = int(m.group(1)) if m else 0
    return (num, 1 if "末" in str(month_str or "") else 0)


def _parse_price(v) -> int | None:
    """解析价格字符串/数值 → 元（int）。
    "26.98万"/"26.98万元" → 269800；"269800" → 269800；269800.0 → 269800。
    空/占位符/负值/无法解析 → None（不编造 0，价格不应为负）。
    """
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s or s.upper() in {"-", "—", "无", "N/A", "NA", "/"}:
        return None
    wan = False
    # 兼容"万"和"万元"后缀（之家源当前是"X.XX万"，防 API 格式漂移）
    if s.endswith("万元"):
        s = s[:-2]
        wan = True
    elif s.endswith("万"):
        s = s[:-1]
        wan = True
    try:
        f = float(s)
    except ValueError:
        return None
    if f < 0:
        return None
    if wan:
        f *= 10000
    if f == 0:
        # 0 不是真实 MSRP（占位符/未知），返 None 避免误匹配
        return None
    return int(round(f))


def _extract_trim_tokens(name: str) -> set[str]:
    """从版型名提取归一 token（去空格小写化）。
    年款/续航/排量/电池容量/驱动形式/版型关键词/纯数字段。
    用于 CAM model_name ↔ 之家 trim.name 消歧。

    归一约定：电池容量"95kWh"与"95度"都归一到 token "95kwh"；
    驱动"4WD/四驱/AWD/4MATIC"归一到"四驱"，"后驱/后轮驱动/RWD"归一到"后驱"。
    纯数字段（3 位数如 510/610/702）作 token 前缀 n（如 n510），覆盖"610Air"
    这类版型编号——比字面互含更稳健。

    年款 token（"25款"）是同车系通用特征，几乎必然共享，单独命中无判别力——
    main_trim_spec_id 消歧时排除年款 token（以"款"结尾的 token）。
    """
    s = re.sub(r"\s+", "", str(name or "")).lower()
    toks: set[str] = set()
    # 年款：25款/2025款 → 25款
    for m in re.findall(r"(\d{2,4})款", s):
        toks.add(m[-2:] + "款")
    # 续航：702km/640km → 702km
    for m in re.findall(r"(\d{2,4})\s*km", s):
        toks.add(m + "km")
    # 排量：1.5T/2.0T → 1.5t
    for m in re.findall(r"(\d\.\d)t", s):
        toks.add(m + "t")
    # 电池容量：95kwh/95度/103kwh → 95kwh（要求数字紧跟 kwh 或 度，避免吞年款等数字）
    for m in re.findall(r"(\d{2,3})\s*kwh", s):
        toks.add(m + "kwh")
    for m in re.findall(r"(\d{2,3})\s*度", s):
        toks.add(m + "kwh")
    # 纯数字段：3 位数版型编号（510/610）→ n510/n610
    # 覆盖"610Air"等关键词表未收录的版型名，比字面互含更稳健。
    # 排除已被 km/kwh/度 捕获的数字（702km 已是 702km，不再重复 n702，避免冗余假命中）
    captured_nums = {m for m in re.findall(r"(\d{2,4})\s*km", s)}
    captured_nums |= {m for m in re.findall(r"(\d{2,3})\s*kwh", s)}
    captured_nums |= {m for m in re.findall(r"(\d{2,3})\s*度", s)}
    for m in re.findall(r"(?<!\d)(\d{3})(?!\d)", s):
        if m not in captured_nums:
            toks.add("n" + m)
    # 驱动形式归一：4wd/四驱/后驱/后轮驱动/rwd/awd/4matic
    if "4wd" in s or "四驱" in s or "awd" in s or "4matic" in s:
        toks.add("四驱")
    if "后驱" in s or "后轮驱动" in s or "rwd" in s:
        toks.add("后驱")
    # 版型关键词（扩展：补 air/ev/plus 等常见版型后缀）
    for kw in ["max", "ultra", "pro", "air", "ev", "plus",
               "标准版", "长续航", "超长续航", "智驾版", "智尊版",
               "自由版", "时尚版", "骑士版", "halo", "鹏翼",
               "性能", "运动", "豪华", "都市"]:
        if kw in s:
            toks.add(kw)
    return toks


def cross_pivot(model_id: str, year: str | None = None, spec: str | None = None,
                prov: str | None = None, kw: str | None = None,
                limit: int = 200) -> dict:
    """交叉透视筛选（specs/dashboards v5）：年款×版型×省份自由组合 → 原话子集 + n。

    年款从 spec_name 正则提取，缺年款归"未知年款"。
    省份按 province_of 归省口径筛（同 review_stream）。
    n<5 只返回原话不计算比率（小样本噪音防护）。
    库内无该 model_id 口碑返回 {"not_collected": True}。

    P0-7：命中 > limit 时改随机抽样（非插入序前 N），抽样种子派生自
    filter_hash（sha1，跨进程稳定）→ 同筛选可复现 → AI 总结缓存命中一致。

    P1-11（SQL 下推）：年款/版型/省份/关键词筛选下推 SQL WHERE（复用
    _stream_query，与 review_stream/export_stream 同口径），不再全量拉取再
    Python 过滤。唐新能源 9181 条全量→仅命中集入 Python。年款分面取自
    spec_name DISTINCT（年款来自 spec_name 正则，非独立列，无法 SQL GROUP BY；
    DISTINCT 后条目数 = 版型数 ≪ 口碑数，轻量拉取）。随机抽样逻辑保留下推后
    的命中集再抽样。
    """
    with session_scope() as s:
        # not_collected 守卫：COUNT 不拉行，避免空库仍走 _stream_query
        exists = s.query(OwnerReview.review_id).filter(
            OwnerReview.model_id == model_id).limit(1).count()
        if not exists:
            return {"not_collected": True, "model_id": model_id}
        # 年款分面：全量 spec_name DISTINCT → Python extract_year（分面是筛选
        # 下拉选项全集，不受当前筛选影响）
        spec_names = [r[0] for r in s.query(OwnerReview.spec_name).filter(
            OwnerReview.model_id == model_id).distinct().all()]
        year_facets = sorted({extract_year(sn) for sn in spec_names})
        # 筛选下推 SQL WHERE（_stream_query：year/spec/prov/kw 同 review_stream 口径）
        rows = _stream_query(s, model_id, spec, prov, None, kw, year).all()

    total = len(rows)
    truncated = total > limit
    # P0-7：命中 > limit 随机抽样（种子=filter_hash 派生，同筛选可复现 → 缓存一致）
    if truncated:
        filt = {"year": year or "", "spec": spec or "",
                "prov": prov or "", "kw": kw or ""}
        rng = random.Random(int(filter_hash(model_id, filt), 16))
        sample = rng.sample(rows, limit)
    else:
        sample = rows
    reviews = [{"review_id": r[0], "spec_name": r[1] or _SPEC_BLANK,
                "city": r[2] or "-", "post_date": r[3] or "-",
                "best": (r[4] or "")[:200], "worst": (r[5] or "")[:200],
                "buy_price": r[6] or "-"} for r in sample]
    # round3-fix R2：暴露全量命中集 review_id（不经过 limit 抽样），供标签分布
    # 全量聚合使用——避免 tag_dist 只统计抽样 100 条而失真。
    all_rids = [r[0] for r in rows]
    out: dict = {"n": total, "reviews": reviews, "year_facets": year_facets,
                 "all_rids": all_rids}
    if truncated:
        out["truncated"] = True
    return out


def series_drilldown(model_id: str) -> dict:
    """单车系下钻数据。库内无该 model_id 口碑时返回 {"not_collected": True}。

    省份守恒：provinces 只含 city 非空的口碑（Σ省+未知 = city 非空数），
    city 为空的条数由 city_blank_n 单独披露，不混入省份分组（specs/dashboards）。
    """
    with session_scope() as s:
        rows = s.query(OwnerReview.review_id, OwnerReview.spec_name, OwnerReview.city,
                       OwnerReview.score, OwnerReview.dimensions, OwnerReview.post_date,
                       OwnerReview.buy_price
                       ).filter(OwnerReview.model_id == model_id).all()
        if not rows:
            return {"not_collected": True, "model_id": model_id}
        # P1-11（SQL 下推）：sentiment 双桶过滤下推 SQL WHERE（仅拉 pro/con，
        # neutral/异常 不入桶——原 Python `if senti not in ("pro","con")` 前置
        # 到 DB 层），减少大车系（如唐新能源 9181 口碑 ≈45k 标签）的拉取量。
        # 孤儿标签（review_id 不在 OwnerReview）仍由 Python `rid not in
        # review_spec` 守卫兜底（model_id 相同但 review 缺失的边角数据）。
        tag_rows = s.query(
            ReviewTag.review_id, ReviewTag.sentiment,
            ReviewTag.tag_name, ReviewTag.tag_category
        ).filter(ReviewTag.model_id == model_id,
                 ReviewTag.sentiment.in_(("pro", "con"))).all()
        summ = s.get(SeriesSummary, model_id)

    name = (summ.series_name if summ else None) or model_id
    review_spec = {r[0]: (r[1] or _SPEC_BLANK) for r in rows}
    review_prov = {r[0]: (province_of(r[2]) if r[2] else None) for r in rows}

    def _new_group():
        return {"count": 0, "score_sum": 0.0, "score_n": 0, "prices": [],
                "dim_sum": defaultdict(float), "dim_n": defaultdict(int),
                "pro_tags": defaultdict(set), "con_tags": defaultdict(set)}

    spec_groups: dict[str, dict] = defaultdict(_new_group)
    prov_groups: dict[str, dict] = defaultdict(_new_group)

    def _targets_for(rid) -> list[dict]:
        """该口碑的累加目标：版型组必进；省份组仅当 city 归省成功（空 city
        不进省份分组——守恒口径，specs/dashboards）。"""
        ts = [spec_groups[review_spec[rid]]]
        if review_prov[rid] is not None:
            ts.append(prov_groups[review_prov[rid]])
        return ts

    def _acc_dims(dims, g: dict) -> None:
        if isinstance(dims, dict):
            for dk, dv in dims.items():
                if _usable_dim_val(dv):
                    g["dim_sum"][dk] += dv
                    g["dim_n"][dk] += 1

    for rid, senti, tname, tcat in tag_rows:
        if rid not in review_spec:
            continue  # 孤儿标签（所属口碑不在库内）跳过，防 KeyError→500
        if senti not in ("pro", "con"):
            continue  # 严格双桶：仅 pro/con 入桶，其余 sentiment 不默认归 con
        bucket = "pro_tags" if senti == "pro" else "con_tags"
        for g in _targets_for(rid):
            g[bucket][tname].add(rid)

    for rid, spec, city, score, dims, post, buy in rows:
        pw = parse_wan(buy)  # 解析一次；面议/缺失 → None 不进中位数分母
        for g in _targets_for(rid):
            g["count"] += 1
            if score is not None:
                g["score_sum"] += score
                g["score_n"] += 1
            if pw is not None:
                g["prices"].append(pw)
            _acc_dims(dims, g)

    def _topN(tags: dict) -> list:
        return [{"name": n, "cnt": len(ids)} for n, ids in
                sorted(tags.items(), key=lambda x: -len(x[1]))[:TOP_N]]

    def _group_view(g: dict) -> dict:
        return {"count": g["count"],
                "avg_score": round(g["score_sum"] / g["score_n"], 2) if g["score_n"] else None,
                "price_med": round(statistics.median(g["prices"]), 2) if g["prices"] else None,
                "price_n": len(g["prices"]),
                "dims": {k: round(g["dim_sum"][k] / g["dim_n"][k], 2) for k in g["dim_sum"]},
                "pros": _topN(g["pro_tags"]), "cons": _topN(g["con_tags"])}

    specs = [{"name": k, **_group_view(g)} for k, g in
             sorted(spec_groups.items(), key=lambda x: -x[1]["count"])]
    provinces = [{"name": k, **_group_view(g)} for k, g in
                 sorted(prov_groups.items(), key=lambda x: -x[1]["count"])]

    cov = _tag_coverage_for_series(model_id)
    scores = [r[3] for r in rows if r[3] is not None]
    posts = [r[5] for r in rows if r[5]]
    city_blank_n = sum(1 for r in rows if not r[2])
    # P0-4 采集覆盖率（库内/之家标注总数）+ 可分析率（有正文/已采）：
    # onsell_review_count=之家 API 标注的在售口碑总数（SeriesSummary 字段）；
    # 缺失时 collection_coverage=None（不编造分母）。可分析率分母=库内已采总数。
    collected = len(rows)
    onsell_total = (summ.onsell_review_count if summ else None)
    # 2026-10-18：封顶 1.0——之家壳表 onsell_review_count 是源站缓存标注，常见滞后
    # （源站标注 2 条、库内实采 100 条 → 曾渲染 5000%）。超 1 只说明"库内 ≥ 源站标注"。
    collection_coverage = (min(round(collected / onsell_total, 4), 1.0)
                           if onsell_total and onsell_total > 0 else None)
    analyzable_rate = (round(cov["taggable"] / collected, 4)
                       if collected > 0 else None)
    overall = {
        "reviews": len(rows), "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        "tagged": cov["tagged"], "taggable": cov["taggable"], "coverage": cov["coverage"],
        "first_post": min(posts) if posts else "-", "last_post": max(posts) if posts else "-",
        "spec_n": len(spec_groups), "province_n": len(prov_groups),
        # P0-4 口径分层披露
        "collected": collected, "onsell_total": onsell_total,
        "collection_coverage": collection_coverage,
        "analyzable_rate": analyzable_rate,
    }

    cov_level = ("ok" if cov["coverage"] >= COVERAGE_OK
                 else "warn" if cov["coverage"] >= COVERAGE_MIN else "none")
    # P0-4/3.3 黄牌：采集覆盖率 <80% 或口碑数 <30
    low_collection = collection_coverage is not None and collection_coverage < 0.8
    low_reviews = collected < 30

    return {"model_id": model_id, "series_name": name,
            "overview": overall, "cov_level": cov_level,
            "low_collection": low_collection, "low_reviews": low_reviews,
            "specs": specs, "provinces": provinces, "city_blank_n": city_blank_n}


def spec_facets(model_id: str) -> dict:
    """车系版型分面（data-layer-tag-system 阶段3）：返回 spec_name + 年款分面，
    供竞品 v2 picker 的 trim 下拉动态加载。轻量查询（仅 GROUP BY spec_name）。

    返回::
        {"specs": [{"name": str, "count": int}, ...],
         "years": [{"name": str, "count": int}, ...]}
    未采集车型返回 {"not_collected": True}。
    """
    with session_scope() as s:
        rows = s.query(OwnerReview.spec_name).filter(
            OwnerReview.model_id == model_id).all()
        if not rows:
            return {"not_collected": True, "model_id": model_id}
        spec_counts: dict[str, int] = defaultdict(int)
        year_counts: dict[str, int] = defaultdict(int)
        for (spec_name,) in rows:
            label = spec_name or _SPEC_BLANK
            spec_counts[label] += 1
            yr = extract_year(spec_name) if spec_name else None
            year_counts[yr or _UNKNOWN_YEAR] += 1
        specs = [{"name": k, "count": v} for k, v in
                 sorted(spec_counts.items(), key=lambda kv: -kv[1])]
        years = [{"name": k, "count": v} for k, v in
                 sorted(year_counts.items(), key=lambda kv: -kv[1])]
        return {"specs": specs, "years": years}


# dashboard-v10 Task 5.2 B3：标签分布聚合（横向条形图数据源）
TAG_DIST_TOP_N = 10


def tag_distribution(model_id: str, review_ids: list[str] | None = None,
                     top_n: int = TAG_DIST_TOP_N) -> dict:
    """标签分布（specs/dashboards v10 B3）：按 tag_name + sentiment 聚合 top-N。

    review_ids 传入时仅聚合该子集（跟随 cross_pivot 当前筛选命中集），None → 全 model。
    仅 pro/con 双桶（neutral/异常不入桶，与 series_drilldown / diagnose 口径一致）。
    pro/con 是命中该标签的口碑数（review_id 去重——同口碑同 senti 同标签只计一次，
    与 ReviewTag (review_id, tag_name) 唯一性约束一致）。
    空 review_ids → 空列表（不回退全量，防误展示全 model 标签）。

    返回 {"items": [{name, pro, con, total}], "pro_items": [...], "con_items": [...],
          "n": <命中标签行数>}。
    - items：按 total 降序取 top-N（旧契约，保留兼容）。
    - pro_items / con_items：**分别在各自情绪上独立排序取 top-N**——修双重截断：
      旧前端拿同一批 total-top-10 分两栏排序，导致满意点/槽点各栏实际只在
      total-top-10 内挑，凑不齐各自 Top10（大车系尤其明显）。现各栏独立 Top-N。
    """
    with session_scope() as s:
        q = s.query(ReviewTag.review_id, ReviewTag.sentiment,
                    ReviewTag.tag_name).filter(
            ReviewTag.model_id == model_id,
            ReviewTag.sentiment.in_(("pro", "con")))
        if review_ids is not None:
            if not review_ids:
                return {"items": [], "pro_items": [], "con_items": [], "n": 0}
            q = q.filter(ReviewTag.review_id.in_(review_ids))
        rows = q.all()
    if not rows:
        return {"items": [], "pro_items": [], "con_items": [], "n": 0}
    agg: dict[str, dict] = defaultdict(lambda: {"pro_ids": set(), "con_ids": set()})
    for rid, senti, tname in rows:
        if not tname:
            continue
        if senti == "pro":
            agg[tname]["pro_ids"].add(rid)
        elif senti == "con":
            agg[tname]["con_ids"].add(rid)
    items = [{"name": n, "pro": len(v["pro_ids"]), "con": len(v["con_ids"]),
              "total": len(v["pro_ids"]) + len(v["con_ids"])}
             for n, v in agg.items()]
    items.sort(key=lambda x: -x["total"])
    # 修双重截断：两栏各自在**全量 items** 上独立排序取 top-N（不受 total 截断限制）
    pro_items = sorted(items, key=lambda x: -x["pro"])[:top_n]
    con_items = sorted(items, key=lambda x: -x["con"])[:top_n]
    return {"items": items[:top_n], "pro_items": pro_items,
            "con_items": con_items, "n": len(rows)}


# dashboard-v11 Task 2.2：维度短板对照（同级各业务维度 pro/con vs 同级中位）
def peer_dim_compare(model_id: str) -> dict:
    """维度短板对照（specs/dashboards v11）：target 各业务维度 pro/con 计数 vs
    同级（同 level_name）每维度 pro/con 中位。

    业务维度走 `_map_to_business_dim`（V3 业务维度，跨工具命名一致）。
    pro/con 是命中该维度任一标签的口碑数（review_id 去重——同口碑同 senti 同维度
    只计一次，与 tag_distribution 口径一致）。

    返回::
        {"peer_n": N, "dims": [
            {"dim", "target_pro", "target_con",
             "peer_pro_med", "peer_con_med", "peer_n"}, ...
        ]}

    不足信封：not_collected（SeriesSummary 缺失）/ insufficient_data（无 level 或同级仅自己）。
    """
    from src.tools.reviews import _map_to_business_dim

    with session_scope() as s:
        target = s.get(SeriesSummary, model_id)
        if target is None:
            return {"not_collected": True, "model_id": model_id}
        level = target.level_name
        if level is None:
            return {"insufficient_data": True, "reason": "no level_name",
                    "model_id": model_id}
        peer_ids = [r[0] for r in s.query(SeriesSummary.series_id).filter(
            SeriesSummary.level_name == level).all()]
        # 排除自身 → 同级竞品池
        peers = [sid for sid in peer_ids if sid != model_id]
        if not peers:
            return {"insufficient_data": True, "reason": "no peers",
                    "model_id": model_id}
        all_ids = [model_id] + peers
        # 一次查询取同级所有标签行（model_id, sentiment, tag_category, tag_name, review_id）
        rows = s.query(ReviewTag.model_id, ReviewTag.sentiment,
                       ReviewTag.tag_category, ReviewTag.tag_name,
                       ReviewTag.review_id).filter(
            ReviewTag.model_id.in_(all_ids),
            ReviewTag.sentiment.in_(("pro", "con"))).all()
    # 聚合：{model_id: {biz_dim: {"pro_ids": set, "con_ids": set}}}
    agg: dict[str, dict[str, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"pro_ids": set(), "con_ids": set()}))
    for mid, senti, tcat, tname, rid in rows:
        if not tname:
            continue
        biz = _map_to_business_dim(tcat or "", tname or "")
        bucket = agg[mid][biz]
        if senti == "pro":
            bucket["pro_ids"].add(rid)
        elif senti == "con":
            bucket["con_ids"].add(rid)
    # target 各维度
    target_agg = agg.get(model_id, {})
    # 全部出现过的维度（target + peers 并集，按 target 维度优先）
    all_dims = list(target_agg.keys())
    for mid in peers:
        for d in agg.get(mid, {}):
            if d not in all_dims:
                all_dims.append(d)
    dims_out = []
    for d in all_dims:
        t_pro = len(target_agg.get(d, {"pro_ids": set()})["pro_ids"])
        t_con = len(target_agg.get(d, {"con_ids": set()})["con_ids"])
        peer_pros = [len(agg[mid].get(d, {"pro_ids": set()})["pro_ids"])
                     for mid in peers]
        peer_cons = [len(agg[mid].get(d, {"con_ids": set()})["con_ids"])
                     for mid in peers]
        dims_out.append({
            "dim": d,
            "target_pro": t_pro, "target_con": t_con,
            "peer_pro_med": statistics.median(peer_pros) if peer_pros else 0,
            "peer_con_med": statistics.median(peer_cons) if peer_cons else 0,
            "peer_n": len(peers),
        })
    # 排序：target 总提及（pro+con）降序，让短板/长板最显著的维度在前
    dims_out.sort(key=lambda x: -(x["target_pro"] + x["target_con"]))
    return {"peer_n": len(peers), "dims": dims_out}


# dashboard-v11 Task 2.3：竞品口碑横向对比
PEER_TAG_COMPARE_MAX_PEERS = 4
PEER_TAG_COMPARE_TOP_N = 10


def peer_tag_compare(model_id: str, peer_ids: list[str]) -> dict:
    """竞品口碑横向对比（specs/dashboards v11）：target + 2-4 个竞品的标签分布横向矩阵。

    对每个车系调 `tag_distribution`（top_n=10），取并集标签，构造每系 pro/con 矩阵。
    数据真实性：各车系标签独立查询，未采集/无标签车系返回全 0 行（不编造）。

    返回::
        {"series": [{"id", "name"}, ...],   # target 在首位
         "tags": [tag_name, ...],            # 并集标签，按跨系总命中降序
         "cells": {tag: [{"pro", "con"}, ... per series]}}

    校验：peer_ids 超 4 个 → {"error": ...}；target 无 SeriesSummary → not_collected。
    """
    if len(peer_ids) > PEER_TAG_COMPARE_MAX_PEERS:
        return {"error": f"竞品最多 {PEER_TAG_COMPARE_MAX_PEERS} 个"}
    with session_scope() as s:
        target = s.get(SeriesSummary, model_id)
        if target is None:
            return {"not_collected": True, "model_id": model_id}
        # name 解析：target + peers（缺 SeriesSummary 的 peer 用 id 兜底）
        names = {model_id: target.series_name or model_id}
        for pid in peer_ids:
            row = s.get(SeriesSummary, pid)
            names[pid] = (row.series_name if row else None) or pid
    all_ids = [model_id] + list(peer_ids)
    # 每系独立 tag_distribution（top_n 放宽到 10，覆盖更多标签便于并集）
    per_series = {mid: tag_distribution(mid, top_n=PEER_TAG_COMPARE_TOP_N)
                  for mid in all_ids}
    # 并集标签 + 跨系总命中
    tag_totals: dict[str, int] = defaultdict(int)
    for mid in all_ids:
        for it in per_series[mid]["items"]:
            tag_totals[it["name"]] += it["total"]
    tags_sorted = [t for t, _ in sorted(tag_totals.items(), key=lambda kv: -kv[1])]
    # 矩阵：每标签每系 {pro, con}（缺失标签=0）
    lookup = {mid: {it["name"]: it for it in per_series[mid]["items"]}
              for mid in all_ids}
    cells = {}
    for t in tags_sorted:
        cells[t] = []
        for mid in all_ids:
            it = lookup[mid].get(t)
            cells[t].append({"pro": it["pro"] if it else 0,
                             "con": it["con"] if it else 0})
    return {
        "series": [{"id": mid, "name": names[mid]} for mid in all_ids],
        "tags": tags_sorted,
        "cells": cells,
    }


# data-layer-tag-system 阶段3：竞品口碑对比 v2（双车 + 粒度锁定 + 样本守卫 + 可比性 + 分类层兜底）
PEER_V2_SAMPLE_REJECT = 5     # n<5 拒绝（stop_answering，不编造）
PEER_V2_SAMPLE_WARN = 10      # n<10 黄牌
PEER_V2_COMPAT_LOW = 40.0     # 可比性% <40 提示看分类层


def peer_tag_compare_v2(model_a: str, spec_a: str, model_b: str, spec_b: str,
                        granularity: str = "year") -> dict:
    """竞品口碑对比 v2（data-layer-tag-system 阶段3）：双车 + 年款/版型锁定 +
    样本守卫 + 可比性体检 + 分类层兜底。

    granularity:
        - "year"：spec_a/spec_b 为年款字面（如 "2024款"），空=全部年款
        - "spec" ：spec_a/spec_b 为版型名（OwnerReview.spec_name），空=全部版型

    返回::
        {"sample_guard": {n_a, n_b, status_a, status_b, reject, warn, advice},
         "comparability": {common, only_a, only_b, ratio, advice},
         "category_compare": [{dim, a_pro, a_con, b_pro, b_con}, ...],
         "tag_details": {common:[...], only_a:[...], only_b:[...]}}
        tag_details 每项含 {name, a_pro, a_con, b_pro, b_con, category, dim}——
        dim 为业务维度（_map_to_business_dim），供前端按维度折叠归位（K-6）。

    数据真实性：标签独立查询，未采集/样本不足返回空结构（不编造）；缺失标签
    标"未提及"（非 0），区别于"确认没有"。样本守卫：n<5 拒绝，n<10 黄牌。
    """
    from src.tools.reviews import _map_to_business_dim, _BUSINESS_DIM_ORDER

    if granularity not in ("year", "spec"):
        return {"error": "granularity 只能是 year 或 spec"}

    def _filtered_review_ids(s, model_id: str, spec_val: str) -> list[str]:
        q = s.query(OwnerReview.review_id).filter(OwnerReview.model_id == model_id)
        if spec_val:
            if granularity == "year":
                q = q.filter(_contains(OwnerReview.spec_name, spec_val))
            else:
                q = q.filter(OwnerReview.spec_name == spec_val)
        return [r[0] for r in q.all()]

    def _tag_rows(s, model_id: str, rids: list[str]) -> list:
        if not rids:
            return []
        return s.query(ReviewTag.review_id, ReviewTag.sentiment,
                       ReviewTag.tag_name, ReviewTag.tag_category).filter(
            ReviewTag.model_id == model_id,
            ReviewTag.sentiment.in_(("pro", "con")),
            ReviewTag.review_id.in_(rids)).all()

    with session_scope() as s:
        rids_a = _filtered_review_ids(s, model_a, spec_a)
        rids_b = _filtered_review_ids(s, model_b, spec_b)
        rows_a = _tag_rows(s, model_a, rids_a)
        rows_b = _tag_rows(s, model_b, rids_b)
        sa = s.get(SeriesSummary, model_a)
        sb = s.get(SeriesSummary, model_b)
        name_a = (sa.series_name if sa else None) or model_a
        name_b = (sb.series_name if sb else None) or model_b

    n_a, n_b = len(rids_a), len(rids_b)

    def _status(n: int) -> str:
        return "ok" if n >= PEER_V2_SAMPLE_WARN else (
            "warn" if n >= PEER_V2_SAMPLE_REJECT else "reject")

    st_a, st_b = _status(n_a), _status(n_b)
    rejected = st_a == "reject" or st_b == "reject"
    sample_guard = {
        "n_a": n_a, "n_b": n_b,
        "status_a": st_a, "status_b": st_b,
        "reject": rejected,
        "warn": (not rejected) and (st_a == "warn" or st_b == "warn"),
        "advice": "样本不足（n<5），建议改用年款级对比或扩大筛选" if rejected else (
            "样本偏少（n<10），结论仅供参考" if st_a == "warn" or st_b == "warn" else ""),
    }

    # 聚合：tag 级（去重 review_id）+ 分类层（biz_dim）
    def _aggregate(rows):
        tag_agg = defaultdict(lambda: {"pro_ids": set(), "con_ids": set(),
                                        "category": ""})
        cat_agg = defaultdict(lambda: {"pro_ids": set(), "con_ids": set()})
        for rid, senti, tname, tcat in rows:
            if not tname:
                continue
            tcat = tcat or ""
            if senti == "pro":
                tag_agg[tname]["pro_ids"].add(rid)
                tag_agg[tname]["category"] = tcat
            elif senti == "con":
                tag_agg[tname]["con_ids"].add(rid)
                tag_agg[tname]["category"] = tcat
            biz = _map_to_business_dim(tcat, tname)
            if senti == "pro":
                cat_agg[biz]["pro_ids"].add(rid)
            elif senti == "con":
                cat_agg[biz]["con_ids"].add(rid)
        tag_out = {n: {"pro": len(v["pro_ids"]), "con": len(v["con_ids"]),
                       "total": len(v["pro_ids"]) + len(v["con_ids"]),
                       "category": v["category"]} for n, v in tag_agg.items()}
        cat_out = {dim: {"pro": len(v["pro_ids"]), "con": len(v["con_ids"])}
                   for dim, v in cat_agg.items()}
        return tag_out, cat_out

    tag_a, cat_a = _aggregate(rows_a)
    tag_b, cat_b = _aggregate(rows_b)

    # 拒绝时返回空结构（不编造）
    empty_compat = {"common": 0, "only_a": 0, "only_b": 0, "ratio": 0.0, "advice": ""}
    empty_tags = {"common": [], "only_a": [], "only_b": []}
    if rejected:
        return {
            "sample_guard": sample_guard,
            "comparability": empty_compat,
            "category_compare": [],
            "tag_details": empty_tags,
            "names": {"a": name_a, "b": name_b},
        }

    # 可比性体检
    set_a, set_b = set(tag_a), set(tag_b)
    common_names = set_a & set_b
    only_a_names = set_a - set_b
    only_b_names = set_b - set_a
    union_n = len(set_a | set_b)
    ratio = (len(common_names) / union_n * 100) if union_n else 0.0
    comparability = {
        "common": len(common_names), "only_a": len(only_a_names),
        "only_b": len(only_b_names), "ratio": round(ratio, 1),
        "advice": "可比性偏低（<40%），标签层差异大——建议看下方分类层聚合"
                  if ratio < PEER_V2_COMPAT_LOW and union_n > 0 else "",
    }

    # 分类层聚合（biz_dim，永远可比——即便标签几乎不重合，维度总能对齐）
    all_dims = list(dict.fromkeys(
        list(cat_a.keys()) + [d for d in cat_b.keys() if d not in cat_a]))
    # 按 _BUSINESS_DIM_ORDER 排序，未在表中的维度尾随
    order_idx = {d: i for i, d in enumerate(_BUSINESS_DIM_ORDER)}

    def _dim_sort(d):
        return (order_idx.get(d, 999), d)
    all_dims_sorted = sorted(all_dims, key=_dim_sort)
    category_compare = []
    for d in all_dims_sorted:
        ca, cb = cat_a.get(d, {"pro": 0, "con": 0}), cat_b.get(d, {"pro": 0, "con": 0})
        # 双方都为 0 的维度不入列（无信息量）
        if ca["pro"] == 0 and ca["con"] == 0 and cb["pro"] == 0 and cb["con"] == 0:
            continue
        category_compare.append({
            "dim": d,
            "a_pro": ca["pro"], "a_con": ca["con"],
            "b_pro": cb["pro"], "b_con": cb["con"],
        })

    # 标签明细：三组，按总命中降序；缺失方标"未提及"（非 0）
    def _tag_detail(name, a_item, b_item):
        cat = (a_item or b_item)["category"]
        return {
            "name": name,
            "a_pro": a_item["pro"] if a_item else "未提及",
            "a_con": a_item["con"] if a_item else "未提及",
            "b_pro": b_item["pro"] if b_item else "未提及",
            "b_con": b_item["con"] if b_item else "未提及",
            "category": cat,
            # K-6：附业务维度（biz_dim）——前端按维度折叠时把标签挂到对应维度下，
            # 与 category_compare.dim 同源（_map_to_business_dim），两级自洽。
            "dim": _map_to_business_dim(cat, name),
        }

    def _by_total(name):
        a_t = tag_a.get(name, {}).get("total", 0)
        b_t = tag_b.get(name, {}).get("total", 0)
        return -(a_t + b_t)

    common_list = [_tag_detail(n, tag_a.get(n), tag_b.get(n))
                   for n in sorted(common_names, key=_by_total)]
    only_a_list = [_tag_detail(n, tag_a.get(n), None)
                   for n in sorted(only_a_names, key=_by_total)]
    only_b_list = [_tag_detail(n, None, tag_b.get(n))
                   for n in sorted(only_b_names, key=_by_total)]

    return {
        "sample_guard": sample_guard,
        "comparability": comparability,
        "category_compare": category_compare,
        "tag_details": {
            "common": common_list,
            "only_a": only_a_list,
            "only_b": only_b_list,
        },
        "names": {"a": name_a, "b": name_b},
    }


async def compare_trims(selections: list[tuple[str, str]],
                        *, cfgs: dict[str, dict] | None = None,
                        trims_by_mid: dict[str, dict] | None = None) -> dict:
    """版型级配置对比（specs/dashboards）。selections = [(model_id, spec_id), ...] 2-4 个。

    cfgs=None → 取值走 api.get_full_config（带缓存，实时路径，测试 mock）。
    cfgs 传入 → 用已取的 {model_id: 配置dict}（快照路径，看板 trim 模式走此分支，
    cfg_failed 口径为"快照无 categories"；并标 data_source）。
    trims_by_mid：调用方可传入已取的 {model_id: get_trims 结果}（同请求内
    auto_fill/下拉已拉过一遍时复用，避免冷缓存下重复网络批次）。
    """
    import asyncio
    from src.tools.config import get_trims

    if not (2 <= len(selections) <= 4):
        return {"error": "请提供 2-4 个（车型, 版型）组合"}
    mids = list(dict.fromkeys(m for m, _ in selections))
    from_snapshot = cfgs is not None
    if cfgs is None:
        from src.api.autohome_api import get_autohome_api
        api = await get_autohome_api()
        cfg_list = await asyncio.gather(*[api.get_full_config(m) for m in mids])
        cfgs = {m: c for m, c in zip(mids, cfg_list) if isinstance(c, dict) and "categories" in c}
    if trims_by_mid is None:
        trims_list = await asyncio.gather(*[get_trims(m) for m in mids])
        trims_by_mid = dict(zip(mids, trims_list))

    cols = _build_cols(selections, trims_by_mid)
    out = _trim_diff_rows(cfgs, cols)
    # 数据真实性：取数失败的车型显式披露（失败列的 "—" ≠ 无此参数 ≠ 配置相同）
    if from_snapshot:
        out["cfg_failed"] = [m for m in mids if not cfgs.get(m, {}).get("categories")]
        out["data_source"] = "config_snapshots 快照"
    else:
        out["cfg_failed"] = [m for m in mids if m not in cfgs]
    return out


def _build_cols(selections: list[tuple[str, str]],
                trims_by_mid: dict[str, dict]) -> list[dict]:
    """构造列头：每列 (model_id, spec_id) → 版型名/指导价（走 trims_by_mid）。
    compare_trims 与（经包装）快照路径共用（specs/dashboards v5 /simplify 归一）。"""
    cols = []
    for mid, spec_id in selections:
        trim_name, price = spec_id, ""
        for t in (trims_by_mid.get(mid) or {}).get("trims", []):
            if str(t.get("spec_id")) == str(spec_id):
                trim_name, price = t.get("name", spec_id), t.get("price", "")
                break
        cols.append({"model_id": mid, "spec_id": spec_id, "trim": trim_name, "price": price})
    return cols


# P0-2：diff 排除元数据白名单——价格/名称/年款等非配置参数，不该参与配置 diff
# （把"厂商指导价变了"当"加配"是错误）。_trim_diff_rows 路径在参数遍历入口 skip，
# 车型名称等元数据统一在此收口排除。
_DIFF_EXCLUDE = {"厂商指导价", "车型名称", "年款", "级别", "能源类型",
                 "上市时间", "生产状态", "厂商", "品牌", "车系", "制造商"}


def _is_diff_excluded(param: str) -> bool:
    """参数名命中元数据白名单（子串匹配，兼容'厂商指导价(万元)'等带单位变体）。"""
    return any(meta in param for meta in _DIFF_EXCLUDE)


def _trim_diff_rows(cfgs: dict, cols: list[dict]) -> dict:
    """纯函数核心：按每列 (model_id, spec_id) 取参数值，仅保留跨列存在差异的参数。

    值形态：dict（版型级 {spec_id: 值}）按列 spec_id 取；标量为车系级；取不到 → "缺采"。
    参数在某车型配置中整体缺失时该列槽位为 None，成行时映射为 "缺采"（M2：区别于
    值级"—"=确认无）；差异比较在归一后进行，不产出"渲染后全缺采/全同值"的可见无差异行。
    无（"—"）与缺采（None 槽位）是 v8 4 态下的不同状态，视为可见差异成行。
    """
    all_params: dict[str, dict[str, list]] = {}
    for i, c in enumerate(cols):
        cfg = cfgs.get(c["model_id"]) or {}
        for cat, params in (cfg.get("categories") or {}).items():
            for param, pv in params.items():
                col_vals = all_params.setdefault(cat, {}).setdefault(param, [None] * len(cols))
                col_vals[i] = _spec_value(pv, c["spec_id"])

    cats = []
    for cat in sorted(all_params):
        rows = []
        for p, vals in sorted(all_params[cat].items()):
            if _is_diff_excluded(p):
                continue  # P0-2：元数据（指导价/名称等）不进配置 diff
            disp = ["缺采" if v is None else v for v in vals]   # None（参数整体缺失=该列未采到此参数）归一为"缺采"，区别于值级"—"
            if len(set(disp)) > 1:                           # 过滤在归一后比较，防可见无差异行
                rows.append({"param": p, "vals": disp,
                             # P0#7：原始 None=参数行在该列配置中未出现（采集缺行），
                             # 与"有行但值为空"区分，供差价层拒绝把"没取到"当"确认没有"
                             "param_absent": [v is None for v in vals]})
        if rows:
            cats.append({"name": cat, "rows": rows})
    # P1-9/P2-26：扫各列快照 categories 字段名+值丢字，供对比表披露 pill。
    fc_n = 0
    fc_samples: list[str] = []
    for c in cols:
        fc = _detect_font_corruption((cfgs.get(c["model_id"]) or {}).get("categories") or {})
        fc_n += fc["n"]
        if not fc_samples:
            fc_samples = fc["samples"]
    return {"cols": cols, "cats": cats,
            "font_corrupted_n": fc_n, "font_corrupt_samples": fc_samples}


def _state(v) -> str:
    """4 态判读（dashboard-v8 根因 A）：缺采/无/选配/标配/数值/文本。
    汽车之家是 ●标配/○选配/-无 三态。
    - 缺采：None/空/"缺采"（未采集，与"无"区分——不可确认 absence，不可计价）
    - 无：- / — / 无 / N/A（确认没有）
    - 选配：○ / ○○ / 选配（具备，但非标配——计中档价）
    - 标配：● / 标配 / 1 / 有
    - 数值：可解析为 float（含千分位/km 单位）
    - 文本：其余（如"全景天窗"）
    单一真相源；concept_config 经 `from src.api.dashboard_data import _state` 复用。"""
    if v is None or v == "" or v == "缺采":
        return "缺采"
    s = str(v).strip()
    if s in ("—", "-", "无", "none", "null", "N/A"):
        return "无"
    if s in ("○", "○○", "选配"):
        return "选配"
    if s in ("●", "标配", "1", "有"):
        return "标配"
    try:
        float(s.replace(",", "").replace("km", "").replace("KM", ""))
        return "数值"
    except (ValueError, AttributeError):
        return "文本"


def _spec_value(param_val, spec_id) -> str:
    """取参数值：dict→按 spec_id 取，标量→直接；空值（None/""）归一为 "缺采"
    （v8：区分"未采集"与"确认无(-)"——后者保持 "-" 原样）。
    方案1（Task9）：list[{name}]（复合功能 sublist 保结构）→ names 用 ' / ' join
    展示，与旧 join 快照口径一致；str → 原样。
    _trim_diff_rows 与 compare_trims_from_snapshots 共用（specs/dashboards v5 /simplify 归一）。"""
    if isinstance(param_val, dict):
        v = param_val.get(str(spec_id), param_val.get(spec_id))
    else:
        v = param_val
    if v in (None, ""):
        return "缺采"
    if isinstance(v, list):
        names = [it.get("name", "") for it in v if isinstance(it, dict) and it.get("name")]
        return " / ".join(names) if names else "—"
    return str(v)


# ---------- Task 3: config_snapshots 快照读源（specs/dashboards v5） ----------

def get_config_snapshot(series_id: str) -> dict:
    """读 config_snapshots 表（specs/dashboards v5）。库内无该系快照返回 not_collected。
    看板只读；刷新走 collector 式写库端点（/config/refresh-snapshot/{sid}）。"""
    with session_scope() as s:
        row = s.get(ConfigSnapshot, series_id)
        if row is None:
            return {"not_collected": True, "series_id": series_id}
        return {
            "series_id": row.series_id, "series_name": row.series_name or series_id,
            "maker": row.maker, "energy": row.energy, "level": row.level,
            "price_range": row.price_range, "categories": row.categories or {},
            "fetched_at": row.fetched_at or "-", "version": row.version,
        }


def list_config_snapshots() -> list[dict]:
    """列出所有有快照的车系（看板选择器用，扩到 244 系）。
    替代既有从 SeriesSummary 取选择器的口径——快照表是配置看板的真实数据源。"""
    with session_scope() as s:
        rows = s.query(ConfigSnapshot.series_id, ConfigSnapshot.series_name,
                       ConfigSnapshot.energy, ConfigSnapshot.level,
                       ConfigSnapshot.price_range, ConfigSnapshot.fetched_at
                       ).order_by(ConfigSnapshot.series_name).all()
    return [{"id": r[0], "name": r[1] or r[0], "energy": r[2], "level": r[3],
             "price_range": r[4], "fetched_at": r[5]} for r in rows]


async def compare_trims_from_snapshots(selections: list[tuple[str, str]],
                                       snapshots: dict[str, dict],
                                       trims_by_mid: dict[str, dict] | None = None) -> dict:
    """版型级对比（从 config_snapshots 快照取配置，specs/dashboards v5）。
    /simplify 后委托 compare_trims(cfgs=snapshots)——核心逻辑已合并入 compare_trims。
    保留此签名供路由与测试 monkeypatch（cfgs 来源=快照，data_source 标注快照来源）。
    trims（版型名/指导价）仍走 API（不在快照里）。"""
    return await compare_trims(selections, cfgs=snapshots, trims_by_mid=trims_by_mid)


async def spec_compare_horizontal(selections: list[tuple[str, str]],
                                  snapshots: dict[str, dict],
                                  trims_by_mid: dict[str, dict[str, str]] | None = None) -> dict:
    """之家式横向对比表数据组装（specs/config-dashboard-redesign）。
    输出：rows(每行 cells 取快照原始值)/groups/cross_series/missing(按列)。
    单元格 ●◐○- 取快照 categories 原始字段值（非 tier 反推）；复合枚举子项
    （extract=sublist_contains，如 高速NOA/城市NOA/前排座椅按摩/外后视镜*）按概念
    自身 extract_pattern 求值折叠为 ●/-（字段有值≠子项具备），口径见 concept_present_cell。
    概念项 implies（如 城市NOA⇒高速NOA）在行组装后同列传递"具备"；
    hidden_if_any（如 激光雷达在高速/城市NOA 存在时整行隐藏，其价值已含于NOA）。
    跨车系不做交集收敛隐藏（除概念项声明的 hidden_if_any 外，全量显示）；
    缺项 cell 标「该车系无此项」（字段不存在）vs「缺采」（字段存在但未采集）；
    cols 输出 trim_name（版型名，由路由层 get_trims 填充，回退 spec_id）。
    config-dashboard 改造：每概念行附 param(原生参数名=计价键)/price(概念兜底单价)/
    present(与 cols 等长三态数组：1 具备 / 0 确认无 / None 缺采)，供 §02 首列行内计价
    与前端差价口径。差价（「配置差价（两车）」）只在前端按 present+内存态手填价就地计算
    ——后端不再产出 price_diff（避免同一语义两处实现）；手填单价仅当次对比内存态生效，
    不落库、不调任何写接口。
    2026-10-08：移除「概念价值分」——不再下发 value_per_col（前后端一并清理）。
    """
    from src.insights.concept_config import (
        _load_configs, _configs_by_id, concept_present_cell,
        _concept_price_for_param, _concept_tier_for_state,
    )

    configs = _load_configs()
    cols = [{"model_id": mid, "spec_id": sid} for mid, sid in selections]
    series_ids = {mid for mid, _ in selections}
    cross_series = len(series_ids) > 1

    energies = {}
    for mid in series_ids:
        snap = snapshots.get(mid) or {}
        energies[mid] = snap.get("energy") or "纯电"

    # config-dashboard-redesign：跨车系全量显示不隐藏（推翻收敛交集）
    active_configs = configs
    hidden_n = 0

    rows = []
    groups = {}
    missing = {mid: {"concept_missing_n": 0, "font_corrupted_n": 0} for mid in series_ids}

    for cfg in active_configs:
        cells = []
        sources = []
        present = []
        all_missing = True
        for c in cols:
            mid, sid = c["model_id"], c["spec_id"]
            cats = (snapshots.get(mid) or {}).get("categories") or {}
            # 概念语义求值（单一真相源）：按 cfg 自身 extract 规则判读展示值/是否具备，
            # 不再用"字段是否有值"——旧口径把复合枚举子项差异吞成"不计"（差价方向算反的根因）。
            cell, pres, pname = concept_present_cell(cfg, cats, sid)
            cells.append(cell)
            present.append(pres)
            if pname is None:
                sources.append({"col": mid, "field": None, "status": "该车系无此项"})
                missing[mid]["concept_missing_n"] += 1
            elif pres is None:
                sources.append({"col": mid, "field": pname, "status": "缺采"})
                missing[mid]["concept_missing_n"] += 1
            else:
                sources.append({"col": mid, "field": pname, "status": "ok"})
                all_missing = False
        if all_missing:
            continue  # 全列缺采的行不展示
        # §02 首列行内计价：param=原生参数名（计价键，与既有 option_prices 语义一致）；
        # price=概念兜底单价（纯概念口径，不含任何持久化手填价——手填价仅前端内存态）；
        # present=与 cols 等长三态数组（1/0/None），供前端唯一实现差价口径。
        param, ah_cat = cfg["ah_param"], cfg["ah_category"]
        states = [_state(c) for c in cells]
        first_present = next((k for k, p in enumerate(present) if p == 1), None)
        tier = (_concept_tier_for_state(ah_cat, param, states[first_present])
                if first_present is not None else 1)
        price = _concept_price_for_param(ah_cat, param, {}, tier=tier)
        row = {
            "id": cfg["id"], "name": cfg["name"], "category": cfg["category"],
            "param": param, "ah_category": ah_cat,
            "price": price,
            "cells": cells, "sources": sources,
            "present": present,
            "is_concept": True,
        }
        rows.append(row)
        groups.setdefault(cfg["category"], []).append(row)

    # 概念项蕴含关系传递（concept_configs.implies）：蕴含方在该列"具备"时，被蕴含项
    # 同列强制判"具备"（如 城市NOA ⇒ 高速NOA —— 城市NOA车型必有高速NOA）。
    # 缺采(None)不传递（不可确认 absence）；rows/groups 引用同一 dict，原地改即同步。
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        for imp in (_configs_by_id().get(r["id"]) or {}).get("implies") or []:
            tgt = by_id.get(imp)
            if tgt is None:
                continue
            for k in range(len(cols)):
                if r["present"][k] == 1 and tgt["present"][k] != 1:
                    tgt["cells"][k] = "●"
                    tgt["present"][k] = 1

    # 概念项条件隐藏（concept_configs.hidden_if_any）：被引用项在"任一列"具备 → 整行不展示。
    # 例：激光雷达(K1) 在 高速/城市NOA(C1/C2) 存在时不单独成行（其价值口径已含于NOA）。
    hidden = set()
    for r in rows:
        trig = (_configs_by_id().get(r["id"]) or {}).get("hidden_if_any") or []
        if trig and any(t in by_id and any(p == 1 for p in by_id[t]["present"]) for t in trig):
            hidden.add(r["id"])
    if hidden:
        rows = [r for r in rows if r["id"] not in hidden]
        groups = {k: [r for r in v if r["id"] not in hidden] for k, v in groups.items()}
        groups = {k: v for k, v in groups.items() if v}  # 空分组不展示

    return {
        "rows": rows,
        "groups": [{"name": k, "rows": v} for k, v in groups.items()],
        "cross_series": cross_series,
        "hidden_n": hidden_n,
        "missing": missing,
        "cols": [{"model_id": mid, "spec_id": sid,
                  "series_name": (snapshots.get(mid) or {}).get("series_name", mid),
                  "trim_name": (trims_by_mid or {}).get(mid, {}).get(sid) or sid,
                  "energy": energies[mid]} for mid, sid in selections],
    }


# ---------- Task 4: 阶梯连线对比（specs/dashboards v5） ----------

def _delta(va, vb) -> str:
    """7 类变化标签（dashboard-v8 Task 1 口径，Task 2 抽取复用）。
    用 _state 判 4 态：缺采/无/选配/标配/数值/文本。
    - 缺采任一侧 → 数据缺失（不可确认 absence，不当 加/减配）
    - 无→标配/选配/数值/文本 = 新增（选装）；标配/选配/数值/文本→无 = 取消
    - 选配→标配 = 升级；标配→选配 = 降级
    - 数值→数值 = 升降；其余同态不同值 = 取值不同
    返回 None 表示两值一致（无差异行）。"""
    if va == vb:
        return None
    sa, sb = _state(va), _state(vb)
    if sa == "缺采" or sb == "缺采":
        return "数据缺失"
    if sa == "无" and sb in ("标配", "选配", "数值", "文本"):
        return "新增（选装）" if sb == "选配" else "新增"
    if sa in ("标配", "选配", "数值", "文本") and sb == "无":
        return "取消"
    if sa == "选配" and sb == "标配":
        return "升级"
    if sa == "标配" and sb == "选配":
        return "降级"
    if sa == "数值" and sb == "数值":
        na = float(str(va).replace(",", "").replace("km", "").replace("KM", ""))
        nb = float(str(vb).replace(",", "").replace("km", "").replace("KM", ""))
        return f"数值提升 +{nb - na:g}" if nb > na else f"数值下降 {nb - na:g}"
    # P0-3：复合枚举（sublist，' / ' 分隔，如座椅调节方向）拆 set 比较——
    # 子项增删有方向（新增/取消子项），仅顺序不同才判"取值不同"。
    sa_str, sb_str = str(va), str(vb)
    if " / " in sa_str and " / " in sb_str:
        set_a = {p.strip() for p in sa_str.split(" / ") if p.strip()}
        set_b = {p.strip() for p in sb_str.split(" / ") if p.strip()}
        added = set_b - set_a
        removed = set_a - set_b
        if added or removed:
            parts = []
            if added:
                parts.append("新增子项：" + "、".join(sorted(added)))
            if removed:
                parts.append("取消子项：" + "、".join(sorted(removed)))
            return "，".join(parts)
        # 子项集合相同但顺序不同 → 落到"取值不同"
    return "取值不同"


# 7 类变化 → 加配/减配方向分类（Task 2 阶梯高亮用）
# P0-3：复合枚举"新增子项"/"取消子项"也接入方向分类——
# 纯新增子项 → 加配；纯取消子项 → 减配；增删并存（"新增子项：X，取消子项：Y"）
# 以"新增子项"打头判加配（与"数值提升"优先判加配同口径；混合行的减配子项在 delta 文本里仍可见）。
_DELTA_ADD = {"新增", "新增（选装）", "升级"}  # 加配方向（含数值提升/新增子项前缀）
_DELTA_REMOVE = {"取消", "降级"}             # 减配方向（含数值下降/取消子项前缀）


def _is_add(delta: str) -> bool:
    return delta in _DELTA_ADD or delta.startswith("数值提升") or delta.startswith("新增子项")


def _is_remove(delta: str) -> bool:
    return delta in _DELTA_REMOVE or delta.startswith("数值下降") or delta.startswith("取消子项")


def _suggest_pairs(specs_a: list[dict], specs_b: list[dict]) -> list[dict]:
    """建议连线：命名 token 重叠（价格不参与——快照无指导价字段，确认后由前端传）。
    specs_a/b: [{spec_id, name}]。贪心匹配：每个 A 找重叠 token 最多的 B，已配 B 不复用。"""
    pairs = []
    used_b = set()
    for a in specs_a:
        best_b, best_score = None, -1
        a_tokens = set(a["name"].split())
        for b in specs_b:
            if b["spec_id"] in used_b:
                continue
            b_tokens = set(b["name"].split())
            score = len(a_tokens & b_tokens)  # 仅命名相似
            if score > best_score:
                best_b, best_score = b, score
        # P1-10：零共同 token（best_score==0）不强配——无依据的连线会误导用户。
        # 门槛 > 0：至少 1 个共同 token 才配对。
        if best_b is not None and best_score > 0:
            used_b.add(best_b["spec_id"])
            pairs.append({"spec_a": a["spec_id"], "name_a": a["name"],
                          "spec_b": best_b["spec_id"], "name_b": best_b["name"],
                          "suggested": True})
    return pairs


# ---------- 字体加密丢字检测（P1-9/P2-26） ----------

# 残缺字段名集合：v7 时代 _FIELD_NAME_RESTORE（手写 (类目,残缺名)→完整名 表）的
# 副产物——取「残缺名 ≠ 完整名」的残缺名作为已知丢字模式。dashboard-v10 Task 6.1
# 删除 _FIELD_NAME_RESTORE 字典（v9 字体解码稳定后 _restore_field_name 不再走该
# 兜底分支），本检测集是唯一仍需这些残缺名模式的消费者，故以冻结字面量形式下沉到
# 此处（诊断资产，非还原机制）。v9 解码后新快照字段名完整，本集合对老快照（pre-v9
# 采集）仍能检出残留丢字；新快照命中数为 0（符合预期）。
_CORRUPT_FIELD_NAMES: frozenset[str] = frozenset({
    # 基本参数
    "车型", "厂", "厂()", "上市", "整车", "(kg)", "首任车主政策",
    # 车身
    "(mm)", "(个)", "后备厢(L)", "阻系数(Cd)",
    # 电池/充电
    "功能", "电池(小时)", "电池范围(%)", "百公里耗(kWh/100km)", "位置",
    "功率(kW)",
    # 变速箱
    "简称",
    # 底盘转向
    "前类型", "类型",
    # 车轮制动
    "类型2", "类型3", "驻车类型", "驻车类型2",
    # 被动安全
    "主/副驾驶座安全", "/侧", "/头部(气帘)",
    # 驾驶硬件
    "/后雷达", "数量", "辅助", "方感知",
    # 驾驶功能
    "卫星航系统", "航路况信息显示",
    # 外观/防盗
    "轮圈", "启动系统", "进入功能", "电池预",
    # 灯光
    "光源", "车雾灯", "大灯可调", "自应远近光",
    # 天窗/玻璃
    "/后电动车窗", "车窗一键降功能", "侧隐私玻璃",
    # 互联/智能化
    "/车载", "应用店",
    # 车内充电
    "多媒体/充电", "USB/Type-C数量",
    # 座椅
    "座椅", "主/副驾驶座电动", "/后扶手", "杯架", "主座椅方式", "副座椅方式",
    "排座椅功能",
    # 音响
    "品牌",
    # 空调
    "空调", "后座出口",
})


def _corrupt_field_names() -> set[str]:
    """残缺字段名集合（已知丢字模式）。v10 Task 6.1 后改为模块级冻结字面量，
    不再从 autohome_api._FIELD_NAME_RESTORE 派生（该字典已删）。"""
    return set(_CORRUPT_FIELD_NAMES)



# 残缺值模式：之家字体加密偶发吃掉值里的字。
# - 通盘式（应为「通风盘式」，吃「风」）
# - 质保值「六15公里」「四8公里」等（应为「六年或15万公里」，吃「年或…万」）：
#   中文数字 + 阿拉伯数字 + 「公里」但缺「年」「万」。
_CORRUPT_VALUE_PATTERNS = [
    (re.compile(r"通盘式"), "通盘式"),
    (re.compile(r"[一二三四五六七八九十]\d+公里"), "质保缺年/万"),
]


def _detect_font_corruption(cats: dict) -> dict:
    """扫描快照 categories 检测字体加密丢字（P1-9/P2-26）。

    检测两路：
    1. 字段名残缺：任一参数名命中 _CORRUPT_FIELD_NAMES（残缺名≠完整名的已知丢字模式）。
    2. 值残缺：参数值命中 _CORRUPT_VALUE_PATTERNS（通盘式 / 质保缺年万 等）。

    返回 {"n": 命中数, "field_hits": int, "value_hits": int, "samples": [str]}。
    n 用于 font_corrupted_n 披露计数；samples 供调试/前端提示（限 8 条）。
    """
    bad_names = _corrupt_field_names()
    field_hits = 0
    value_hits = 0
    samples: list[str] = []
    for cat, params in (cats or {}).items():
        for pname, pv in (params or {}).items():
            if pname in bad_names:
                field_hits += 1
                if len(samples) < 8:
                    samples.append(f"字段:{cat}/{pname}")
            # 取标量值做模式检测（dict 取各 spec 值；list 取 name）
            vals = []
            if isinstance(pv, dict):
                vals = list(pv.values())
            elif isinstance(pv, (str, int, float)):
                vals = [pv]
            elif isinstance(pv, list):
                vals = [it.get("name", "") for it in pv if isinstance(it, dict)]
            for v in vals:
                if not isinstance(v, str) or not v:
                    continue
                for pat, label in _CORRUPT_VALUE_PATTERNS:
                    if not pat.search(v):
                        continue
                    # 「通盘式」恒为丢字；质保模式还须缺「年」「万」才算残缺
                    if label == "通盘式" or ("万" not in v and "年" not in v):
                        value_hits += 1
                        if len(samples) < 8:
                            samples.append(f"值:{pname}={v}")
                        break
    return {"n": field_hits + value_hits, "field_hits": field_hits,
            "value_hits": value_hits, "samples": samples}




