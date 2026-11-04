"""市场看板查询层（specs/market-dashboard v7：单源单表）。

数据来源：CAM 分版型监测 Excel（scripts/import_sales_excel.py 导入）的唯一 Sheet。
- sales_trim：版型级（唯一数据源），month 原文如"8月末"，月份标签 f"{year}-{month}"
- 车系视角（销量/价格/优惠/结构）一律由 sales_trim 按 series 聚合得到：
  车系销量 = SUM(retail)；车系价格 = 零售加权 SUM(tp*retail)/SUM(retail)。
  旧 sales_series_weighted（加权表）与 series_alias（跨表归一表）已于 v7 退役。

月份排序口径：解析 month 前导数字 + 中/末后缀（"10月末" > "10月中" > "9月中"）。
所有函数空库/无匹配时返回空结构（不编造）。
"""
from __future__ import annotations

import re

from sqlalchemy import case, func, select

from src.models.orm import SalesTrim
from src.storage.db import session_scope

_MONTH_RE = re.compile(r"(\d+)")


def _month_key(month_str: str) -> tuple:
    """'10月末' → (10, 1)；'1月中' → (1, 0)；无后缀 '1' → (1, 0)。
    同数字内 中 < 末（月末是当月更晚的快照）。"""
    m = _MONTH_RE.search(str(month_str or ""))
    num = int(m.group(1)) if m else 0
    tail = 1 if "末" in str(month_str or "") else 0
    return (num, tail)


def _month_label(year: int, month: str) -> str:
    return f"{year}-{month}"


def _split_month_label(label: str) -> tuple[int, str] | None:
    """'2025-10月中' → (2025, '10月中')。"""
    if not label or "-" not in label:
        return None
    y, _, m = label.partition("-")
    try:
        return int(y), m
    except ValueError:
        return None


def _series_names(series_name: str) -> list[str]:
    """车系名匹配（v7 单表化）：对 sales_trim.series 做**精确 IN 匹配**，
    防 LIKE 串系（P0-4：选"汉"不并入"汉L"）。

    旧实现为 `_series_names_by_key`：name → series_alias.series_key → 该 key 下
    指定 source 的所有 raw_name（跨表归一，把主表"吉利星愿"映射到加权表"星愿"）。
    v7 退役 series_alias 与加权表后，车系视角**全部来自 sales_trim 单表**，
    归一层已无存在意义（同表内车系名一致），故直接精确单名匹配。
    保留"返回 list"的调用契约（调用方统一用 `.in_(names)`），未命中由 IN 自然落空；
    空/空白名 → 返回 []（避免 IN 空串误匹配）。
    """
    n = str(series_name or "").strip()
    return [n] if n else []


def _weighted_avg(col):
    """零售加权月度均值 SQL 表达式：SUM(col*retail) / SUM(retail)。

    分母只累加**该字段非空行**的 retail（分子同批行），避免未定价版型把均价稀释；
    分母全空或为 0 → NULL（不编造 0，由调用方转 None）。
    用于：车系 TP / MSRP 的零售加权（v7 价格统一口径）。
    """
    return func.sum(col * SalesTrim.retail) / func.sum(
        case((col.isnot(None), SalesTrim.retail), else_=None))


def _latest_retail_month_rows(session) -> list:
    """最新"有零售数"月份的底层查询（P3-30：复用调用方 session，避免嵌套 session_scope）。
    返回 [(year, month, sum_retail)] 全量月份行，由调用方归一为 label。"""
    return session.execute(
        select(SalesTrim.year, SalesTrim.month, func.sum(SalesTrim.retail))
        .group_by(SalesTrim.year, SalesTrim.month)
    ).fetchall()


def _rows_to_latest_retail_month(rows) -> str | None:
    """[(year, month, sum_retail)] → 最新有零售月 label（无零售回退最新月；空→None）。"""
    if not rows:
        return None
    have = [(r[0], r[1]) for r in rows if r[2] is not None]
    y, m = max(have or [(r[0], r[1]) for r in rows],
               key=lambda r: (r[0],) + _month_key(r[1]))
    return _month_label(y, m)


def latest_retail_month() -> str | None:
    """最新"有零售数"的月份标签（CAM 月中快照的零售数滞后到月末文件才填，
    最新月常为空）。全库无零售 → 回退最新月；空库 → None。"""
    with session_scope() as s:
        rows = _latest_retail_month_rows(s)
    return _rows_to_latest_retail_month(rows)


# ---------------------------------------------------------------- 车系列表

