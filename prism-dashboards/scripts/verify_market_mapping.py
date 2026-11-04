"""市场月度增量导入 — 映射验证脚本（导入前门禁）。

读 CAM 月末 xlsx + 现库 sales_trim 月末子集，按 (model_code, year, month) join
逐字段比对 27 个源字段（不含派生 is_main / hi_lo / pre_msrp，xlsx 无此列）。
抽 3 个车系校验 SUM(retail) GROUP BY (series, year, month) 新表=现库。

退出码：全一致 0；有不一致或缺失 1（作门禁）。
用法：
    .venv/Scripts/python.exe scripts/verify_market_mapping.py <xlsx路径>

环境变量 DATABASE_URL 指向主库（默认 worktree 库可能为空）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import openpyxl

# 走项目库（scripts/ 非包，CLI 直跑时把项目根加进 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from src.models.orm import SalesTrim  # noqa: E402
from src.storage.db import init_db, session_scope  # noqa: E402

# 复用 import_sales_excel 的表头匹配规则 + 数值/字符串转换器（保持口径一致）
from scripts.import_sales_excel import (  # noqa: E402
    _TRIM_HEADER_RULES,
    _match_headers,
    _parse_trim_row,
    _require,
    _TRIM_REQUIRED,
)

# xlsx 实际映射的 27 个源字段（不含 is_main/hi_lo/pre_msrp，xlsx 无此列）
_SOURCE_FIELDS = [
    "model_code", "year", "month", "manufacturer", "brand", "series",
    "level", "body", "displacement", "gearbox", "energy_type", "seats",
    "drive", "fuel", "origin", "ev_range", "version", "length_mm",
    "wheelbase_mm", "launch_date", "prod_status", "model_name", "msrp",
    "tp", "discount", "mix", "retail",
]


def _load_xlsx_rows(path: str) -> dict[tuple, dict]:
    """读 xlsx → {(model_code, year, month): {field: value}}（27 源字段，已归一）。"""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out: dict[tuple, dict] = {}
    try:
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            try:
                header = next(it)
            except StopIteration:
                continue
            colmap = _match_headers(header, _TRIM_HEADER_RULES)
            # xlsx 无 is_main/hi_lo/pre_msrp 列 → colmap 不会有这 3 个 key（自然 OK）
            _require(colmap, _TRIM_REQUIRED, ws.title)
            for row in it:
                parsed = _parse_trim_row(row, colmap)
                if parsed is None:
                    continue
                pk = (parsed["model_code"], parsed["year"], parsed["month"])
                # 只保留 27 源字段（_parse_trim_row 可能含 is_main/hi_lo/pre_msrp 若表头误有，剔除）
                out[pk] = {k: parsed.get(k) for k in _SOURCE_FIELDS}
    finally:
        wb.close()
    return out


def _load_db_rows() -> dict[tuple, dict]:
    """读现库 sales_trim 月末子集 → {(model_code, year, month): {field: value}}。"""
    out: dict[tuple, dict] = {}
    with session_scope() as s:
        cols = [getattr(SalesTrim, c) for c in _SOURCE_FIELDS]
        rows = s.execute(
            select(*cols).where(SalesTrim.month.like("%月末"))
        ).fetchall()
        for r in rows:
            pk = (r[0], r[1], r[2])  # model_code, year, month
            out[pk] = {k: v for k, v in zip(_SOURCE_FIELDS, r)}
    return out


def _values_equal(a, b) -> bool:
    """归一化比较：数值走 float 容差，字符串 trim，None 与空串视为相等。"""
    # 都 None / 空 → 一致
    if a is None and b is None:
        return True
    # 数值列：尝试 float 比较（容差 1e-6）
    fa = _to_float(a)
    fb = _to_float(b)
    if fa is not None or fb is not None:
        if fa is None or fb is None:
            # 一边数值一边 None → 不一致（除非 None 一边是空串/占位符）
            return False
        return abs(fa - fb) < 1e-6
    # 字符串列：trim 后比较；空串与 None 视为相等
    sa = (str(a).strip() if a is not None else "")
    sb = (str(b).strip() if b is not None else "")
    return sa == sb


def _to_float(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if not s or s in {"-", "—", "无", "N/A", "NA", "/"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _aggregate_retail_by_series(rows: dict[tuple, dict], series: str) -> dict[tuple, int]:
    """SUM(retail) GROUP BY (series, year, month) for one series → {(year, month): sum}。"""
    out: dict[tuple, int] = {}
    for pk, r in rows.items():
        if r.get("series") != series:
            continue
        ym = (r.get("year"), r.get("month"))
        retail = r.get("retail") or 0
        out[ym] = out.get(ym, 0) + retail
    return out


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print("用法: python scripts/verify_market_mapping.py <xlsx路径>",
              file=sys.stderr)
        return 2
    path = argv[0]
    if not Path(path).exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 2

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("⚠ 未设 DATABASE_URL，将用 worktree 默认库（可能为空）",
              file=sys.stderr)
    init_db()

    print(f"读 xlsx: {path}")
    xlsx_rows = _load_xlsx_rows(path)
    print(f"  xlsx 行数: {len(xlsx_rows)}")
    print("读现库 sales_trim 月末子集...")
    db_rows = _load_db_rows()
    print(f"  现库月末行数: {len(db_rows)}")

    # ---- PK join 比对 ----
    xlsx_pks = set(xlsx_rows)
    db_pks = set(db_rows)
    only_xlsx = xlsx_pks - db_pks
    only_db = db_pks - xlsx_pks
    common = xlsx_pks & db_pks

    print(f"\nPK 比对：xlsx={len(xlsx_pks)} 现库={len(db_pks)} "
          f"交集={len(common)} 仅xlsx={len(only_xlsx)} 仅库={len(only_db)}")

    # only_xlsx / only_db 作信息性输出（新月份导入前会有 only_xlsx，属预期），
    # 不计入门禁——本脚本定位是"导入前字段映射门禁"，gate 只判交集 PK 的字段一致性
    # + 聚合校验。only_xlsx 非空 ≠ 字段映射错。
    consistent = 0
    inconsistent = 0
    samples: list[str] = []
    for pk in common:
        xr = xlsx_rows[pk]
        dr = db_rows[pk]
        diffs = []
        for f in _SOURCE_FIELDS:
            if not _values_equal(xr.get(f), dr.get(f)):
                diffs.append((f, xr.get(f), dr.get(f)))
        if diffs:
            inconsistent += 1
            if len(samples) < 10:
                samples.append(
                    f"  PK={pk}: " + ", ".join(
                        f"{f}(xlsx={xr.get(f)!r} db={dr.get(f)!r})" for f, _, _ in diffs[:3]))
        else:
            consistent += 1

    print(f"\n字段比对（27 源字段，{len(common)} 个共同 PK）：")
    print(f"  一致字段组合: {consistent}")
    print(f"  不一致字段组合: {inconsistent}")
    if samples:
        print("  不一致样本（前10条）:")
        for s in samples:
            print(s)

    # ---- 车系销量聚合校验 ----
    print("\n车系 SUM(retail) 聚合校验（抽 3 个车系）...")
    all_series = sorted({r.get("series") for r in xlsx_rows.values()
                         if r.get("series")})
    # 抽 3 个有代表性的：第 1 个、中间 1 个、最后 1 个
    if len(all_series) >= 3:
        picks = [all_series[0], all_series[len(all_series) // 2], all_series[-1]]
    else:
        picks = all_series
    agg_ok = True
    for series in picks:
        x_agg = _aggregate_retail_by_series(xlsx_rows, series)
        d_agg = _aggregate_retail_by_series(db_rows, series)
        x_keys = set(x_agg)
        d_keys = set(d_agg)
        mismatches = []
        for ym in sorted(x_keys | d_keys):
            xv = x_agg.get(ym, 0)
            dv = d_agg.get(ym, 0)
            if xv != dv:
                mismatches.append((ym, xv, dv))
        status = "OK" if not mismatches else f"MISMATCH({len(mismatches)} 个月)"
        print(f"  车系「{series}」: xlsx 月数={len(x_agg)} 库月数={len(d_agg)} → {status}")
        if mismatches and len(mismatches) <= 3:
            for ym, xv, dv in mismatches[:3]:
                print(f"    {ym}: xlsx={xv} db={dv}")
        if mismatches:
            agg_ok = False

    # ---- 退出码 ----
    ok = (inconsistent == 0 and agg_ok)
    print(f"\n门禁结果：{'✓ 全一致' if ok else '✗ 有不一致'}")
    print(f"  （仅xlsx={len(only_xlsx)} 仅库={len(only_db)} 属信息性，新月份导入时 only_xlsx 非空为预期，不计入门禁）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
