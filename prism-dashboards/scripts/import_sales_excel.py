"""CAM 分版型监测 Excel → 单表落库（specs/market-dashboard v7：单源单表）。

源文件：CAM终端分版型监测-YYYY年M月末.xlsx，**唯一 Sheet**（27 列，版型级）：
车型编号/年/月/制造商/品牌/车系/车型级别/车身形式/排量/变速箱形式/新能源分类/
座位数/驱动形式/燃油种类/合资·自主·进口/纯电动工况续航里程/车型版本/长/轴距/
上市日期/生产状态/车型名称/MSRP/TP/优惠幅度/Mix/分版型零售数。
落库目标：sales_trim（版型级，主键 车型编号+年+月）。

用法（CLI）：
    python scripts/import_sales_excel.py <xlsx路径>

用法（模块，market_routes 上传端点复用）：
    from scripts_import import ...  # 不存在——用 importlib 加载本文件（scripts/ 非包）
    stats = import_workbook(path)

设计要点（v7 单表化）：
- **单源单表**：不再解析"加权表"（旧 sales_series_weighted 已废），也不再维护
  series_alias 归一表；车系视角一律由版型表按 series 聚合得到（车系销量 =
  SUM(retail) GROUP BY (series, year, month)）。
- openpyxl read_only=True：10 万行级，普通模式全量载入会 OOM。
- 表头容错：核心列 contains 匹配（"分版型零售数"contains"零售"），缺核心列 raise ValueError。
- 数值容错：MSRP/TP/零售 空或非数值 → None（不编造 0）。
- upsert：ON CONFLICT DO UPDATE（SQLite 主键命中→整行覆盖更新）。
- is_main 派生：新源表无"是否主销"列，导入后按 (车系,年,月) 内 **Mix 最高行**
  回填 is_main='是'（无 Mix 时退化为 retail 最高行）——与配置页 main_trim_spec_id
  既有的"取 mix 最大者"tie-break 语义一致，纯派生不猜数据。
- 统计口径：inserted/updated 以"该 PK 落库前是否已存在"计（导入前一次性预载
  现存 PK 集合），而非 SQLite rowcount（ON CONFLICT 不区分插改）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import openpyxl
from sqlalchemy import func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

# 统一走项目库（scripts/ 无包结构，CLI 直跑时把项目根加进 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models.orm import SalesTrim  # noqa: E402

# ---- 表头匹配规则（exact 优先，contains 兜底；排除名用于歧义列）----
# (ORM 列, 精确候选, contains 候选, 排除子串)
_TRIM_HEADER_RULES = [
    ("model_code", ["车型编号"], ["车型编号"], []),
    ("year", ["年"], ["年"], ["年款", "年份"]),
    ("month", ["月"], ["月"], ["月份"]),
    ("manufacturer", ["制造商"], ["制造商"], []),
    ("brand", ["品牌"], ["品牌"], []),
    ("series", ["车系"], ["车系"], []),
    ("level", ["车型级别"], ["级别"], ["级别(奇瑞)"]),
    ("body", ["车身形式"], ["车身"], []),
    ("displacement", ["排量"], ["排量"], []),
    ("gearbox", ["变速箱形式"], ["变速箱"], []),
    ("energy_type", ["新能源分类"], ["能源"], []),
    ("seats", ["座位数"], ["座位"], []),
    ("drive", ["驱动形式"], ["驱动"], []),
    ("fuel", ["燃油种类"], ["燃油种类"], ["燃料"]),
    ("origin", ["合资/自主/进口"], ["合资/自主/进口"], []),
    ("ev_range", ["纯电动工况续航里程（KM）"], ["续航里程"], []),
    ("version", ["车型版本"], ["车型版本"], []),
    ("pre_msrp", ["调价前MSRP"], ["调价前"], []),
    ("length_mm", ["长(mm)"], ["长(mm"], []),
    ("wheelbase_mm", ["轴距(mm)"], ["轴距"], []),
    ("launch_date", ["上市日期"], ["上市"], []),
    ("prod_status", ["生产状态"], ["生产状态"], []),
    ("model_name", ["车型名称"], ["车型名称"], []),
    ("msrp", ["MSRP"], ["MSRP"], ["调价前"]),   # 排除"调价前MSRP"
    ("tp", ["TP"], ["TP"], []),
    ("discount", ["优惠幅度"], ["优惠"], []),
    ("mix", ["Mix"], ["Mix"], []),
    ("retail", ["分版型零售数"], ["零售"], []),
    ("is_main", ["是否主销"], ["主销"], []),
    ("hi_lo", ["高/低配"], ["高/低配"], []),
]
# 缺失即 raise 的核心列
_TRIM_REQUIRED = ("model_code", "year", "month", "msrp", "tp", "retail")

_NUM_NONE = {"", "-", "—", "无", "N/A", "NA", "/", "None"}


def _num(v) -> float | None:
    """数值容错：空/占位符/非数值 → None（不编造 0）。"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s.upper() in {x.upper() for x in _NUM_NONE} or not s:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _int(v) -> int | None:
    f = _num(v)
    if f is None:
        return None
    try:
        return int(f)
    except (ValueError, OverflowError):
        return None


