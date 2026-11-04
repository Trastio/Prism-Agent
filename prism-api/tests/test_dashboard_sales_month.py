# -*- coding: utf-8 -*-
"""
/dashboard/sales month 参数单测（query-sales-month过滤 change，2026-10-15）
运行：cd prism-api && python -m pytest tests/test_dashboard_sales_month.py -q
     （无 pytest 时 python tests/test_dashboard_sales_month.py 走裸断言）

覆盖：
- 月度聚合：month=N 恰等于无 month 结果按月号过滤的子集（零回归断言法）
- 月度聚合：库内不存在的月份 → 空 rows（不编数）
- spec 分支：month 过滤按前导数字匹配，1/11 陷阱不误配（'1月末' 不吃 '11月末'）
- spec 分支：月末口径限定不破（返回行全部 '%月末'）
- month=13 / month=0 → 400 fail-loud
- month 参数出现在 reviews 分支不影响其 200（跨 dtype 无副作用）
"""
import re
import sys
from pathlib import Path
from urllib.parse import quote

try:
    import pytest
except ImportError:  # 裸 python 直跑兼容
    pytest = None

def _skip(msg):
    """Step7 审查 P2-6：skip 显性化——pytest 下计 skip，裸跑下打印提示"""
    if pytest is not None:
        pytest.skip(msg)
    print(f'[skip] {msg}')

sys.path.insert(0, str(Path(__file__).parent.parent))
from fastapi.testclient import TestClient  # noqa: E402
import main as prism_main  # noqa: E402

client = TestClient(prism_main.app)

E5 = quote('银河E5')


def _lead(month_str):
    m = re.match(r'^(\d+)', str(month_str or ''))
    return int(m.group(1)) if m else None


def test_monthly_subset_zero_regression():
    r_all = client.get(f'/dashboard/sales?series_key={E5}&year=2026')
    r_m8 = client.get(f'/dashboard/sales?series_key={E5}&year=2026&month=8')
    assert r_all.status_code == 200 and r_m8.status_code == 200
    rows_all, rows_m8 = r_all.json()['rows'], r_m8.json()['rows']
    expected = [r for r in rows_all if r['month'] == 8]
    assert rows_m8 == expected, 'month=8 应恰为全量结果中月号=8 的子集'
    assert all(r['month'] == 8 for r in rows_m8)
    # 2026-8月末 银河E5 总零售真值锚（4436；sales-14 金标口径）
    e5_8 = [r for r in rows_m8 if r['series'] == '银河E5']
    assert len(e5_8) == 1 and e5_8[0]['retail_sum'] == 4436, f'真值锚失配: {e5_8}'


def test_monthly_absent_month_empty():
    r_all = client.get(f'/dashboard/sales?series_key={E5}&year=2026')
    present = {r['month'] for r in r_all.json()['rows']}
    absent = next((m for m in range(1, 13) if m not in present), None)
    if absent is None:
        _skip('2026 全 12 月均有数据，无缺失月可测')
        return
    r = client.get(f'/dashboard/sales?series_key={E5}&year=2026&month={absent}')
    assert r.status_code == 200 and r.json()['rows'] == [], '库内无该月应返回空 rows 而非编数'


def test_null_retail_month_lock():
    """Step7 审查 P2-5：第二种缺失语义的回归锁——有月末行但零售全 NULL 的月，
    month 过滤应返回 1 行 retail_sum=null（如实见缺），不得剔成空 rows 或填 0。"""
    r_all = client.get(f'/dashboard/sales?series_key={E5}&year=2026')
    null_months = [r['month'] for r in r_all.json()['rows'] if r['retail_sum'] is None]
    if not null_months:
        _skip('库内无 retail_sum=null 的月，null 语义锁本次未覆盖')
        return
    m = null_months[0]
    r = client.get(f'/dashboard/sales?series_key={E5}&year=2026&month={m}')
    assert r.status_code == 200
    rows = r.json()['rows']
    assert rows and rows[0]['retail_sum'] is None, \
        f'月={m} 应保留 1 行 retail_sum=null（与无 month 全量行为一致），实得 {rows}'


def test_spec_branch_filter_and_trap():
    r_all = client.get(f'/dashboard/sales?series_key={E5}&group_by=spec')
    rows_all = r_all.json()['rows']
    assert rows_all, 'spec 分支应有数据'
    assert all(str(r['month']).endswith('月末') for r in rows_all), '月末口径限定被破坏'
    digits = {_lead(r['month']) for r in rows_all}
    d = sorted(digits)[0]
    r_d = client.get(f'/dashboard/sales?series_key={E5}&group_by=spec&month={d}')
    assert r_d.status_code == 200
    rows_d = r_d.json()['rows']
    assert rows_d == [r for r in rows_all if _lead(r['month']) == d], 'spec 过滤应为前导数字精确匹配子集'
    # 1/11 陷阱：month=1 绝不含 10/11/12 月行（LIKE '1月末' 误配路径的回归锁）
    # Step7 审查 P2-3：区分力依赖库内存在 10/11/12 月末行——条件化断言，无则显性 skip 不空真过
    trap_rows = [r for r in rows_all if _lead(r['month']) != 1 and str(r['month']).startswith('1')]
    r1 = client.get(f'/dashboard/sales?series_key={E5}&group_by=spec&month=1')
    assert r1.status_code == 200
    rows_1 = r1.json()['rows']
    assert all(_lead(r['month']) == 1 for r in rows_1), 'month=1 混入了非 1 月行'
    if trap_rows:
        assert not any(_lead(r['month']) != 1 for r in rows_1), \
            f'1/11 陷阱回归：month=1 吃进了 {len(trap_rows)} 行 10/11/12 月行'
    else:
        print('[note] 库内无 10/11/12 月末行，1/11 陷阱区分力本次未覆盖（数据依赖，见审查 P2-3）')


def test_month_validation_400():
    for bad in (13, 0):
        r = client.get(f'/dashboard/sales?series_key={E5}&month={bad}')
        assert r.status_code == 400, f'month={bad} 应 400，实得 {r.status_code}'


def test_month_param_no_side_effect_on_reviews():
    r = client.get(f'/dashboard/reviews?series_key={E5}&month=8')
    assert r.status_code == 200 and r.json()['rows'], 'reviews 分支应忽略 month 不受影响'


def test_month_param_no_side_effect_on_config():
    """Step7 审查 P2-6：config 分支同样应忽略合法 month（与 reviews 对称）"""
    r = client.get(f'/dashboard/config?series_key={E5}&month=8')
    assert r.status_code == 200 and r.json().get('rows'), 'config 分支应忽略 month 不受影响'


if __name__ == '__main__':
    test_monthly_subset_zero_regression()
    test_monthly_absent_month_empty()
    test_spec_branch_filter_and_trap()
    test_month_validation_400()
    test_month_param_no_side_effect_on_reviews()
    print('ALL PASS')