def market_series_list() -> list[dict]:
    """车系下拉（v7 单表）：主表**最新有零售月**的 DISTINCT series（带当月零售合计）。
    返回 [{"series": name, "latest_retail": n, "has_retail": bool, "has_weighted": bool}]，
    按零售降序。has_retail=主表当月有该 series 零售数据（销量模块可用）。

    has_weighted：**键名沿用旧契约（前端不改动）**，v7 语义改为"当月该车系存在
    TP 数据（终端价模块可用）"——旧值来自已退役的加权表，新值来自版型表 tp 非空行。
    v7 去掉了"主表 ∪ 加权表"的并集：下拉只含版型表车系，同月同车系名一致，
    旧的"零跑 B10 / 零跑B10"双 key 重复问题（两表名不一致 + alias 归一）随之消失。
    """
    with session_scope() as s:
        # P3-30：复用本 session 算最新零售月，避免嵌套 session_scope
        label = _rows_to_latest_retail_month(_latest_retail_month_rows(s))
        latest_retail: dict[str, float | None] = {}
        priced: set[str] = set()
        if label is not None:
            y, m = _split_month_label(label)
            latest_retail = {
                r[0]: r[1] for r in s.execute(
                    select(SalesTrim.series, func.sum(SalesTrim.retail))
                    .where(SalesTrim.year == y, SalesTrim.month == m,
                           SalesTrim.series.isnot(None))
                    .group_by(SalesTrim.series)
                ).fetchall()}
            priced = {r[0] for r in s.execute(
                select(SalesTrim.series).distinct()
                .where(SalesTrim.year == y, SalesTrim.month == m,
                       SalesTrim.series.isnot(None), SalesTrim.tp.isnot(None))
            ).fetchall() if r[0]}
    names = set(latest_retail)
    return [{"series": n, "latest_retail": latest_retail.get(n),
             "has_retail": latest_retail.get(n) is not None,
             "has_weighted": n in priced} for n in
            sorted(names, key=lambda n: (-(latest_retail.get(n) or 0), n))]


def market_series_all() -> list[dict]:
    """竞品对比候选（2026-10 改造）：**全库有数据的车系**（不限最新月）。

    旧 market_series_list 只取"最新有零售月"的 DISTINCT series，导致历史月有数据、
    最新月无数据的车系（全库 1472 vs 最新月 1149，缺约 22%）在竞品对比里选不到。
    此函数放开为全库车系：latest_retail 取该车系**自身最新有零售月**的零售合计
    （无任何零售 → None），保持与 market_series_list 一致的返回结构（前端可复用），
    按 latest_retail 降序。仅用于竞品对比候选，不改动顶部车系下拉口径。
    """
    with session_scope() as s:
        names = [r[0] for r in s.execute(
            select(SalesTrim.series).distinct()
            .where(SalesTrim.series.isnot(None))
        ).fetchall() if r[0]]
        # 每车系自身最新"有零售"月的零售合计（同月多版型先聚合）
        rows = s.execute(
            select(SalesTrim.series, SalesTrim.year, SalesTrim.month,
                   func.sum(SalesTrim.retail))
            .where(SalesTrim.series.isnot(None), SalesTrim.retail.isnot(None))
            .group_by(SalesTrim.series, SalesTrim.year, SalesTrim.month)
        ).fetchall()
        priced = {r[0] for r in s.execute(
            select(SalesTrim.series).distinct().where(SalesTrim.tp.isnot(None))
        ).fetchall() if r[0]}
    latest: dict[str, tuple] = {}
    for name, y, m, total in rows:
        key = (y,) + _month_key(m)
        cur = latest.get(name)
        if cur is None or key > cur[0]:
            latest[name] = (key, total)
    out = [{"series": n,
            "latest_retail": latest[n][1] if n in latest else None,
            "has_retail": n in latest,
            "has_weighted": n in priced} for n in names]
    out.sort(key=lambda r: (-(r["latest_retail"] or 0), r["series"]))
    return out


# ---------------------------------------------------------------- 跨车系筛选（人工题集转金标 Block 0）

# energy 枚举映射（写死端点，agent 只传枚举，不收库内原文）。
# ICE 语义=用户期望锚："燃油"=传统能源+油电混合（人工题集第9行拍板）。
ENERGY_ENUMS = {
    "BEV": ("纯电动",),
    "PHEV": ("插电式混合", "增程式混合"),
    "NEV": ("纯电动", "插电式混合", "增程式混合", "燃料电池"),
    "ICE": ("传统能源", "油电混合"),
}


