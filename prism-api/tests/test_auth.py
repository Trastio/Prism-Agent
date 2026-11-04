# -*- coding: utf-8 -*-
"""
登录门禁单测（登录门禁 change T5，2026-10-15）
运行：cd prism-api && python -m pytest tests/test_auth.py -q

覆盖：
- login 成功：Set-Cookie 带 prism_token（HttpOnly），/auth/me 恢复身份
- 密码错 401（固定文案）；用户名非法 400
- 无 token 访问业务路由 401；带 token 200（TestClient cookie jar 透传）
- token 过期 401（手工构造已过期签名）
- user_id 覆盖语义（依赖注入层直测 resolve_user_id——token 用户名优先于自报值）
"""
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest  # noqa: E402
from fastapi import Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import main as prism_main  # noqa: E402

E5 = quote('银河E5')
PW = '666666'  # 共享密码（bootstrap 落盘即此值；哈希在 users.json，明文不落测试断言外）


@pytest.fixture
def gated():
    """关闭 conftest 的旁路 → 真门禁；测毕恢复旁路防污染其他用例"""
    prism_main.app.state.auth_bypass = False
    yield
    prism_main.app.state.auth_bypass = True


def test_login_success_sets_cookie_and_me(gated):
    c = TestClient(prism_main.app)
    r = c.post('/auth/login', json={'username': 'alice', 'password': PW})
    assert r.status_code == 200, r.text
    assert r.json() == {'username': 'alice', 'role': 'viewer'}
    sc = r.headers.get('set-cookie', '')
    assert 'prism_token=' in sc and 'HttpOnly' in sc and 'samesite=lax' in sc.lower()
    # cookie jar 已存 → /auth/me 恢复身份
    me = c.get('/auth/me')
    assert me.status_code == 200 and me.json() == {'username': 'alice', 'role': 'viewer'}


def test_login_admin_role_whitelist(gated):
    c = TestClient(prism_main.app)
    r = c.post('/auth/login', json={'username': 'admin', 'password': PW})
    assert r.status_code == 200 and r.json()['role'] == 'admin'
    assert c.get('/auth/me').json()['role'] == 'admin'


def test_login_wrong_password_401(gated):
    c = TestClient(prism_main.app)
    r = c.post('/auth/login', json={'username': 'alice', 'password': 'wrong'})
    assert r.status_code == 401 and r.json()['detail'] == '用户名或密码错误'
    assert 'prism_token' not in r.headers.get('set-cookie', '')


def test_login_bad_username_400(gated):
    c = TestClient(prism_main.app)
    r = c.post('/auth/login', json={'username': '坏 名字!', 'password': PW})
    assert r.status_code == 400


def test_business_route_401_without_token(gated):
    c = TestClient(prism_main.app)
    r = c.get(f'/dashboard/sales?series_key={E5}')
    assert r.status_code == 401 and r.json()['detail'] == '未登录'
    r2 = c.get('/session?user_id=alice')
    assert r2.status_code == 401
    r3 = c.post('/chat/abort', json={'user_id': 'alice'})
    assert r3.status_code == 401


def test_business_route_200_with_token(gated):
    c = TestClient(prism_main.app)
    c.post('/auth/login', json={'username': 'alice', 'password': PW})
    r = c.get(f'/dashboard/sales?series_key={E5}&year=2026&month=8')
    assert r.status_code == 200 and r.json()['rows'][0]['retail_sum'] == 4436


def test_expired_token_401(gated):
    # 手工构造已过期 token（签名合法、exp 在过去）——门禁必须拒
    orig_ttl = prism_main.AUTH_TTL_S
    prism_main.AUTH_TTL_S = -10
    token = prism_main._sign_token('alice', 'viewer')
    prism_main.AUTH_TTL_S = orig_ttl
    c = TestClient(prism_main.app)
    c.cookies.set('prism_token', token)
    assert c.get('/auth/me').status_code == 401
    assert c.get(f'/dashboard/sales?series_key={E5}').status_code == 401


def test_forged_token_401(gated):
    c = TestClient(prism_main.app)
    c.cookies.set('prism_token', 'not.a.token')
    assert c.get('/auth/me').status_code == 401


