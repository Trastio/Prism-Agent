# -*- coding: utf-8 -*-
"""
_live_meta sales as_of 修复单测（sales-asof修复 change，2026-10-15）
背景：sales_trim 无 fetched_at 列，旧查询 SQL 异常被 except 吞 → /dashboard/sales 的
as_of 恒空（工具契约"返回带 as_of"从未兑现）。修复后与 /dash/as_of 端点同源。
"""
import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent.parent))
from fastapi.testclient import TestClient  # noqa: E402
import main as prism_main  # noqa: E402

client = TestClient(prism_main.app)
E5 = quote('银河E5')


def test_sales_asof_nonempty_and_month_end():
    r = client.get(f'/dashboard/sales?series_key={E5}')
    assert r.status_code == 200
    as_of = r.json()['_meta']['as_of']
    assert as_of, 'sales as_of 不得为空（修复前恒空）'
    assert re.fullmatch(r'\d{4}-\d{1,2}月末', as_of), f'as_of 形态应为 year-M月末，实得 {as_of!r}'


def test_sales_asof_same_source_as_dash_endpoint():
    r1 = client.get(f'/dashboard/sales?series_key={E5}').json()['_meta']['as_of']
    r2 = client.get('/dash/as_of').json()['sales']
    assert r1 == r2, f'两处 sales as_of 必须同源（/dashboard/sales 的 _meta vs /dash/as_of）：{r1!r} != {r2!r}'


def test_month_filter_keeps_asof():
    r = client.get(f'/dashboard/sales?series_key={E5}&year=2026&month=8')
    assert r.status_code == 200
    assert r.json()['_meta']['as_of'], 'month 过滤不得影响 as_of 供给'


if __name__ == '__main__':
    test_sales_asof_nonempty_and_month_end()
    test_sales_asof_same_source_as_dash_endpoint()
    test_month_filter_keeps_asof()
    print('ALL PASS')