def market_series_filter(kw=None, brand=None, energy=None, level=None,
                         price_min=None, price_max=None, wheelbase_min=None,
                         wheelbase_max=None, limit=50) -> dict:
    """跨车系筛选（人工题集转金标 Block 0）：全库车系按属性过滤 + 零售降序。

    基础集＝全库车系（同 market_series_all 口径，含无零售车系如风云T7，
    latest_retail=None）。每车系**两锚分离**（防 T7 形态丢行）：
    - 属性锚月＝该车系自身最新月（year + _month_key 排序，无视零售空否）→
      该月行 energy/level/wheelbase/brand 取非空众数、msrp 取非空 min/max；
    - 零售锚月＝自身最新**有零售**月合计（无则 None，同 market_series_all）。
    过滤全闭区间：价格=车系 [msrp_min, msrp_max] 与查询区间**重叠即命中**
    （"±1万"这类容差属题面层，端点只做通用重叠）；wheelbase=众数落区间内；
    level 精确匹配（A ≠ A0/A00）；kw 去空格包含（既有惯例）；
    brand=锚月 brand 子品牌 OR manufacturer 集团众数**任一**去空格包含
    （Excel 奇瑞题集团语义，2026-10-13 拍板 B：CAM brand 列是子品牌粒度，
    "奇瑞的电车"需 manufacturer='奇瑞汽车' 才能命中 风云/iCAR/QQ 系）；
    energy 只收 ENERGY_ENUMS 锚枚举（非法抛 ValueError，路由层转 400）。
    返回 {rows, total_matched, total_library, _meta}，latest_retail 降序
    （None 最后）再按名；limit 截断由路由层附 _truncated（线B模式）。
    """
    if energy is not None and energy not in ENERGY_ENUMS:
        raise ValueError(
            f"energy 非法枚举：{energy}（可选：{'/'.join(ENERGY_ENUMS)}）")
    kw_clean = re.sub(r"\s+", "", str(kw or ""))
    brand_clean = re.sub(r"\s+", "", str(brand or ""))
    energy_types = ENERGY_ENUMS.get(energy)  # None=未传，不过滤
    with session_scope() as s:
        # 属性锚月候选：全部车系及其出现过的月份（无视零售空否）
        month_rows = s.execute(
            select(SalesTrim.series, SalesTrim.year, SalesTrim.month).distinct()
            .where(SalesTrim.series.isnot(None))
        ).fetchall()
        # 零售锚：每车系自身最新有零售月的合计（同 market_series_all）
        retail_rows = s.execute(
            select(SalesTrim.series, SalesTrim.year, SalesTrim.month,
                   func.sum(SalesTrim.retail))
            .where(SalesTrim.series.isnot(None), SalesTrim.retail.isnot(None))
            .group_by(SalesTrim.series, SalesTrim.year, SalesTrim.month)
        ).fetchall()

        # 属性锚月聚合：energy/level/wheelbase/brand 按值计数（Python 端取众数），
        # msrp 直接 SQL min/max——分组行数远小于全表，避免拉全量版型行
        def _value_counts(col):
            return s.execute(
                select(SalesTrim.series, SalesTrim.year, SalesTrim.month, col,
                       func.count())
                .where(SalesTrim.series.isnot(None), col.isnot(None))
                .group_by(SalesTrim.series, SalesTrim.year, SalesTrim.month, col)
            ).fetchall()

        energy_rows = _value_counts(SalesTrim.energy_type)
        level_rows = _value_counts(SalesTrim.level)
        wheel_rows = _value_counts(SalesTrim.wheelbase_mm)
        brand_rows = _value_counts(SalesTrim.brand)
        mfr_rows = _value_counts(SalesTrim.manufacturer)
        msrp_rows = s.execute(
            select(SalesTrim.series, SalesTrim.year, SalesTrim.month,
                   func.min(SalesTrim.msrp), func.max(SalesTrim.msrp))
            .where(SalesTrim.series.isnot(None), SalesTrim.msrp.isnot(None))
            .group_by(SalesTrim.series, SalesTrim.year, SalesTrim.month)
        ).fetchall()
        priced = {r[0] for r in s.execute(
            select(SalesTrim.series).distinct()
            .where(SalesTrim.series.isnot(None), SalesTrim.tp.isnot(None))
        ).fetchall() if r[0]}

    # 每车系属性锚月（自身最新月，无视零售）与零售锚月（最新有零售月）
    anchor: dict[str, tuple] = {}
    for name, y, m in month_rows:
        key = (y,) + _month_key(m)
        if key > anchor.get(name, ()):
            anchor[name] = key

    def _mode_at(count_rows) -> dict:
        """[(series, year, month, value, cnt)] → {series: 锚月众数值}。
        同计数并列取值升序（确定性）；锚月无非空值 → 不在返回 dict（视为 None）。"""
        best: dict[str, tuple] = {}
        for name, y, m, val, cnt in count_rows:
            if (y,) + _month_key(m) != anchor.get(name):
                continue
            cand = (-cnt, val)
            cur = best.get(name)
            if cur is None or cand < cur[0]:
                best[name] = (cand, val)
        return {n: v[1] for n, v in best.items()}

    energy_mode = _mode_at(energy_rows)
    level_mode = _mode_at(level_rows)
    wheel_mode = _mode_at(wheel_rows)
    brand_mode = _mode_at(brand_rows)
    mfr_mode = _mode_at(mfr_rows)
    msrp_at: dict[str, tuple] = {}
    for name, y, m, lo, hi in msrp_rows:
        if (y,) + _month_key(m) == anchor.get(name):
            msrp_at[name] = (lo, hi)
    latest: dict[str, tuple] = {}
    for name, y, m, total in retail_rows:
        key = (y,) + _month_key(m)
        cur = latest.get(name)
        if cur is None or key > cur[0]:
            latest[name] = (key, total)

    rows = []
    for name in anchor:
        e_val = energy_mode.get(name)
        lv = level_mode.get(name)
        wb = wheel_mode.get(name)
        lo, hi = msrp_at.get(name, (None, None))
        if kw_clean and kw_clean not in re.sub(r"\s+", "", name):
            continue
        if brand_clean:
            # 拍板 B：子品牌 brand 或集团 manufacturer 锚月众数**任一**包含即命中
            # （合资厂如 奇瑞捷豹路虎 也会被"奇瑞"命中，精确排除属题面层）
            b_val = brand_mode.get(name)
            m_val = mfr_mode.get(name)
            b_hit = bool(b_val) and brand_clean in re.sub(r"\s+", "", str(b_val))
            m_hit = bool(m_val) and brand_clean in re.sub(r"\s+", "", str(m_val))
            if not (b_hit or m_hit):
                continue  # 两众数均不含/均无非空值 → 不命中（不编造）
        if energy_types is not None and e_val not in energy_types:
            continue
        if level and lv != level:  # 精确匹配（A ≠ A0/A00）
            continue
        if price_min is not None or price_max is not None:
            if lo is None or hi is None:
                continue  # 锚月无 msrp 数据，不编造、不误命中
            if price_max is not None and lo > price_max:
                continue
            if price_min is not None and hi < price_min:
                continue
        if wheelbase_min is not None or wheelbase_max is not None:
            if wb is None:
                continue
            if wheelbase_min is not None and wb < wheelbase_min:
                continue
            if wheelbase_max is not None and wb > wheelbase_max:
                continue
        rows.append({"series": name,
                     "latest_retail": latest[name][1] if name in latest else None,
                     "has_retail": name in latest,
                     "has_weighted": name in priced,
                     "energy": e_val, "level": lv,
                     "msrp_min": lo, "msrp_max": hi, "wheelbase": wb})
    rows.sort(key=lambda r: (r["latest_retail"] is None,
                             -(r["latest_retail"] or 0), r["series"]))
    return {"rows": rows[:max(1, limit)], "total_matched": len(rows),
            "total_library": len(anchor),
            "_meta": {"source": "prism-dashboards/market/series-filter",
                      "semantics": (
                          "属性取车系自身最新月（无视零售空否）行聚合："
                          "energy/level/wheelbase/brand=非空众数，"
                          "msrp_min/max=非空 min/max；"
                          "latest_retail=车系自身最新有零售月合计（无则 null）。"
                          "价格=车系[msrp_min,msrp_max]与查询区间闭区间重叠即命中，"
                          "wheelbase/价格区间均闭区间；level 精确匹配；"
                          "brand=子品牌或集团 manufacturer 锚月众数任一去空格"
                          "包含匹配（含合资如 奇瑞捷豹路虎，"
                          "如需排除请在题面层用更精确词）。"
                          "energy 枚举映射：BEV=纯电动；PHEV=插电式混合+增程式混合；"
                          "NEV=纯电动+插电式混合+增程式混合+燃料电池；"
                          "ICE=传统能源+油电混合。")}}