def test_resolve_user_id_token_wins(gated):
    """T2 覆盖语义：token 注入的 username 优先于 body/query 自报值（依赖注入层直测，
    不真起 /chat/stream 流——端到端冒烟留 Step9 主会话）"""
    req = Request(scope={'type': 'http', 'method': 'POST', 'path': '/chat/stream',
                         'headers': [], 'query_string': b''})
    req.state.username = 'alice'
    req.state.role = 'viewer'
    assert prism_main.resolve_user_id(req, 'someone_else') == 'alice'  # 自报被覆盖
    # 旁路态（无注入）回落自报值
    req2 = Request(scope={'type': 'http', 'method': 'POST', 'path': '/chat/stream',
                          'headers': [], 'query_string': b''})
    assert prism_main.resolve_user_id(req2, 'legacy_user') == 'legacy_user'
    assert prism_main.resolve_user_id(req2, None) == 'default'


def test_users_json_no_plaintext_password():
    """验收 §5：users.json 不含明文密码（P2-9 加固：先 _users() 保单跑不 FileNotFoundError + 哈希形态断言）"""
    import re as _re
    data = prism_main._users()  # 触发读取/bootstrap（否则单跑该用例时文件可能不存在）
    txt = prism_main.USERS_FILE.read_text(encoding='utf-8')
    assert '666666' not in txt, '明文密码出现在 users.json！'
    assert _re.fullmatch(r'[0-9a-f]{128}', data['pwhash']), 'pwhash 应为 scrypt(dklen=64) 的 128 hex'
    assert _re.fullmatch(r'[0-9a-f]{32}', data['salt']), 'salt 应为 16 字节 32 hex'


def test_events_local_id_token_wins(gated, tmp_path, monkeypatch):
    """多轮评估批 change T5：/events 身份焊死——token 用户名覆盖请求体自报 local_id
    （北极星 DAU 实名口径的服务端保证，此前全站唯一未覆盖端点）；同批事件统一身份。"""
    db = tmp_path / 'ev.db'
    monkeypatch.setattr(prism_main, 'EVENTS_DB', str(db))
    prism_main._init_events_db()
    c = TestClient(prism_main.app)
    c.post('/auth/login', json={'username': 'alice', 'password': PW})
    r = c.post('/events', json={'events': [
        {'event_type': 'page_view', 'local_id': 'usr_spoof', 'ts': '2026-10-25T00:00:00'},
        {'event_type': 'chat_start', 'local_id': 'another_id', 'ts': '2026-10-25T00:00:01'},
    ]})
    assert r.status_code == 200 and r.json()['inserted'] == 2, r.text
    import sqlite3 as _s
    rows = _s.connect(str(db)).execute('SELECT local_id FROM events ORDER BY rowid').fetchall()
    assert [x[0] for x in rows] == ['alice', 'alice']  # 自报被覆盖；同批统一身份


def test_events_eval_stack_dropped(gated, tmp_path, monkeypatch):
    """P0 北极星隔离（2026-10-26）：eval 栈（PRISM_EVAL_STACK=1）不写产品事件库。"""
    db = tmp_path / 'ev_eval.db'
    monkeypatch.setattr(prism_main, 'EVENTS_DB', str(db))
    prism_main._init_events_db()
    monkeypatch.setenv('PRISM_EVAL_STACK', '1')
    c = TestClient(prism_main.app)
    c.post('/auth/login', json={'username': 'eval_cross-01', 'password': PW})
    r = c.post('/events', json={'events': [{'event_type': 'page_view', 'ts': '2026-10-26T00:00:00'}]})
    assert r.status_code == 200 and r.json()['inserted'] == 0 and r.json()['skipped'] == 'eval_stack', r.text
    import sqlite3 as _s
    n = _s.connect(str(db)).execute('SELECT COUNT(*) FROM events').fetchone()[0]
    assert n == 0


def test_events_401_without_token(gated):
    """多轮评估批 change T5：无 token 的 /events 仍被门拦（既有行为不变）"""
    c = TestClient(prism_main.app)
    r = c.post('/events', json={'events': [{'event_type': 'page_view', 'local_id': 'x'}]})
    assert r.status_code == 401 and r.json()['detail'] == '未登录'