def _str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s not in _NUM_NONE and s != "" else None


def _match_headers(header_row, rules) -> dict[str, int]:
    """按规则把表头行映射成 {ORM列: 列号}。exact 优先、contains 兜底。"""
    headers = [str(c).strip() if c is not None else "" for c in header_row]
    out: dict[str, int] = {}
    used: set[int] = set()
    # 第一遍：精确匹配（MSRP vs 调价前MSRP 这类歧义靠精确命中解决）
    for col, exacts, _, _ in rules:
        for i, h in enumerate(headers):
            if i in used:
                continue
            if h in exacts:
                out[col] = i
                used.add(i)
                break
    # 第二遍：contains 兜底（"分版型零售数"含"零售"），跳过已占用列
    for col, _, contains, excludes in rules:
        if col in out:
            continue
        for i, h in enumerate(headers):
            if i in used:
                continue
            if any(k in h for k in contains) and not any(x in h for x in excludes):
                out[col] = i
                used.add(i)
                break
    return out


def _is_trim_sheet(header) -> bool:
    """按表头列结构判定是否版型级数据表（不靠 sheet 名，兼容读取顺序）。
    判定依据：表头同时含"车型编号"与"分版型零售数"两列。"""
    headers = [str(c).strip() if c is not None else "" for c in (header or [])]
    has = lambda kw: any(kw in h for h in headers)
    return has("车型编号") and has("分版型零售数")


def _require(mapping: dict, required: tuple, sheet_name: str) -> None:
    missing = [k for k in required if k not in mapping]
    if missing:
        raise ValueError(
            f"Sheet「{sheet_name}」缺少核心列：{missing}（表头需包含车型编号/年/月/MSRP/TP/零售数等）")


# ---- 数值/字符串转换器（按 ORM 列类型）----
_TRIM_INT_COLS = {"year", "seats", "ev_range", "length_mm", "wheelbase_mm", "retail"}
_TRIM_FLOAT_COLS = {"pre_msrp", "msrp", "tp", "discount", "mix"}
_TRIM_PK = ("model_code", "year", "month")


def _parse_trim_row(row, colmap) -> dict | None:
    """主表行 → ORM dict；PK 缺件 → None（计入 skipped）。"""
    out: dict = {}
    for col, idx in colmap.items():
        v = row[idx] if idx < len(row) else None
        if col in _TRIM_INT_COLS:
            out[col] = _int(v)
        elif col in _TRIM_FLOAT_COLS:
            out[col] = _num(v)
        else:
            out[col] = _str(v)
    if not out.get("model_code") or out.get("year") is None or not out.get("month"):
        return None
    return out


def _derive_is_main(session, months: set) -> int:
    """导入落库后派生 is_main（v7：新源表无"是否主销"列）。

    规则：同 (车系,年,月) 内取 **Mix 最高行**为 is_main='是'（Mix 全空时退化为
    retail 最高行），其余置 '否'。Mix/retail 均为源表原始列，属纯派生不猜数据；
    与配置页 main_trim_spec_id 既有的"同月多行取 mix 最大者"tie-break 语义一致。
    仅对本次导入出现的 (year, month) 批次重算，避免全表重写。返回置 '是' 的行数。
    """
    if not months:
        return 0
    from sqlalchemy import text
    marked = 0
    for y, m in months:
        session.execute(text(
            "UPDATE sales_trim SET is_main = CASE WHEN rowid IN ("
            "  SELECT rid FROM ("
            "    SELECT rowid AS rid, ROW_NUMBER() OVER ("
            "      PARTITION BY series, year, month"
            "      ORDER BY COALESCE(mix, -1) DESC, COALESCE(retail, -1) DESC) AS rn"
            "    FROM sales_trim WHERE year = :y AND month = :m) WHERE rn = 1"
            "  ) THEN '是' ELSE '否' END"
            " WHERE year = :y AND month = :m"), {"y": y, "m": m})
        marked += session.execute(text(
            "SELECT COUNT(*) FROM sales_trim WHERE year = :y AND month = :m"
            " AND is_main = '是'"), {"y": y, "m": m}).scalar() or 0
    return marked