# ---------------------------------------------------------------- 单车系趋势

def series_trend(series_name: str) -> dict:
    """月度 TP/MSRP/优惠（版型表，**零售加权**，按年+月排序；车系名精确匹配）。

    v7 口径：tp = SUM(tp*retail)/SUM(retail)（分母只累加 tp 非空行的 retail），
    msrp 同理；分母全空/为 0 → None（不编造）。
    **仅取月末行**：月中快照零售数未发布（retail 为 NULL）→ 加权价必为 NULL，
    若纳入会让月份轴出现空洞；统一取月末，与看板"仅月末"口径一致，也复现旧
    加权表"每月一个值"的轴形态。
    discount = msrp - tp（任一缺失 → None，不编造）。
    """
    out = {"series": series_name, "months": [], "tp": [], "msrp": [], "discount": []}
    names = _series_names(series_name)
    if not names:
        return out
    with session_scope() as s:
        rows = s.execute(
            select(SalesTrim.year, SalesTrim.month,
                   _weighted_avg(SalesTrim.tp), _weighted_avg(SalesTrim.msrp))
            .where(SalesTrim.series.in_(names), SalesTrim.month.like("%末"))
            .group_by(SalesTrim.year, SalesTrim.month)
        ).fetchall()
    rows.sort(key=lambda r: (r[0],) + _month_key(r[1]))
    for y, m, tp, msrp in rows:
        out["months"].append(_month_label(y, m))
        out["tp"].append(round(tp, 0) if tp is not None else None)
        out["msrp"].append(round(msrp, 0) if msrp is not None else None)
        out["discount"].append(round(msrp - tp, 0)
                               if (msrp is not None and tp is not None) else None)
    return out


def retail_trend(series_name: str) -> dict:
    """月度零售数（主表 series 按 series_key 精确 IN，GROUP BY 年+月）+ 最新有零售月 top 版型明细。
    返回 {"months": [...], "retail": [...], "top_trims": [{model_name, retail, mix}]}。
    月中快照零售数未发布 → 该月 retail 为 None（不编造 0）。
    series 精确 IN 匹配（防 LIKE 串系 P0-4：选"汉"不并入"汉L"）。"""
    out = {"months": [], "retail": [], "top_trims": []}
    names = _series_names(series_name)
    if not names:
        return out
    with session_scope() as s:
        rows = s.execute(
            select(SalesTrim.year, SalesTrim.month, func.sum(SalesTrim.retail))
            .where(SalesTrim.series.in_(names))
            .group_by(SalesTrim.year, SalesTrim.month)
        ).fetchall()
    rows.sort(key=lambda r: (r[0],) + _month_key(r[1]))
    for y, m, total in rows:
        out["months"].append(_month_label(y, m))
        out["retail"].append(total)  # None=当期零售未发布
    with_retail = [r for r in rows if r[2] is not None]
    if not with_retail:
        return out
    y, m, _ = with_retail[-1]
    # names 跨 session 复用（list 不依赖 session）：避免二次 _series_names 重复查询
    with session_scope() as s:
        trims = s.execute(
            select(SalesTrim.model_name, SalesTrim.retail, SalesTrim.mix)
            .where(SalesTrim.series.in_(names),
                   SalesTrim.year == y, SalesTrim.month == m,
                   SalesTrim.retail.isnot(None))
            .order_by(SalesTrim.retail.desc())
            .limit(10)
        ).fetchall()
    out["top_trims"] = [{"model_name": t[0], "retail": t[1],
                         "mix": t[2] if t[2] is not None else None} for t in trims]
    return out


# ---------------------------------------------------------------- 竞品对比

