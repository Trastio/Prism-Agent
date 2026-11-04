# -*- coding: utf-8 -*-
"""
/export API 单测（社媒深挖能力包 M3）
运行：cd prism-api && python -m pytest tests/test_export_api.py -q
     （无 pytest 时 python tests/test_export_api.py 走裸断言）

覆盖：
- POST /export 往返：openpyxl 读回校验 sheet 名/表头/单元格内容
- filename 白名单（../ 与特殊字符 → fallback，不 500）
- rows 超限 → 422
- /export/download/{id} 命中 manifest / 不存在 id → 404
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from fastapi.testclient import TestClient  # noqa: E402
import openpyxl  # noqa: E402
import main as prism_main  # noqa: E402

client = TestClient(prism_main.app)


def _read_back(file_id):
    path = prism_main.EXPORT_DIR / f'{file_id}.xlsx'
    assert path.exists(), f'{path} 未生成'
    return openpyxl.load_workbook(path)


def test_export_roundtrip():
    body = {
        'title': '风云T7典型用户分析',
        'filename': '风云T7典型用户分析.xlsx',
        'sheets': [
            {'name': '用户对照总览', 'headers': ['维度', '用户1', '用户2'],
             'rows': [['性别/年龄', '男/约53岁', '女/40岁'], ['地域', '安徽', '浙江(IP)']]},
            {'name': '溯源清单', 'headers': ['平台', 'URL'], 'rows': [['douyin', 'https://www.douyin.com/video/1']]},
        ],
    }
    r = client.post('/export', json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data['sheets'] == 2
    assert data['url'] == f"/export/download/{data['file_id']}"
    assert data['filename'] == '风云T7典型用户分析.xlsx'

    wb = _read_back(data['file_id'])
    assert wb.sheetnames == ['用户对照总览', '溯源清单']
    ws = wb['用户对照总览']
    assert [c.value for c in ws[1]] == ['维度', '用户1', '用户2']
    assert ws.cell(2, 1).value == '性别/年龄'
    assert ws.cell(2, 3).value == '女/40岁'

    # 下载往返
    d = client.get(data['url'])
    assert d.status_code == 200
    assert 'spreadsheetml' in d.headers.get('content-type', '')


def test_filename_sanitized():
    r = client.post('/export', json={
        'title': 't', 'filename': '../../etc/passwd',
        'sheets': [{'name': 'S', 'headers': ['a'], 'rows': [[1]]}],
    })
    assert r.status_code == 200
    assert '../' not in r.json()['filename']
    assert r.json()['filename'].endswith('.xlsx')


def test_rows_over_limit_422():
    r = client.post('/export', json={
        'title': 't',
        'sheets': [{'name': 'S', 'headers': ['a'], 'rows': [[1]] * 5001}],
    })
    assert r.status_code == 422


def test_download_404():
    assert client.get('/export/download/nonexistent0000').status_code == 404


def test_tikhub_status_unconfigured():
    # 密封（P2）：强制无 key 态——开发机配了 key 也不真实外呼（15s 超时 + 10min 缓存污染）
    prev_key, prev_cache = prism_main._TIKHUB_KEY_PRISM, prism_main._tikhub_status_cache['data']
    prism_main._TIKHUB_KEY_PRISM = ''
    prism_main._tikhub_status_cache.update(ts=0.0, data=None)
    try:
        r = client.get('/tikhub/status')
        assert r.status_code == 200
        assert r.json() == {'configured': False}
    finally:
        prism_main._TIKHUB_KEY_PRISM = prev_key
        prism_main._tikhub_status_cache.update(ts=0.0, data=prev_cache)


if __name__ == '__main__':
    for fn in [test_export_roundtrip, test_filename_sanitized, test_rows_over_limit_422,
               test_download_404, test_tikhub_status_unconfigured]:
        fn()
        print(f'PASS {fn.__name__}')
    print('ALL PASS')