def _chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _upsert_chunk(session, model_cls, pk_cols, chunk) -> None:
    """SQLite ON CONFLICT DO UPDATE 批量 upsert（主键命中→非主键列更新）。
    executemany 形态（语句不带 values、参数按行走）：单语句参数数=列数，
    避开 SQLite 单语句绑定变量上限（多行 VALUES 会 19.7万×30 超限）。

    P3-33 None 不覆盖：set_ 用 coalesce(excluded[c], table.c[c])，
    使导入行值为 None（未映射列/空单元格）时不覆盖既有值，与
    upsert_config_snapshot 的"None 不覆盖"策略对齐。executemany 下
    set_ 是语句级固定的，无法逐行过滤 None 列，故在 SQL 层用 coalesce
    兜底。"""
    table = model_cls.__table__
    cols = [c.name for c in table.columns]
    stmt = sqlite_insert(table)
    non_pk = [c for c in cols if c not in pk_cols]
    stmt = stmt.on_conflict_do_update(
        index_elements=list(pk_cols),
        set_={c: func.coalesce(stmt.excluded[c], table.c[c]) for c in non_pk})
    session.execute(stmt, [{c: row.get(c) for c in cols} for row in chunk])


def import_workbook(path: str, chunk_size: int = 2000) -> dict:
    """解析 xlsx（唯一版型级 Sheet）并 upsert 落库。返回统计信封。
    {"trim": {"inserted","updated"}, "is_main": n, "skipped": n, "errors": [前10条]}

    v7 单表化：只认版型级 Sheet（表头含"车型编号"+"分版型零售数"）；非数据表跳过并在
    errors 里说明。导入完成后对本次出现的 (年,月) 批次派生 is_main。
    """
    from src.storage.db import session_scope

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    stats = {"trim": {"inserted": 0, "updated": 0},
             "is_main": 0, "skipped": 0, "errors": []}
    try:
        with session_scope() as s:
            # 预载现存 PK 集合：inserted/updated 统计口径（ON CONFLICT 不区分插改）
            trim_pks = _existing_pks(s, SalesTrim, _TRIM_PK)

            seen_trim: set = set()
            seen_months: set = set()   # 本次导入出现的 (year, month)，供 is_main 派生
            processed_any = False
            for ws in wb.worksheets:
                rows_iter = ws.iter_rows(values_only=True)
                try:
                    header = next(rows_iter)
                except StopIteration:
                    stats["errors"].append(f"Sheet「{ws.title}」为空，跳过")
                    continue
                if not _is_trim_sheet(header):
                    stats["errors"].append(f"Sheet「{ws.title}」非版型级数据表，跳过")
                    continue
                processed_any = True
                colmap = _match_headers(header, _TRIM_HEADER_RULES)
                _require(colmap, _TRIM_REQUIRED, ws.title)
                buffer: list[dict] = []
                for row in rows_iter:
                    parsed = _parse_trim_row(row, colmap)
                    if parsed is None:
                        stats["skipped"] += 1
                        continue
                    pk = (parsed["model_code"], parsed["year"], parsed["month"])
                    if pk not in seen_trim:
                        seen_trim.add(pk)
                        stats["trim"]["updated" if pk in trim_pks else "inserted"] += 1
                    seen_months.add((parsed["year"], parsed["month"]))
                    buffer.append(parsed)
                    if len(buffer) >= chunk_size:
                        _upsert_chunk(s, SalesTrim, _TRIM_PK, buffer)
                        buffer = []
                if buffer:
                    _upsert_chunk(s, SalesTrim, _TRIM_PK, buffer)
            if not processed_any:
                raise ValueError("未找到有效数据表（需一张版型级 Sheet：含车型编号/分版型零售数）")
            # 导入落库后派生 is_main（新源表无"是否主销"列）
            stats["is_main"] = _derive_is_main(s, seen_months)
    finally:
        wb.close()
    stats["errors"] = stats["errors"][:10]
    return stats


def _existing_pks(session, model_cls, pk_cols) -> set:
    """现存主键集合（表未建时返回空集——首份导入前表由 init_db/create_all 建好）。"""
    from sqlalchemy import select, inspect
    if not inspect(session.bind).has_table(model_cls.__tablename__):
        return set()
    cols = [getattr(model_cls, c) for c in pk_cols]
    return {tuple(r) for r in session.execute(select(*cols)).fetchall()}


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print("用法: python scripts/import_sales_excel.py <xlsx路径>", file=sys.stderr)
        return 2
    path = argv[0]
    if not Path(path).exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 2
    from src.storage.db import init_db
    init_db()  # 建表（幂等）+ WAL
    stats = import_workbook(path)
    import json
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