def peer_compare(series_names: list[str], metric: str = "tp") -> dict:
    """2-4 车系月度对比（版型表；仅月末）。metric ∈ tp/msrp/discount/retail。
    车系名精确 IN 匹配（v7 单表后同表内车系名一致，无需跨表归一）。
    价格口径（tp/msrp）为**零售加权**：SUM(col*retail)/SUM(retail)，分母只累加该字段
    非空行的 retail；discount = msrp - tp（任一缺失 → None）。
    2026-10 新增 retail：月度零售合计 SUM(retail)（竞品对比不再局限于价格，也看销量）。
    返回 {"series": [...], "months": [...], "data": {name: [values]}}，缺月为 None。"""
    names = [n for n in series_names if n][:4]
    out = {"series": names, "months": [], "data": {n: [] for n in names}}
    if len(names) < 2:
        return out
    if metric not in ("tp", "msrp", "discount", "retail"):
        metric = "tp"
    per_series: dict[str, dict[str, float | None]] = {}
    all_months: set[str] = set()
    with session_scope() as s:
        for name in names:
            rows = s.execute(
                select(SalesTrim.year, SalesTrim.month,
                       _weighted_avg(SalesTrim.tp), _weighted_avg(SalesTrim.msrp),
                       func.sum(SalesTrim.retail))
                .where(SalesTrim.series.in_(_series_names(name)),
                       SalesTrim.month.like("%末"))
                .group_by(SalesTrim.year, SalesTrim.month)
            ).fetchall()
            pts = {}
            for y, m, tp, msrp, retail in rows:
                if metric == "retail":
                    v = float(retail) if retail is not None else None
                elif metric == "tp":
                    v = tp
                elif metric == "msrp":
                    v = msrp
                else:  # discount
                    v = (msrp - tp) if (msrp is not None and tp is not None) else None
                pts[_month_label(y, m)] = round(v, 0) if v is not None else None
                all_months.add(_month_label(y, m))
            per_series[name] = pts
    months = sorted(
        all_months,
        key=lambda lb: (lambda ym: (ym[0],) + _month_key(ym[1]))(
            _split_month_label(lb) or (0, "0")))
    out["months"] = months
    for n in names:
        out["data"][n] = [per_series[n].get(m) for m in months]
    return out


# ---------------------------------------------------------------- 当月聚合

def price_volume_scatter(month: str) -> list[dict]:
    """当月 定位散点：主表按 series 聚合 [{series, tp_avg, wheelbase_avg, retail_sum,
    level, body, energy_type}]。month 为 market_months 的标签（"2025-10月末"）。
    tp_avg = **零售加权** SUM(tp*retail)/SUM(retail)（分母只累加 tp 非空行的 retail）；
    wheelbase_avg = **零售加权** SUM(wheelbase_mm*retail)/SUM(retail)（分母只累加
    wheelbase_mm 非空行的 retail）——2026-10 改造新增：散点横轴由 TP 改轴距(mm)，
    需车系级轴距代表值（同车系跨版型取零售加权平均）；
    键名沿用旧契约（前端不改），月中无零售 → tp_avg/retail_sum 为 None。"""
    ym = _split_month_label(month or "")
    if ym is None:
        return []
    y, m = ym
    with session_scope() as s:
        rows = s.execute(
            select(SalesTrim.series, _weighted_avg(SalesTrim.tp),
                   _weighted_avg(SalesTrim.wheelbase_mm),
                   func.sum(SalesTrim.retail), func.max(SalesTrim.level),
                   func.max(SalesTrim.body), func.max(SalesTrim.energy_type))
            .where(SalesTrim.year == y, SalesTrim.month == m,
                   SalesTrim.series.isnot(None))
            .group_by(SalesTrim.series)
        ).fetchall()
    return [{"series": r[0],
             "tp_avg": round(r[1], 0) if r[1] is not None else None,
             "wheelbase_avg": round(r[2], 0) if r[2] is not None else None,
             "retail_sum": r[3],  # None=当期零售未发布（月中快照）
             "level": r[4],
             "body": r[5],
             "energy_type": r[6]} for r in rows]


def _prev_month_label(month: str) -> str | None:
    """当月标签 → 同口径上一期标签（按 market_months 时间轴回退）。

    month 形如 "2025-10月中"，因 SalesTrim.month 带"中"/"末"后缀，简单 int-1
    无法处理"10月末"→"10月中"或跨年回退。改用全表 DISTINCT 月份时间轴：定位
    当月在升序列表中的下标，再按"同口径"（中→中、末→末）回退到上一个同后缀标签。
    原因：同一月份内有"月中/月末"两期快照，零售数仅"月末"文件发布；若直接取前
    一个标签，"月末"的上一期会落到同月"月中"（零售为空）→ 环比恒为 None。
    无同后缀前驱（如序列最早的"月末"）或当月不在列表 → None。
    """
    months = market_months()
    try:
        idx = months.index(month)
    except ValueError:
        return None
    if idx <= 0:
        return None
    suffix = month[-1:]  # 期次后缀："中" / "末"
    for j in range(idx - 1, -1, -1):
        if months[j].endswith(suffix):
            return months[j]
    return None


def level_summary(month: str) -> dict:
    """级别/能源基础聚合（dashboard-interaction-polish Task 3.1：删环比/结论卡）。

    返回 {"by_level": [{level, avg_tp, total_retail}],
          "by_energy": [{energy, avg_tp, total_retail}]}。

    空库/非法月份返回空结构（不编造）。仅当月聚合，不再产出 mom/prev_retail/conclusion
    ——市场汇总模块已从看板移除，环比结论价值低且与散点重复。
    """
    out: dict = {"by_level": [], "by_energy": []}
    ym = _split_month_label(month or "")
    if ym is None:
        return out
    y, m = ym

    def _agg(col, cy, cm):
        # avg_tp 为**零售加权**（SUM(tp*retail)/SUM(retail)，分母只累加 tp 非空行），
        # 键名沿用旧契约（前端不改）；月中无零售 → avg_tp 为 None。
        with session_scope() as s:
            rows = s.execute(
                select(col, _weighted_avg(SalesTrim.tp), func.sum(SalesTrim.retail))
                .where(SalesTrim.year == cy, SalesTrim.month == cm, col.isnot(None))
                .group_by(col)
            ).fetchall()
        return {r[0]: {"avg_tp": round(r[1], 0) if r[1] is not None else None,
                       "total_retail": r[2]} for r in rows}

    def _rows(cur, label_key):
        return sorted([{label_key: k, **v} for k, v in cur.items()],
                      key=lambda r: -(r["total_retail"] or 0))

    cur_lv = _agg(SalesTrim.level, y, m)
    cur_en = _agg(SalesTrim.energy_type, y, m)
    out["by_level"] = _rows(cur_lv, "level")
    out["by_energy"] = _rows(cur_en, "energy")
    return out


# ---------------------------------------------------------------- 版型结构（v11）

def trim_structure(series_name: str, month: str | None = None) -> dict:
    """版型结构（dashboard-v11 Task 1.3）：单系视角的版型集中度 + 高低配分布 + 优惠有效性。

    - Top1/Top3 版型 mix 占比（sales_trim mix 降序）
    - hi_lo 分布（高配/低配/不区分的零售占比）
    - 优惠 vs 量有效性（discount 与 retail 的相关系数 + 文字说明）

    month=None → 取最新"有零售数"月（与 retail_trend 同口径）。
    空匹配/空库返回空结构（不编造）。
    """
    out = {"series": series_name, "month": None, "top_trims": [],
           "top1_mix": None, "top3_mix": None, "hi_lo_dist": [],
           "discount_vs_retail": {"trims": [], "correlation": None,
                                  "time_series_correlation": None, "note": ""}}
    if not series_name:
        return out
    with session_scope() as s:
        names = _series_names(series_name)
        # 确定目标月：显式 month 优先，否则最新有零售月
        if month:
            ym = _split_month_label(month)
            if ym is None:
                return out
            y, m = ym
        else:
            rows = s.execute(
                select(SalesTrim.year, SalesTrim.month, func.sum(SalesTrim.retail))
                .where(SalesTrim.series.in_(names))
                .group_by(SalesTrim.year, SalesTrim.month)
            ).fetchall()
            have = [(r[0], r[1]) for r in rows if r[2] is not None]
            if not have:
                return out
            y, m = max(have, key=lambda r: (r[0],) + _month_key(r[1]))
        out["month"] = _month_label(y, m)
        trims = s.execute(
            select(SalesTrim.model_name, SalesTrim.retail, SalesTrim.mix,
                   SalesTrim.discount, SalesTrim.tp, SalesTrim.msrp,
                   SalesTrim.hi_lo)
            .where(SalesTrim.series.in_(names), SalesTrim.year == y,
                   SalesTrim.month == m, SalesTrim.retail.isnot(None))
            .order_by(SalesTrim.retail.desc())
        ).fetchall()
        # D15 时间序列相关：近 12 月 discount vs retail 月度聚合的皮尔逊 r（时序口径）
        # 与版型间横截面 r 互补——时序 r 反映"加大优惠→销量升"的历史有效性。
        trend_rows = s.execute(
            select(SalesTrim.year, SalesTrim.month,
                   func.avg(SalesTrim.discount), func.sum(SalesTrim.retail))
            .where(SalesTrim.series.in_(names), SalesTrim.discount.isnot(None),
                   SalesTrim.retail.isnot(None))
            .group_by(SalesTrim.year, SalesTrim.month)
            .order_by(SalesTrim.year.desc(), SalesTrim.month.desc())
            .limit(12)
        ).fetchall()
        if len(trend_rows) >= 3:
            ts_disc = [r[2] for r in trend_rows if r[2] is not None]
            ts_retail = [r[3] for r in trend_rows if r[3] is not None]
            if len(ts_disc) == len(ts_retail) and len(ts_disc) >= 3:
                out["discount_vs_retail"]["time_series_correlation"] = _pearson(ts_disc, ts_retail)
            else:
                out["discount_vs_retail"]["time_series_correlation"] = None
        else:
            out["discount_vs_retail"]["time_series_correlation"] = None
    if not trims:
        return out
    # Top 版型（按 retail 降序；mix 来自源表，不重算）
    out["top_trims"] = [{"model_name": t[0], "retail": t[1],
                         "mix": t[2] if t[2] is not None else None}
                        for t in trims]
    mixes = [t[2] for t in trims if t[2] is not None]
    if mixes:
        out["top1_mix"] = round(max(mixes), 4)
        # top3 = 前 3 个 mix 之和（不足 3 取全部）
        sorted_mix = sorted(mixes, reverse=True)
        out["top3_mix"] = round(sum(sorted_mix[:3]), 4)
    # hi_lo 分布（按零售占比；空 hi_lo 归"不区分"）
    by_hl: dict[str, int] = {}
    total_retail = 0
    for t in trims:
        hl = t[6] if t[6] else "不区分"
        by_hl[hl] = by_hl.get(hl, 0) + (t[1] or 0)
        total_retail += (t[1] or 0)
    out["hi_lo_dist"] = [{"hi_lo": k, "retail": v,
                          "share": round(v / total_retail, 4) if total_retail else 0}
                         for k, v in sorted(by_hl.items(), key=lambda kv: -kv[1])]
    # 优惠 vs 量有效性
    dvr_trims = [{"model_name": t[0], "discount": t[3], "retail": t[1], "mix": t[2]}
                 for t in trims if t[3] is not None]
    out["discount_vs_retail"]["trims"] = dvr_trims
    corr = _pearson([t[3] for t in trims if t[3] is not None and t[1] is not None],
                    [t[1] for t in trims if t[3] is not None and t[1] is not None])
    out["discount_vs_retail"]["correlation"] = corr
    out["discount_vs_retail"]["note"] = _discount_validity_note(corr, dvr_trims)
    return out


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """皮尔逊相关系数（≥3 对才计算，否则 None）。常量列返回 None。"""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 3)


def _discount_validity_note(corr: float | None, trims: list[dict]) -> str:
    """优惠有效性文字说明（数据规则，不编造）。"""
    if corr is None:
        if not trims:
            return "无优惠数据，无法判断优惠对销量的影响。"
        return "版型数不足，无法判断优惠与销量的相关性。"
    if corr > 0.3:
        return f"优惠与销量正相关（r={corr}），加大优惠的版型卖得更多——优惠有效。"
    if corr < -0.3:
        return f"优惠与销量负相关（r={corr}），高优惠版型反而销量低——可能因高配基数小。"
    return f"优惠与销量弱相关（r={corr}），销量主要由版型定位而非优惠幅度驱动。"


# ---------------------------------------------------------------- 结论卡（v11）

def series_insight(series_name: str) -> dict:
    """数据规则生成一句话洞察（dashboard-v11 Task 1.4）。

    - 销量趋势：最近 3 月 vs 前 3 月（↑/↓/持平/未知）
    - TP 稳定性：波动幅度（万元）
    - 主销版型：Top1 mix

    返回 {"series", "sentence", "parts": {sales_trend, tp_stability, top_trim,
    latest_retail, mom_pct, level_share}}。
    数据不足时如实说明，不编造。
    """
    out = {"series": series_name, "sentence": "",
           "parts": {"sales_trend": {"direction": "unknown", "pct": None,
                                     "recent_avg": None, "prev_avg": None},
                     "tp_stability": {"range_wan": None, "stable": None,
                                      "latest_wan": None},
                     "top_trim": None,
                     # 原型 §01 结论卡 4 KPI（additive，不改既有键语义）
                     "latest_retail": {"month": None, "value": None},
                     "mom_pct": None,
                     "level_share": {"level": None, "share": None}}}
    if not series_name:
        out["sentence"] = "请先选择车系。"
        return out
    retail = retail_trend(series_name)
    trend = series_trend(series_name)
    # 销量趋势：取有零售数的月份，last3 vs prev3
    vals = [v for v in retail["retail"] if v is not None]
    if len(vals) >= 6:
        recent = vals[-3:]
        prev = vals[-6:-3]
        ra = sum(recent) / 3
        pa = sum(prev) / 3
        pct = round((ra - pa) / pa * 100, 1) if pa else None
        direction = "up" if (pct or 0) > 5 else "down" if (pct or 0) < -5 else "flat"
        out["parts"]["sales_trend"] = {"direction": direction, "pct": pct,
                                       "recent_avg": round(ra), "prev_avg": round(pa)}
    # TP 稳定性
    tps = [v for v in trend["tp"] if v is not None]
    if tps:
        r_wan = round((max(tps) - min(tps)) / 10000, 2)
        out["parts"]["tp_stability"] = {"range_wan": r_wan,
                                        "stable": r_wan <= 1.0,
                                        "latest_wan": round(tps[-1] / 10000, 1)}
    # 主销版型
    if retail["top_trims"]:
        t0 = retail["top_trims"][0]
        out["parts"]["top_trim"] = {"model_name": t0["model_name"],
                                    "mix": t0["mix"]}
    out["sentence"] = _build_insight_sentence(series_name, out["parts"])
    # 原型 §01 结论卡 4 KPI（additive）：本月零售 / 环比 / 细分份额
    # （第 4 项"终端价 TP"复用上面的 tp_stability.latest_wan）
    pts = [(lbl, v) for lbl, v in zip(retail["months"], retail["retail"])
           if v is not None]
    if pts:
        lbl, val = pts[-1]
        out["parts"]["latest_retail"] = {"month": lbl, "value": int(val)}
        prev_val = pts[-2][1] if len(pts) >= 2 else None
        out["parts"]["mom_pct"] = (round((val - prev_val) / prev_val * 100, 1)
                                   if prev_val else None)
        # 细分份额 = 该车系当月零售 ÷ 同级别（level）当月总零售
        ym = _split_month_label(lbl)
        if ym:
            y0, m0 = ym
            names = _series_names(series_name)
            with session_scope() as s:
                lv = s.execute(
                    select(SalesTrim.level).where(
                        SalesTrim.series.in_(names), SalesTrim.year == y0,
                        SalesTrim.month == m0,
                        SalesTrim.level.isnot(None)).limit(1)).scalar()
                tot = None
                if lv:
                    tot = s.execute(
                        select(func.sum(SalesTrim.retail)).where(
                            SalesTrim.year == y0, SalesTrim.month == m0,
                            SalesTrim.level == lv)).scalar()
            out["parts"]["level_share"] = {
                "level": lv,
                "share": round(val / tot, 4) if (lv and tot) else None}
    return out


def _build_insight_sentence(name: str, parts: dict) -> str:
    """从 parts 组装一句话洞察（数据规则）。"""
    bits = []
    st = parts["sales_trend"]
    if st["direction"] == "up":
        bits.append(f"销量近 3 月环比 ↑{st['pct']}%")
    elif st["direction"] == "down":
        bits.append(f"销量近 3 月环比 ↓{abs(st['pct'])}%")
    elif st["direction"] == "flat":
        bits.append("销量近 3 月环比基本持平")
    else:
        bits.append("销量数据不足 6 月，无法判断趋势")
    tp = parts["tp_stability"]
    if tp["latest_wan"] is not None:
        if tp["stable"]:
            bits.append(f"TP 稳定在 {tp['latest_wan']} 万")
        else:
            bits.append(f"TP 波动较大（幅度 {tp['range_wan']} 万）")
    else:
        bits.append("终端价暂无数据")
    tt = parts["top_trim"]
    if tt and tt["mix"] is not None:
        bits.append(f"主销 {tt['model_name']}（占 {round(tt['mix'] * 100)}%）")
    elif tt:
        bits.append(f"主销 {tt['model_name']}")
    else:
        bits.append("主销版型暂无数据")
    return f"「{name}」：" + "，".join(bits) + "。"


def market_months() -> list[str]:
    """可用月份列表（主表 DISTINCT 年+月，"2025-10月中" 标签，按时间升序）。"""
    with session_scope() as s:
        rows = s.execute(
            select(SalesTrim.year, SalesTrim.month).distinct()).fetchall()
    rows = [(r[0], r[1]) for r in rows if r[1] is not None]
    rows.sort(key=lambda r: (r[0],) + _month_key(r[1]))
    return [_month_label(y, m) for y, m in rows]


def _normalize_trim_name(name: str | None) -> str:
    """版型键去年款前缀（dashboards-tri-polish Q8）：'2025款 标准型'→'标准型'。

    跨月集中度对齐：同版型不同年款前缀（"2025款 X"/"2026款 X"）归一到"X"，
    避免被当作两个版型稀释集中度。None / 空白安全返回空串。
    """
    return re.sub(r"^\d{4}款\s*", "", str(name or "")).strip()


def trim_concentration_trend(series_name: str, months: int = 12) -> dict:
    """版型集中度时间序列（dashboards-tri-polish Q8）：按月算 top1_mix/top3_mix。

    版型键去年款前缀规范化（_normalize_trim_name）对齐跨月——同版型不同年款
    归一到同一键，避免集中度被年款前缀稀释。空匹配/空库返回 {months: []}（不编造）。
    """
    out = {"months": []}
    if not series_name:
        return out
    with session_scope() as s:
        names = _series_names(series_name)
        # 取最近 months*50 行（每月版型数上限兜底），按年月倒序
        rows = s.execute(
            select(SalesTrim.year, SalesTrim.month, SalesTrim.model_name,
                   SalesTrim.retail)
            .where(SalesTrim.series.in_(names), SalesTrim.retail.isnot(None))
            .order_by(SalesTrim.year.desc(), SalesTrim.month.desc())
            .limit(months * 50)
        ).fetchall()
    if not rows:
        return out
    by_month: dict[tuple, list] = {}
    for r in rows:
        by_month.setdefault((r[0], r[1]), []).append({
            "name": _normalize_trim_name(r[2]),
            "retail": r[3] or 0,
        })
    # 时间轴从旧到新（左→右递增）：升序排序后取最近 N 个月（末尾 N 个）。
    # 旧实现 reverse=True + [:months] 取最近 N 个月但顺序新→旧（时间轴反转）。
    for key in sorted(by_month.keys(), key=lambda k: (k[0],) + _month_key(k[1]),
                      reverse=False)[-months:]:
        trims = by_month[key]
        merged: dict[str, int] = {}
        total = 0
        for t in trims:
            merged[t["name"]] = merged.get(t["name"], 0) + t["retail"]
            total += t["retail"]
        if not total:
            continue
        shares = sorted(merged.values(), reverse=True)
        top1 = shares[0] / total
        top3 = sum(shares[:3]) / total
        out["months"].append({
            "month": f"{key[0]}年{key[1]}",
            "top1_mix": round(top1, 4),
            "top3_mix": round(top3, 4),
        })
    return out


def market_data_freshness() -> dict:
    """数据时效（P1-12）：覆盖月份范围 + 最后导入时间（代理口径）。
    返回 {"month_range": "2025-8月中 ~ 2026-9月中" 或 None（空库）,
          "latest_month": "2026-9月中" 或 None,
          "imported_at": None}。
    imported_at：sales_trim 无 fetched/updated 字段，用最新月份（MAX year+month 排序）
    代理"最后导入时间"——即最近一次导入写入的最新数据批次月份。空库返回全 None。"""
    months = market_months()
    if not months:
        return {"month_range": None, "latest_month": None, "imported_at": None}
    return {"month_range": f"{months[0]} ~ {months[-1]}",
            "latest_month": months[-1],
            "imported_at": months[-1]}
