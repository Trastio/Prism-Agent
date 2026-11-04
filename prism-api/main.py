"""
Prism-Agent · FastAPI 网关（T-2.5b.1 + T-2.5b.6）

路由：
- GET  /dashboard/{type}  → 实时读 Prism 主库（prism-dashboards 同源，含 _meta）
- POST /chat/stream        → SSE 流式（pi_bridge，M7）
- GET/POST /session        → 会话 CRUD（Redis，M7）
- WS   /ws/status          → 状态栏推送（M7）

开发期：本地 127.0.0.1:8001
"""
import sys, os, json
from pathlib import Path

# 把 src/ 加进 path 以便复用 TS 模块的 Python 等价（口径视图刷新脚本）
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response, JSONResponse
import sqlite3
import httpx
import re  # dashboard spec 分支月过滤用（原 369 行处后置导入上移——Step7 审查 P2-1，防函数依赖后置模块名的脆弱模式）

# 2026-10-08 单源化：物化视图 prism_views.db 退役，以下统一直读 Prism 主库 AUTOHOME_DB
# （数据真值在下方 AUTOHOME_DB 定义）
# 数据真值（迁移后以 Prism 侧为主库）：prism-dashboards/data/autohome.db
# 仍可用环境变量 AUTOHOME_DB_PATH 覆盖
AUTOHOME_DB = os.environ.get('AUTOHOME_DB_PATH', str(Path(__file__).parent.parent / 'prism-dashboards' / 'data' / 'autohome.db'))
PI_SERVER = os.environ.get('PI_SERVER', 'http://127.0.0.1:9200')
SENTIMENT_BOARD = os.environ.get('SENTIMENT_BOARD', 'http://127.0.0.1:8000')
# 舆情库（/dash/as_of 舆情段直读；只读 URI，fail-soft 缺省）
SENTIMENT_DB = os.environ.get('SENTIMENT_DB_PATH', str(Path(__file__).parent.parent / 'prism-sentiment' / 'data' / 'vehicle_sentiment.db'))

# ---------------------------------------------------------------------------
# P0-1：统一 httpx 客户端工厂——显式 trust_env=False，禁止 localhost 请求走系统代理
# 背景：本机若装有系统代理（如 http://127.0.0.1:7892），httpx 默认 trust_env=True 会让
# 对 127.0.0.1 的后端调用被代理劫持 → 502/空响应（前端收不到回复）。
# 此处对所有内部后端调用强制直连，timeout 语义与原调用保持一致。
# ---------------------------------------------------------------------------
def httpx_client(timeout):
    """构造直连（不走系统代理）的 httpx.AsyncClient。

    timeout 兼容原用法：可为 number（秒）或 httpx.Timeout 对象。
    """
    return httpx.AsyncClient(timeout=timeout, trust_env=False)


app = FastAPI(title='Prism-Agent API', version='0.3.0')

# CORS（开发期允许 5173 前端；云上可用 PRISM_ALLOWED_ORIGIN 覆盖，逗号分隔）
# 默认值保持与本机开发完全一致，不设该 env 时行为不变
_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get(
        'PRISM_ALLOWED_ORIGIN', 'http://localhost:5173,http://127.0.0.1:5173'
    ).split(',') if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# T-5.10 鉴权：管理者写端点保护（红线#3）
MANAGER_PASSWORD = os.environ.get('PRISM_MANAGER_PASSWORD', '')  # 生产期必设
WRITE_ENDPOINTS_PREFIXES = ('/autohome/',)  # POST /autohome/{tool} 等管理者写端点
# B3（2026-11-03）：写端点显式白名单分层——
#   ① 管理者写端点（/autohome/*）：需 X-Manager-Password，prod 未配口令则 fail-closed（原逻辑不变）；
#   ② 用户写端点（下表）：需有效登录身份（auth_gate 外层已强制，这里做纵深登记，防新增写端点裸奔）。
#   不把②并入 MANAGER_PASSWORD 校验：前端不带该头，会把「新建会话 / 导出 / 回填」全部打断；
#   其身份绑定由各端点 resolve_user_id（token 覆盖 body）承担。
USER_WRITE_PATHS = {
    ('POST', '/session'),
    ('POST', '/session/rename'),
    ('POST', '/export'),
    ('POST', '/ui-response'),
}

@app.middleware('http')
async def manager_auth(request: Request, call_next):
    # 只拦写端点（POST/PUT/DELETE）
    if request.method in ('POST', 'PUT', 'DELETE') and any(request.url.path.startswith(p) for p in WRITE_ENDPOINTS_PREFIXES):
        if MANAGER_PASSWORD:  # 生产期启用
            provided = request.headers.get('X-Manager-Password', '')
            if provided != MANAGER_PASSWORD:
                return Response(json.dumps({'error': '管理者操作需密码'}), status_code=401, media_type='application/json')
        elif os.environ.get('PRISM_ENV') == 'prod':
            # B3（2026-11-02）：prod 未配管理密码时 fail-closed，避免写端点裸奔；
            # dev 保持放行（本地开发/测试不受影响）。
            return Response(json.dumps({'error': '管理者操作需配置 PRISM_MANAGER_PASSWORD'}), status_code=401, media_type='application/json')
    # B3（2026-11-03）：用户写端点必须带登录身份（service 令牌或有效 cookie）；
    # prod 下无身份直接 401，dev 保持原行为（评估/本地直调不受影响）。
    if os.environ.get('PRISM_ENV') == 'prod' and (request.method, request.url.path) in USER_WRITE_PATHS:
        if not getattr(request.state, 'username', None):
            return Response(json.dumps({'error': '写操作需要登录'}), status_code=401, media_type='application/json')
    return await call_next(request)


# ---------------------------------------------------------------------------
# 登录门禁（登录门禁 change T1/T2，2026-10-15）：统一口令门——全员共享密码 666666，
# 进站必须用户名+密码，业务路由一律要求有效 prism_token cookie（HMAC-SHA256 签名，7 天）。
# 设计依据：设计图总览/Prism-Agent-登录门禁方案-v1.md + change proposal
# 落点修正：①api 层统一拦截（网关 9200 不动，浏览器只达 8002）②门禁边界=主站 api，
#   dashboards(8010)/sentiment(8000)/ops(8020) 子服务本地阶段不拦（上云收内网）。
# 中间件顺序注：本件注册在 manager_auth 之后 = 外层先执行（Starlette 逆序），
#   未登录请求在管理者写保护之前即被 401 挡下。
# ---------------------------------------------------------------------------
import hashlib, hmac as _hmac_auth, secrets, base64, time as _time_auth

AUTH_SECRET = os.environ.get('PRISM_AUTH_SECRET', '')
if not AUTH_SECRET:
    # P1-1 修复（Step7 审查）：dev 固定密钥是源码内公开串，可离线伪造含 admin 的合法 token——
    # prod 环境 fail-closed 拒启（护栏在执行层非提示层，红线#5 精神）；本地 dev 保留回落+WARN
    if os.environ.get('PRISM_ENV') == 'prod':
        raise RuntimeError('[auth] PRISM_ENV=prod 且未设 PRISM_AUTH_SECRET——拒启（dev 固定密钥可伪造 token，上云必换）')
    AUTH_SECRET = 'prism-dev-secret-change-before-deploy'
    print('[auth][WARN] PRISM_AUTH_SECRET 未设置，使用 dev 固定密钥——上云前必换（PRISM_ENV=prod 将拒启）')
USERS_FILE = Path(__file__).parent / 'data' / 'users.json'
# 服务令牌（2026-10-18）：登录门禁会拦本机内部调用（extension 工具链不带浏览器 cookie）。
# 网关把 .pi/service_token 注入 pi 进程 env，extension 以 X-Prism-Service 头通过鉴权。
SERVICE_TOKEN_FILE = Path(__file__).parent.parent / '.pi' / 'service_token'


def _service_token() -> str:
    try:
        return SERVICE_TOKEN_FILE.read_text(encoding='utf-8').strip()
    except OSError:
        return ''
AUTH_EXEMPT_PATHS = {'/auth/login', '/health'}
AUTH_COOKIE = 'prism_token'
AUTH_TTL_S = 7 * 24 * 3600
_USERNAME_RE = re.compile(r'^[A-Za-z0-9_-]{1,32}$')

def _hash_pw(password: str, salt_hex: str) -> str:
    """共享密码盐哈希（scrypt）——users.json 只存 hex，不存明文"""
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1).hex()

_USERS_CACHE: tuple | None = None  # (mtime, data)——P2-1 修复：mtime 失效缓存，改密/白名单热生效
def _users() -> dict:
    """读 users.json；缺失/损坏时自动 bootstrap（共享密码 666666 哈希落盘 + admin 白名单）。
    P2-1（Step7 审查）：损坏文件不静默重置（半文件会让 bootstrap 把密码重置回 666666）——
    显式 WARN 后重置（本地阶段接受，上云改管理员告警）；写盘原子化 tmp+os.replace。"""
    global _USERS_CACHE
    try:
        mtime = USERS_FILE.stat().st_mtime
    except FileNotFoundError:
        mtime = None
    if _USERS_CACHE is not None and _USERS_CACHE[0] == mtime:
        return _USERS_CACHE[1]
    data = None
    if mtime is not None:
        try:
            data = json.loads(USERS_FILE.read_text(encoding='utf-8'))
            if not (isinstance(data.get('pwhash'), str) and isinstance(data.get('salt'), str)):
                data = None
        except Exception as e:
            print(f'[auth][WARN] users.json 读取失败（{e}），将重建（注意：重建会生成新的随机初始口令，旧口令立即失效）')
            data = None
    if data is None:
        salt = secrets.token_hex(16)
        # B2（2026-11-02）：不再回落固定 666666；首次部署生成随机口令并仅打印一次
        initial_pw = secrets.token_urlsafe(9)
        data = {'pwhash': _hash_pw(initial_pw, salt), 'salt': salt, 'admins': ['admin']}
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = USERS_FILE.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, USERS_FILE)  # 原子写：半文件不可能落盘
        print(f'[auth] users.json 已 bootstrap；初始口令（仅本次打印，请立即记录并轮换）: {initial_pw}')
        mtime = USERS_FILE.stat().st_mtime
    _USERS_CACHE = (mtime, data)
    return data

def _role_of(username: str) -> str:
    return 'admin' if username in _users().get('admins', []) else 'viewer'

def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip('=')

def _sign_token(username: str, role: str) -> str:
    payload = _b64u(json.dumps({'u': username, 'r': role, 'exp': int(_time_auth.time()) + AUTH_TTL_S},
                               separators=(',', ':')).encode())
    sig = _b64u(_hmac_auth.new(AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    return f'{payload}.{sig}'

def _verify_token(token: str):
    """→ (username, role) | None。过期/伪造/格式错统一 None（401 不区分原因，方案 §4）"""
    try:
        payload, sig = token.split('.', 1)
        expect = _b64u(_hmac_auth.new(AUTH_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
        if not secrets.compare_digest(sig, expect):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        if not isinstance(data.get('exp'), int) or data['exp'] < _time_auth.time():
            return None
        u = data.get('u')
        if not isinstance(u, str) or not _USERNAME_RE.match(u):
            return None
        return u, (data.get('r') if data.get('r') in ('admin', 'viewer') else 'viewer')
    except Exception:
        return None

@app.middleware('http')
async def auth_gate(request: Request, call_next):
    # 既有离线单测的进程内旁路（app.state，非 env——生产环境无路径可达；见 tests/conftest.py）
    if getattr(app.state, 'auth_bypass', False):
        return await call_next(request)
    # 豁免：登录端点自身 / 健康检查 / CORS 预检（浏览器预检不带 cookie）
    if request.method == 'OPTIONS' or request.url.path in AUTH_EXEMPT_PATHS:
        return await call_next(request)
    # 服务令牌：本机内部调用（pi extension 工具链，网关注入令牌）
    _svc = _service_token()
    if _svc and request.headers.get('X-Prism-Service') == _svc:
        request.state.username, request.state.role = 'service', 'admin'
        return await call_next(request)
    ident = _verify_token(request.cookies.get(AUTH_COOKIE, ''))
    if ident is None:
        return Response(json.dumps({'detail': '未登录'}), status_code=401, media_type='application/json')
    request.state.username, request.state.role = ident
    return await call_next(request)


# B2（2026-11-02）：登录失败限流——按 (IP, 用户名) 组合，20 次/10 分钟锁 10 分钟。
# 不能只按用户名：共享口令下所有人都是 admin，一人连错会锁全员。
# 不能只按 IP：办公网共用出口 IP，会误伤同事（与 nginx login_zone 叠加更严）。
_LOGIN_FAILS: dict = {}
_LOGIN_WINDOW_S = 600
_LOGIN_MAX_FAILS = 20


def _login_key(request, username: str):
    ip = request.headers.get('X-Real-IP') or (request.client.host if request.client else '')
    return (ip, username.lower())


def _login_blocked(key) -> bool:
    now = _time_auth.time()
    arr = [t for t in _LOGIN_FAILS.get(key, []) if now - t < _LOGIN_WINDOW_S]
    _LOGIN_FAILS[key] = arr
    return len(arr) >= _LOGIN_MAX_FAILS


@app.post('/auth/login')
async def auth_login(req: dict, request: Request):
    """统一口令门：用户名（归因+分层用）+ 共享密码。成功发 HttpOnly cookie（7 天）。"""
    username, password = req.get('username'), req.get('password')
    if not isinstance(username, str) or not _USERNAME_RE.match(username) or not isinstance(password, str):
        raise HTTPException(400, '用户名或密码格式不合法')
    key = _login_key(request, username)
    if _login_blocked(key):
        raise HTTPException(429, '登录失败次数过多，请 10 分钟后再试')
    u = _users()
    # 恒时比较；失败文案不区分用户名/密码哪个错
    if not secrets.compare_digest(_hash_pw(password, u['salt']), u['pwhash']):
        _LOGIN_FAILS.setdefault(key, []).append(_time_auth.time())
        raise HTTPException(401, '用户名或密码错误')
    _LOGIN_FAILS.pop(key, None)
    role = _role_of(username)
    resp = JSONResponse({'username': username, 'role': role})
    resp.set_cookie(AUTH_COOKIE, _sign_token(username, role), max_age=AUTH_TTL_S,
                    httponly=True, samesite='lax', path='/',
                    secure=(os.environ.get('PRISM_ENV') == 'prod'))
    return resp


@app.get('/auth/me')
def auth_me(request: Request):
    """前端启动时恢复身份（本路由在门禁保护内，state 由中间件注入）"""
    return {'username': request.state.username, 'role': request.state.role}


@app.get('/health/report')
def health_report():
    """A2 每日巡检汇总（2026-11-02）：读云端 /data/health/latest.json。

    受登录门禁保护（AUTH_EXEMPT_PATHS 只豁免 /health），不新增公网面；
    报告由 ECS cron 每日 08:00 跑 deploy/daily_health.py 生成。
    """
    p = Path('/data/health/latest.json')
    if not p.exists():
        raise HTTPException(404, '暂无巡检报告（每日 08:00 生成）')
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception as e:
        raise HTTPException(500, f'巡检报告读取失败: {e}')


# ---------------------------------------------------------------------------
# T-7.3 /events + SQLite 事件库（北极星指标数据源，独立库写多读少）
# ---------------------------------------------------------------------------
EVENTS_DB = str(Path(__file__).parent.parent / 'prism_events.db')

def _init_events_db():
    import sqlite3 as _s
    c = _s.connect(EVENTS_DB)
    try:
        c.execute('''CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            local_id TEXT,
            session_id TEXT,
            page TEXT,
            series_key TEXT,
            value TEXT,
            ts TEXT NOT NULL
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(event_type, ts)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_events_local ON events(local_id)')
        c.commit()
    finally:
        c.close()

_init_events_db()

# 块0.5 D-1：脱敏读跨语言 spec（shared/redaction.json），消除双实现
import re as _re
import json as _json
from pathlib import Path as _Path
_REDACTION_SPEC_PATH = _Path(__file__).parent.parent / 'shared' / 'redaction.json'
try:
    _redaction_spec = _json.loads(_REDACTION_SPEC_PATH.read_text(encoding='utf-8'))
except Exception:
    _redaction_spec = {"vin": "[A-HJ-NPR-Z0-9]{17}", "plate": "[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤川青藏琼宁][A-Z][A-HJ-NP-Z0-9]{4,5}[A-HJ-NP-Z0-9]"}
_VIN_RE = _re.compile(_redaction_spec['vin'])
_PLATE_RE = _re.compile(_redaction_spec['plate'])

def sanitize_text(s: str) -> str:
    if not isinstance(s, str): return s
    s = _VIN_RE.sub('***', s)
    s = _PLATE_RE.sub('***', s)
    return s


@app.post('/events')
async def post_events(request: Request):
    """T-7.3 接收前端埋点事件（批量，sendBeacon）。
    多轮评估批 change T5（身份焊死）：local_id 过 resolve_user_id——token 身份覆盖自报值，
    全站最后一条未覆盖端点堵死（北极星 DAU 实名口径的服务端保证）。同批事件统一身份
    （一个请求一个人的物理事实）；无 token 旁路态回落逐条自报（防御性不变式，门后理论到不了）。"""
    body = await request.body()
    try:
        import json as _j
        payload = _j.loads(body)
    except Exception:
        raise HTTPException(400, 'invalid json')
    events = payload.get('events') if isinstance(payload, dict) else payload
    if not isinstance(events, list):
        raise HTTPException(400, 'events must be a list')

    # P0 北极星隔离（2026-10-26）：eval 栈（prism.py eval start）不写产品事件库——
    # 评估流量混入会让 DAU/结论数/采纳率全部失真，且事后无法从事件行区分。
    if os.environ.get('PRISM_EVAL_STACK') == '1':
        return {'ok': True, 'inserted': 0, 'skipped': 'eval_stack'}

    # 请求级解一次（批量共享）；'default'=无 token 旁路态 → 回落逐条自报（Gap9 防御）
    resolved_id = resolve_user_id(request, None)
    resolved = resolved_id if resolved_id != 'default' else None

    import sqlite3 as _s
    from datetime import datetime as _dt
    now = _dt.utcnow().isoformat()
    conn = _s.connect(EVENTS_DB)
    rows = []
    for e in events:
        if not isinstance(e, dict): continue
        et = e.get('event_type')
        if not et: continue
        rows.append((
            et,
            sanitize_text(str(resolved if resolved else e.get('local_id', ''))),
            sanitize_text(str(e.get('session_id', ''))) if e.get('session_id') else None,
            sanitize_text(str(e.get('page', ''))),
            sanitize_text(str(e.get('series_key', ''))) if e.get('series_key') else None,
            sanitize_text(str(e.get('value', ''))) if e.get('value') else None,
            e.get('ts', now),
        ))
    try:
        conn.executemany(
            'INSERT INTO events (event_type, local_id, session_id, page, series_key, value, ts) VALUES (?,?,?,?,?,?,?)',
            rows
        )
        conn.commit()
    finally:
        conn.close()
    return {'ok': True, 'inserted': len(rows)}


# ---------------------------------------------------------------------------
# 用户反馈（2026-11-04）：主界面右下角入口 → user_feedback 表 → 北极星看板明细列表
# 存储选型：独立表落在 prism_events.db（该库已同时挂载给 prism-api 可写、prism-ops 只读，
# 不新增挂载）；不用 events.event_type='user_feedback' 是为了不污染北极星事件口径（DAU 等）。
# ---------------------------------------------------------------------------
FEEDBACK_KINDS = {'issue': '问题', 'suggestion': '建议', 'other': '其他'}
FEEDBACK_MAX_LEN = 2000

def _init_feedback_table():
    import sqlite3 as _s
    c = _s.connect(EVENTS_DB)
    try:
        c.execute('''CREATE TABLE IF NOT EXISTS user_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'other',
            content TEXT NOT NULL,
            ts TEXT NOT NULL
        )''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_user_feedback_ts ON user_feedback(ts)')
        c.commit()
    finally:
        c.close()

_init_feedback_table()


@app.post('/feedback')
async def post_feedback(req: dict, request: Request):
    """用户反馈入库（登录门禁内：用户身份取 token，不信前端自报）。
    kind 三选一（issue/suggestion/other）；content 1-2000 字；入库前走 sanitize_text 脱敏。
    错误一律显式 400 + 中文原因（前端会展示，不静默）。"""
    kind = req.get('kind')
    content = req.get('content')
    if kind not in FEEDBACK_KINDS:
        raise HTTPException(400, '反馈类型不合法')
    if not isinstance(content, str):
        raise HTTPException(400, '反馈内容格式不合法')
    text = content.strip()
    if not text:
        raise HTTPException(400, '请填写反馈内容')
    if len(text) > FEEDBACK_MAX_LEN:
        raise HTTPException(400, f'反馈内容最多 {FEEDBACK_MAX_LEN} 字')
    username = getattr(request.state, 'username', '') or ''
    if not username:
        raise HTTPException(401, '未登录')
    import sqlite3 as _s
    from datetime import datetime as _dt
    conn = _s.connect(EVENTS_DB)
    try:
        cur = conn.execute(
            'INSERT INTO user_feedback (username, kind, content, ts) VALUES (?,?,?,?)',
            (sanitize_text(username), kind, sanitize_text(text), _dt.utcnow().isoformat()),
        )
        conn.commit()
        fid = cur.lastrowid
    finally:
        conn.close()
    return {'ok': True, 'id': fid, 'kind': kind}


def _open_live():
    """实时直读 Prism 主库（只读）。2026-10-08：物化视图 prism_views.db 退役。"""
    conn = sqlite3.connect(f"file:{AUTOHOME_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


# config_snapshots.categories 关键配置项白名单（与 refresh.py 原 mv_config_spec 口径一致）
_CONFIG_KEY_ITEMS = ["座椅材质", "侧窗多层隔音玻璃", "前轮胎规格", "CLTC纯电续航", "车机智能芯片"]


def _flatten_config_rows(conn, series_id: int) -> list:
    """实时展平 config_snapshots.categories（复刻原 mv_config_spec 口径：年款标注 + 白名单关键项）。"""
    import json as _j
    import re as _re2
    rows = conn.execute(
        "SELECT series_id, series_name, categories FROM config_snapshots WHERE series_id=?",
        (series_id,)).fetchall()
    out = []
    for r in rows:
        cats = r['categories']
        if isinstance(cats, str):
            try:
                cats = _j.loads(cats)
            except Exception:
                cats = {}
        cats = cats or {}
        all_specs, name_map = set(), {}
        for _cat_name, catv in cats.items():
            if not isinstance(catv, dict):
                continue
            for _sub_name, subv in catv.items():
                if isinstance(subv, dict):
                    for spec, val in subv.items():
                        all_specs.add(spec)
                        if spec not in name_map and isinstance(val, str) and "款" in val:
                            name_map[spec] = val
        for spec in sorted(all_specs):
            mk = _re2.search(r"(20\d{2})款", name_map.get(spec, ""))
            niankuan = (mk.group(1) + "款") if mk else None
            for _cat_name, catv in cats.items():
                if not isinstance(catv, dict):
                    continue
                for sub_name, subv in catv.items():
                    if not isinstance(subv, dict):
                        continue
                    val = subv.get(spec)
                    if val is None:
                        continue
                    for ki in _CONFIG_KEY_ITEMS:
                        if ki in sub_name:
                            val_str = val if isinstance(val, str) else _j.dumps(val, ensure_ascii=False)
                            out.append({
                                'series_id': r['series_id'], 'series_name': r['series_name'],
                                'spec_id': spec, '年款': niankuan,
                                '车型名称': name_map.get(spec, ''), 'key_config': ki,
                                'key_config_value': val_str,
                            })
                            break
    return out


# 命名归一化：series_summaries.series_name 不带品牌前缀（"海豚"/"零跑B10"），
# sales_trim.series 带品牌前缀+空格（"比亚迪 海豚"/"零跑 B10"）。
# 两个问题：①品牌前缀不一致 ②series_name 内部空格（"零跑 B10" vs "零跑B10"）。
# 修法：查 sales_trim 时用 REPLACE(series,' ','') LIKE '%series_name去空格%'（去空格后子串匹配）
def normalize_series_for_sales(series_key: str, conn=None):
    """返回 (去空格后的 LIKE 模式, brand_name)。
    查询用：WHERE REPLACE(series,' ','') LIKE pattern。
    conn 可选：复用调用者连接。"""
    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(f"file:{AUTOHOME_DB}?immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
    try:
        r = conn.execute("SELECT series_name, brand_name FROM series_summaries WHERE series_name=?", (series_key,)).fetchone()
        if r:
            sn = r['series_name'].replace(' ', '')
            return f"%{sn}%", r['brand_name']
        return f"%{series_key.replace(' ','')}%", None
    finally:
        if own_conn:
            conn.close()


# 2026-10-08：_meta 改为实时派生（物化视图退役后不再有 *_meta 表）
def _live_meta(dtype: str) -> dict:
    """实时口径元信息。as_of 取库内数据自身时点（非查询时间），语义对齐旧 mv *_meta。"""
    src = {
        'reviews': 'review_tags + series_summaries (live)',
        'sales': "sales_trim (month LIKE '%月末') (live)",
        'config': 'config_snapshots (live)',
    }.get(dtype, dtype)
    as_of = ''
    try:
        conn = _open_live()
        try:
            if dtype == 'reviews':
                r = conn.execute("SELECT MAX(fetched_at) AS m FROM owner_reviews").fetchone()
                as_of = (r['m'] if r and r['m'] else '') or ''
            elif dtype == 'config':
                r = conn.execute("SELECT MAX(fetched_at) AS m FROM config_snapshots").fetchone()
                as_of = (r['m'] if r and r['m'] else '') or ''
            else:
                # sales-asof 修复（sales-asof修复 change，2026-10-15）：sales_trim 无 fetched_at 列，
                # 旧查询抛 OperationalError 被 except 吞 → as_of 恒空（工具契约"返回带 as_of"从未兑现）。
                # 改用 /dash/as_of 同源口径：最新"月末"批（月中批=价格快照，零售滞后为空，但批存在即算时点）
                row = conn.execute(
                    "SELECT year, MAX(CAST(month AS INTEGER)) FROM sales_trim "
                    "WHERE month LIKE '%月末' GROUP BY year ORDER BY year DESC LIMIT 1"
                ).fetchone()
                as_of = f'{row[0]}-{row[1]}月末' if row and row[1] is not None else ''
        finally:
            conn.close()
    except sqlite3.Error:
        as_of = ''
    return {
        'as_of': as_of,
        'source': src,
        '口径': '实时直读 Prism 主库（prism-dashboards/data/autohome.db）；物化视图 prism_views.db 已于 2026-10-08 退役',
    }


# ---------------------------------------------------------------------------
# /dashboard/{type}
# ---------------------------------------------------------------------------
@app.get('/dashboard/{dtype}')
def dashboard(dtype: str, request: Request, series_key: str | None = None, series_id: str | None = None, year: int | None = None, month: int | None = None):
    # query_sales month 实装（query-sales-month过滤 change，2026-10-15）：fail-loud，1-12 之外直接 400
    # 注：签名级参数 → 校验对所有 dtype 生效（reviews/config 传非法 month 也 400 而非静默忽略；
    # 已核实现网零消费方如此调用——web 前端不调 /dashboard/，工具 schema 仅 query_sales 有 month）
    if month is not None and not (1 <= month <= 12):
        raise HTTPException(400, f'month must be 1-12, got {month}')
    conn = _open_live()
    try:
        if dtype == 'reviews':
            # series_key → model_id 反查
            if not series_id:
                r = conn.execute("SELECT series_id FROM series_summaries WHERE series_name=?", (series_key,)).fetchone()
                if not r:
                    raise HTTPException(404, f"series {series_key} 不在 series_summaries")
                series_id = int(r['series_id'])
            # 实时聚合（口径同原 mv_reviews_dim：按 model_id×tag_category 统计 pro/con 标签行数）
            rows = conn.execute(
                "SELECT t.model_id, COALESCE(s.series_name, '') AS series_name, t.tag_category, "
                "       t.pro_count, t.con_count, t.pro_count + t.con_count AS total_count, "
                "       CASE WHEN t.pro_count + t.con_count > 0 "
                "            THEN CAST(t.con_count AS REAL) / (t.pro_count + t.con_count) ELSE 0 END AS con_ratio, "
                "       t.pro_count - t.con_count AS net_attitude "
                "  FROM (SELECT model_id, tag_category, "
                "               COUNT(CASE WHEN sentiment IN ('pro','1','正面') THEN 1 END) AS pro_count, "
                "               COUNT(CASE WHEN sentiment IN ('con','-1','负面') THEN 1 END) AS con_count "
                "          FROM review_tags WHERE CAST(model_id AS TEXT)=? GROUP BY model_id, tag_category) t "
                "  LEFT JOIN series_summaries s ON s.series_id = t.model_id "
                " ORDER BY total_count DESC",
                (str(series_id),)
            ).fetchall()
            return {'rows': [dict(r) for r in rows], '_meta': _live_meta('reviews')}

        elif dtype == 'sales':
            if not series_key:
                raise HTTPException(400, 'series_key required')
            group_by = request.query_params.get('group_by', 'month') if hasattr(request, 'query_params') else 'month'
            pattern, _ = normalize_series_for_sales(series_key, conn)
            # P1-3：group_by=spec → 读 sales_trim 版型明细
            if group_by == 'spec':
                rows = conn.execute(
                    "SELECT model_name, year, month, retail, tp, msrp FROM sales_trim WHERE REPLACE(series,' ','') LIKE ? AND month LIKE '%月末' ORDER BY model_name, year, month",
                    (pattern,)
                ).fetchall()
                if year:
                    rows = [r for r in rows if r['year'] == year]
                if month is not None:
                    # 行内过滤取前导数字（禁 LIKE 'N月末'——'1月末' 会误配 '11月末'）；月末口径限定已在上方 SQL
                    kept = []
                    for r in rows:
                        m = re.match(r'^(\d+)', str(r['month'] or ''))
                        if m and int(m.group(1)) == month:
                            kept.append(r)
                    rows = kept
                return {'rows': [dict(r) for r in rows], '_meta': _live_meta('sales')}
            # 实时月度聚合（口径同原 mv_sales_monthly：月末行按 series+year+month 汇总，month 取月号数字）
            sql = ("SELECT series, year, CAST(TRIM(REPLACE(month,'月末','')) AS INTEGER) AS month, "
                   "SUM(retail) AS retail_sum, AVG(tp) AS tp_avg, COUNT(*) AS row_count "
                   "FROM sales_trim WHERE REPLACE(series,' ','') LIKE ? AND month LIKE '%月末' ")
            params = [pattern]
            if year:
                sql += 'AND year=? '
                params.append(year)
            if month is not None:
                # month 过滤只缩行集不改口径：%月末' 限定仍先生效（销量红线）
                sql += "AND CAST(TRIM(REPLACE(month,'月末','')) AS INTEGER)=? "
                params.append(month)
            sql += "GROUP BY series, year, month ORDER BY year, CAST(TRIM(REPLACE(month,'月末','')) AS INTEGER)"
            rows = conn.execute(sql, params).fetchall()
            return {'rows': [dict(r) for r in rows], '_meta': _live_meta('sales')}

        elif dtype == 'config':
            # series_key → series_id 反查（与 reviews 同逻辑）
            if not series_id and series_key:
                r = conn.execute("SELECT series_id FROM series_summaries WHERE series_name=?", (series_key,)).fetchone()
                if r:
                    series_id = int(r['series_id'])
            if not series_id:
                raise HTTPException(400, 'series_id or series_key required')
            # 实时展平（口径同原 mv_config_spec）
            return {'rows': _flatten_config_rows(conn, series_id), '_meta': _live_meta('config')}

        else:
            raise HTTPException(400, f'unknown dashboard type: {dtype}')
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# /chat/stream（转发 pi_gateway :9100，NDJSON 透传）
# ---------------------------------------------------------------------------
def validate_user_id(uid):
    if not isinstance(uid, str) or not re.match(r'^[A-Za-z0-9_-]+$', uid):
        raise HTTPException(400, 'invalid user_id')
    return uid

def resolve_user_id(request: Request, raw):
    """登录门禁 T2：user_id 以 token 为准（auth_gate 注入 request.state.username）——
    前端自报字段废弃，body/query 值仅在门禁旁路态（离线测试直调）回落；validate_user_id 仍跑防注入。"""
    tok = getattr(request.state, 'username', None)
    if tok:
        return validate_user_id(tok)
    return validate_user_id(raw if raw is not None else 'default')

@app.post('/chat/stream')
async def chat_stream(req: dict, request: Request):
    """流式对话，转发到 Node pi_gateway（RPC 子进程池），NDJSON 透传。"""
    user_id = resolve_user_id(request, req.get('user_id'))
    message = req.get('message')
    if not isinstance(message, str) or not message.strip():
        raise HTTPException(400, 'message required')

    async def stream():
        try:
            async with httpx_client(httpx.Timeout(300.0)) as client:
                async with client.stream('POST', f'{PI_SERVER}/chat', json={
                    'message': message,
                    'user_id': user_id,
                    'series_key': req.get('series_key'),
                    'scope': req.get('scope', 'agent'),
                    'session_id': req.get('session_id'),
                    # P0 链路焊死（2026-10-26）：eval 批次/题级标识必须透传到网关，
                    # 否则 ctx.json 拿不到 runId、轨迹无法按 run 取 verdict（整批判分失真）。
                    'eval_run_id': req.get('eval_run_id'),
                    'eval_task_id': req.get('eval_task_id'),
                    'eval_repeat': req.get('eval_repeat'),
                }) as r:
                    # P0-1c：显式检查非 2xx——否则 4xx/5xx 不抛异常 → 静默空响应（前端收不到任何内容）
                    if r.status_code >= 400:
                        body = (await r.aread())[:300].decode('utf-8', 'ignore')
                        yield json.dumps({'type': 'error', 'data': {'message': f'对话服务返回 {r.status_code}: {body}'}}) + '\n'
                        return
                    async for line in r.aiter_lines():
                        if line.strip():
                            yield line + '\n'
        except httpx.HTTPError:
            yield json.dumps({'type': 'error', 'data': {'message': '对话服务暂时不可用，请重试'}}) + '\n'
        except Exception:
            yield json.dumps({'type': 'error', 'data': {'message': '对话处理出错，请重试'}}) + '\n'
    return StreamingResponse(stream(), media_type='application/x-ndjson')


@app.post('/chat/abort')
async def chat_abort(req: dict, request: Request):
    """中止在途轮（中止键与单一在途轮次，2026-10-12）：透传 gateway /abort。
    S8 P1-5：失败必须非 2xx——前端 abortChat 只看 res.ok，200+{ok:false} 会把
    中止失败静默当成功（只剩本地断流兜底，网关轮继续跑、锁滞留）。"""
    user_id = resolve_user_id(request, req.get('user_id'))
    if not user_id:
        raise HTTPException(400, 'invalid user_id')   # 防 None 落到 gateway 的 default 用户
    try:
        async with httpx_client(15.0) as c:
            r = await c.post(f'{PI_SERVER}/abort', json={'user_id': user_id})
            return JSONResponse(status_code=r.status_code, content=r.json())
    except Exception:
        return JSONResponse(status_code=502, content={'ok': False, 'error': '中止服务暂不可达'})


# ---------------------------------------------------------------------------
# /session（转发 pi_server SessionManager）
# ---------------------------------------------------------------------------
@app.get('/session')
async def list_sessions(request: Request, user_id: str = Query('default')):
    user_id = resolve_user_id(request, user_id)
    async with httpx_client(30.0) as c:
        r = await c.get(f'{PI_SERVER}/session', params={'user_id': user_id})
        return r.json()


@app.post('/session')
async def create_session(req: dict, request: Request):
    user_id = resolve_user_id(request, req.get('user_id'))
    async with httpx_client(30.0) as c:
        r = await c.post(f'{PI_SERVER}/session', json={**req, 'user_id': user_id})
        return r.json()


# ---------------------------------------------------------------------------
# /sentiment/vehicles-all（舆情全量车名单，2026-10-20 舆情工具层跟进 T1）
# ---------------------------------------------------------------------------
# extension resolveVehicleId 两级解析的 fallback 数据源：fleet-overview 与舆情
# /api/vehicles 均只返回 active（16 台 paused 车断链误报"未收录"，红线#1），而
# 舆情侧无任何全量名单端点。身份映射（车名→UUID+status）是 Prism 适配层职责，
# 此处只读直查舆情库（与 /verify/claim 的 SENTIMENT_DB 同源同模式）。
@app.get('/sentiment/vehicles-all')
async def sentiment_vehicles_all():
    try:
        conn = sqlite3.connect(f'file:{SENTIMENT_DB}?mode=ro', uri=True)
    except sqlite3.Error:
        raise HTTPException(503, detail='sentiment db unreachable')
    try:
        rows = conn.execute('SELECT id, name, status, brand FROM vehicles').fetchall()
    except sqlite3.Error:
        # P2-5（Step7 审查）：表级异常对照 /verify/claim 的防护语义，不裸 500
        raise HTTPException(503, detail='sentiment db read failed')
    finally:
        conn.close()
    return [{'id': r[0], 'name': r[1], 'status': r[2], 'brand': r[3]} for r in rows]


# ---------------------------------------------------------------------------
# /sentiment-board/{path}（反代舆情 Board，供前端 iframe 同源嵌入）
# ---------------------------------------------------------------------------
@app.get('/sentiment-board/{path:path}')
async def sentiment_proxy(path: str, request: Request):
    # P1#10：path 白名单（禁 .. 和绝对路径）
    if '..' in path.split('/') or path.startswith('/'):
        raise HTTPException(400, 'invalid path')
    target = f'{SENTIMENT_BOARD}/{path}'
    if request.url.query:
        target += '?' + request.url.query
    async with httpx_client(30.0) as c:
        r = await c.get(target)
        ct = r.headers.get('content-type', 'text/html')
        # 只允许 HTML/JSON/CSS/JS/图片
        if not any(t in ct for t in ['text/html', 'application/json', 'text/css', 'javascript', 'image']):
            ct = 'text/html'
        return Response(r.content, status_code=r.status_code, media_type=ct)


@app.delete('/session/{session_id}')
async def delete_session(session_id: str, request: Request):
    """D2（2026-11-02）：删除会话——转发 pi_gateway（删 jsonl + names sidecar）。"""
    user_id = resolve_user_id(request, None)
    async with httpx_client(15.0) as c:
        r = await c.delete(f'{PI_SERVER}/session/{session_id}', params={'user_id': user_id})
        if r.status_code >= 400:
            raise HTTPException(r.status_code if r.status_code < 500 else 502, '删除会话失败，请重试')
        return r.json()


@app.post('/session/rename')
async def rename_session(req: dict, request: Request):
    """B4：会话重命名——转发 pi_gateway（names.json sidecar，列表显示 custom_name）。"""
    user_id = resolve_user_id(request, req.get('user_id'))
    session_id = req.get('session_id')
    name = req.get('name')
    if not isinstance(session_id, str) or not session_id.strip() \
            or not isinstance(name, str) or not name.strip():
        raise HTTPException(400, 'session_id and name required')
    async with httpx_client(30.0) as c:
        r = await c.post(f'{PI_SERVER}/session/rename', json={
            'user_id': user_id,
            'session_id': session_id.strip(),
            'name': name.strip()[:60],
        })
        if r.status_code >= 400:
            raise HTTPException(502, '会话重命名失败，请重试')
        return r.json()


@app.get('/session/messages')
async def session_messages(request: Request, user_id: str = Query('default'), session_id: str = Query(...)):
    """会话历史回显：转发 pi_gateway（switch_session → get_messages → {session_id, messages}）。"""
    user_id = resolve_user_id(request, user_id)
    session_id = (session_id or '').strip()
    if not session_id:
        raise HTTPException(400, 'session_id required')
    try:
        async with httpx_client(30.0) as c:
            r = await c.get(f'{PI_SERVER}/session/messages',
                            params={'user_id': user_id, 'session_id': session_id})
    except httpx.HTTPError:
        # 审查P2-6：网关不可达曾裸 500——固定文案 502（与 /chat/stream 同款，不泄内部信息）
        raise HTTPException(502, '获取会话历史失败，请重试')
    if r.status_code >= 400:
        # 网关固定文案透传（404 session not found / 409 上一请求进行中），异常兜底 502 固定文案
        try:
            return JSONResponse(status_code=r.status_code, content=r.json())
        except Exception:
            raise HTTPException(502, '获取会话历史失败，请重试')
    return r.json()


# ---------------------------------------------------------------------------
# /dash/as_of（C3）：看板数据时点——iframe 化后看板无法上抛 _meta，
# Prism 看板顶部栏的 as_of 由本端点统一供给（与 /dashboard 同源直读主库）。
# 注意：必须注册在 /dash/{path:path} 反代之前，否则被反代吞掉。
# ---------------------------------------------------------------------------
@app.get('/dash/as_of')
def dash_as_of():
    sales = reviews = config = None
    conn = sqlite3.connect(f'file:{AUTOHOME_DB}?mode=ro', uri=True)
    try:
        # 销量：最新"月末"批（month 形如 '9月末'，月中批为价格快照、零售滞后为空）
        row = conn.execute(
            "SELECT year, MAX(CAST(month AS INTEGER)) FROM sales_trim "
            "WHERE month LIKE '%月末' GROUP BY year ORDER BY year DESC LIMIT 1"
        ).fetchone()
        sales = f'{row[0]}-{row[1]}月末' if row else None
        # 口碑：最新发帖日（koubei 页同口径 MAX(post_date)）
        r2 = conn.execute('SELECT MAX(post_date) FROM owner_reviews').fetchone()
        reviews = str(r2[0])[:10] if r2 and r2[0] else None
        # E5（2026-11-02）：配置看板时点（此前缺失，状态栏显示「—」）
        r4 = conn.execute('SELECT MAX(fetched_at) FROM config_snapshots').fetchone()
        config = str(r4[0])[:10] if r4 and r4[0] else None
    finally:
        conn.close()
    # 舆情：最新采集日（2026-10-22 用户拍板 A：状态栏加舆情段）。口径=采集日
    # （管线新鲜度，raw_posts.collected_at 存 UTC → 本地+8 取日期）而非发帖日——
    # 舆情是日更管线，段义是"跑到哪天了"；与口碑（批式深采 MAX(post_date) 发帖日）
    # 语义不同属有意。库不可达 fail-soft 缺省（前端 filter(Boolean) 自动省略该段）。
    sentiment = None
    try:
        sconn = sqlite3.connect(f'file:{SENTIMENT_DB}?mode=ro', uri=True)
        try:
            r3 = sconn.execute('SELECT MAX(collected_at) FROM raw_posts').fetchone()
            if r3 and r3[0]:
                from datetime import datetime, timedelta
                utc = datetime.strptime(str(r3[0])[:19], '%Y-%m-%d %H:%M:%S')
                sentiment = (utc + timedelta(hours=8)).strftime('%Y-%m-%d')
        finally:
            sconn.close()
    except sqlite3.Error:
        sentiment = None
    return {'sales': sales, 'reviews': reviews, 'config': config, 'sentiment': sentiment}


# ---------------------------------------------------------------------------
# /dash/{path}（反代 Prism Dashboards 子服务 :8010，供 prism-web iframe 嵌入三看板）
# 迁移自 Atuohome_Agent（口碑 / 配置 / 市场），服务见 ../prism-dashboards/app.py
# ---------------------------------------------------------------------------
DASHBOARDS = os.environ.get('PRISM_DASHBOARDS', 'http://127.0.0.1:8010')

@app.api_route('/dash/{path:path}', methods=['GET', 'POST'])
async def dash_proxy(path: str, request: Request):
    # path 白名单（禁 .. 和绝对路径）
    if '..' in path.split('/') or path.startswith('/'):
        raise HTTPException(400, 'invalid path')
    target = f'{DASHBOARDS}/dash/{path}'
    if request.url.query:
        target += '?' + request.url.query
    body = await request.body() if request.method == 'POST' else None
    req_headers = {'content-type': request.headers.get('content-type', 'application/json')} if body else None
    async with httpx_client(120.0) as c:
        try:
            r = await c.request(request.method, target, content=body, headers=req_headers)
        except httpx.HTTPError:
            raise HTTPException(502, '看板服务（prism-dashboards）不可达')
        ct = r.headers.get('content-type', 'text/html')
        headers = {}
        # CSV 导出（/dash/koubei/series/{id}/export）需透传下载头
        if r.headers.get('content-disposition'):
            headers['content-disposition'] = r.headers['content-disposition']
        return Response(r.content, status_code=r.status_code, media_type=ct, headers=headers)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# /ui-response · T-5.3 P0#7 转发 pi_gateway（ui_request 双向通信回填）
# ---------------------------------------------------------------------------
@app.post('/ui-response')
async def ui_response(request: Request):
    body = await request.body()
    try:
        import json as _j
        payload = _j.loads(body)
    except Exception:
        raise HTTPException(400, 'invalid json')
    # B3（2026-11-02）：浏览器回填以 token 身份为准，不信任 body 里的 user_id；
    # service token（pi 内部/eval runner）保留 body 指定的目标用户，避免破坏回填路由。
    _who = getattr(request.state, 'username', None)
    if _who and _who != 'service':
        payload['user_id'] = validate_user_id(_who)
    elif _who == 'service':
        payload['user_id'] = validate_user_id(payload.get('user_id') or 'default')
    async with httpx_client(30.0) as c:
        try:
            r = await c.post(f'{PI_SERVER}/ui-response', json=payload)
            return Response(r.content, status_code=r.status_code, media_type='application/json')
        except httpx.HTTPError:
            raise HTTPException(502, 'pi_gateway 不可达')


# Agent 工具取数层：直连 Prism Dashboards 子服务（迁移后不再依赖 Atuohome :8001）
# ---------------------------------------------------------------------------
DASHBOARDS_HTTP = os.environ.get('PRISM_DASHBOARDS_HTTP') or os.environ.get('AUTOHOME_HTTP', 'http://127.0.0.1:8010')

# 工具名 → Prism Dashboards HTTP 端点映射（前缀 /dash，由子服务承载）
# 2026-10-08 修正：仅映射 JSON API（原 6 条指向 HTML 看板页）；4 工具退役（8010 无等价：代际/能耗/新闻/报价）
DASHBOARDS_TOOL_MAP = {
    'search_cars':        ('GET',  '/dash/market/api/series-list'),
    'series_filter':      ('GET',  '/dash/market/api/series-filter'),         # 人工题集转金标 Block 0：search_cars 筛选路径（服务端过滤）
    'get_model_detail':    ('GET',  '/dash/koubei/series/{model_id}/data'),      # 车系下钻 JSON（facts/tag_dist/stream）
    'get_similar_models':  ('GET',  '/dash/koubei/peer-compare-v2'),             # 双车对比：a_mid+b_mid（数字 model_id）
    'get_trims':           ('GET',  '/dash/config/trims/{series_id}'),
    'get_config_detail':   ('GET',  '/dash/config/compare-horizontal'),          # sel=series_id:spec_id（2-6 个，可重复）
    'get_review_analysis': ('GET',  '/dash/koubei/series/{model_id}/data'),      # tag_dist = 维度聚合
    'search_reviews':      ('GET',  '/dash/koubei/series/{model_id}/data'),      # kw=关键词 → stream 原文流
    'get_dimension_reviews': ('GET', '/dash/koubei/series/{model_id}/data'),     # tag=维度 → stream 原文流
    'get_sales_detail':    ('GET',  '/dash/market/api/retail'),                  # 参数 series（车系名，非 model_id）
    'score_models':        ('GET',  '/dash/config/concept-configs'),
    # 配置赋值口径改造 M3：差价引擎出口（sel 可重复，第 1 个为基准；POST+manual_prices 仅前端用，agent 走 GET）
    'compare_configs_valued': ('GET', '/dash/config/compare-valued'),
}
# P1-2：/autohome 反代 TTL 缓存（默认 60s），缓解上游 series-list 10.8s / 160KB
import time as _time
import threading as _threading
_AUTOHOME_CACHE = {}          # key → (expire_ts, content, media_type, status)
_AUTOHOME_CACHE_TTL = float(os.environ.get('PRISM_AUTOHOME_CACHE_TTL', '60'))

def _autohome_cache_get(key):
    ent = _AUTOHOME_CACHE.get(key)
    if not ent:
        return None
    exp, content, mt, st = ent
    if exp < _time.time():
        _AUTOHOME_CACHE.pop(key, None)
        return None
    return content, mt, st

def _autohome_cache_set(key, content, mt, st):
    _AUTOHOME_CACHE[key] = (_time.time() + _AUTOHOME_CACHE_TTL, content, mt, st)


@app.api_route('/autohome/{tool_name}', methods=['GET', 'POST'])
async def autohome_proxy(tool_name: str, request: Request):
    if tool_name not in DASHBOARDS_TOOL_MAP:
        raise HTTPException(404, f'unknown tool: {tool_name}')
    method, path_template = DASHBOARDS_TOOL_MAP[tool_name]

    # 参数替换。多值查询参数必须保序保留（list of tuples）——dict() 会折叠重复键，
    # sel=a&sel=b 只剩 b，compare-valued 端点报"请提供 2-6 个"假错
    # （2026-10-13 skill v2 复盘实证：agent 路径 compare_configs_valued 从未成功过）
    q_items = list(request.query_params.multi_items())
    q_dict = dict(q_items)
    path = path_template
    for key in ['series_id', 'model_id']:
        if '{' + key + '}' in path and key in q_dict:
            path = path.replace('{' + key + '}', q_dict.pop(key))
            q_items = [(k, v) for k, v in q_items if k != key]

    # P1-2：GET 走 TTL 缓存，命中直接返回（不重复打上游）
    cache_key = None
    if method == 'GET':
        cache_key = tool_name + '|' + path + '|' + '&'.join(f'{k}={v}' for k, v in sorted(q_items))
        hit = _autohome_cache_get(cache_key)
        if hit:
            content, mt, st = hit
            return Response(content, status_code=st, media_type=mt)

    async with httpx_client(60.0) as c:
        try:
            if method == 'GET':
                r = await c.get(f'{DASHBOARDS_HTTP}{path}', params=q_items)
            else:
                body = await request.body()
                r = await c.post(f'{DASHBOARDS_HTTP}{path}', content=body, params=q_items, headers={'Content-Type': 'application/json'})
            # P1-2：成功响应写入 TTL 缓存
            if cache_key and r.status_code == 200:
                _autohome_cache_set(cache_key, r.content, 'application/json', r.status_code)
            return Response(r.content, status_code=r.status_code, media_type='application/json')
        except httpx.HTTPError:
            raise HTTPException(502, '看板服务（prism-dashboards）不可达')

# ---------------------------------------------------------------------------
# 社媒深挖能力包 M3：xlsx 导出（openpyxl）+ TikHub 状态探针
# ---------------------------------------------------------------------------
from dotenv import load_dotenv as _load_dotenv  # Gap5：key 单源 prism-api/.env
_load_dotenv(Path(__file__).parent / '.env')

import openpyxl as _openpyxl
from openpyxl.styles import Font as _XlFont
from openpyxl.utils import get_column_letter as _xl_col
from uuid import uuid4 as _uuid4
import time as _time

EXPORT_DIR = Path(__file__).parent / 'exports'
EXPORT_DIR.mkdir(exist_ok=True)
_EXPORT_MANIFEST = EXPORT_DIR / 'manifest.json'
_FILENAME_RE = re.compile(r'^[A-Za-z0-9_\-一-龥.]{1,60}$')
_TIKHUB_KEY_PRISM = os.environ.get('TIKHUB_KEY_PRISM', '').strip()
_TIKHUB_BASE = os.environ.get('TIKHUB_BASE_URL', 'https://api.tikhub.dev').rstrip('/')
_tikhub_status_cache = {'ts': 0.0, 'data': None}


def _export_manifest_load():
    try:
        return json.loads(_EXPORT_MANIFEST.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _export_manifest_save(m):
    _EXPORT_MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding='utf-8')


@app.post('/export')
async def export_document(request: Request):
    """xlsx 导出：{title, filename?, sheets:[{name, headers, rows}]} → {file_id, url, filename}"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(422, '请求体须为 JSON')
    title = str(body.get('title') or 'Prism 导出').strip()[:100]
    filename = str(body.get('filename') or '').strip()
    if not _FILENAME_RE.match(filename or ''):
        filename = f'export-{_time.strftime("%Y%m%d-%H%M%S")}.xlsx'
    sheets = body.get('sheets')
    if not isinstance(sheets, list) or not sheets:
        raise HTTPException(422, 'sheets 须为非空数组 [{name, headers, rows}]')
    if len(sheets) > 20:
        raise HTTPException(422, 'sheets 超上限（≤20）')

    wb = _openpyxl.Workbook()
    wb.remove(wb.active)
    used_names = set()
    rows_dropped = 0
    # P1 修复：社媒文本含 openpyxl 非法控制字符（\x0b/\x0c 等）会 IllegalCharacterError → 统一清洗
    _ILLEGAL_XL = _re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')
    _SHEET_NAME_BAD = _re.compile(r'[\\/:*?\[\]]')

    def _cell(x):
        if x is None or isinstance(x, (int, float)):
            return x
        return _ILLEGAL_XL.sub('', str(x))[:3000]

    for i, s in enumerate(sheets):
        if not isinstance(s, dict):
            raise HTTPException(422, f'sheets[{i}] 须为对象')
        name = _SHEET_NAME_BAD.sub('_', str(s.get('name') or f'Sheet{i + 1}').strip()[:31] or f'Sheet{i + 1}')
        while name in used_names:
            name = (name[:28] + f'_{len(used_names)}')[:31]
        used_names.add(name)
        headers = s.get('headers') if isinstance(s.get('headers'), list) else []
        rows = s.get('rows') if isinstance(s.get('rows'), list) else []
        if len(rows) > 5000:
            raise HTTPException(422, f'{name} rows 超上限（{len(rows)} > 5000），请先聚合再导出')
        ws = wb.create_sheet(name)
        ws.append([_cell(h) for h in headers])
        for cell in ws[1]:
            cell.font = _XlFont(bold=True)
        ws.freeze_panes = 'A2'
        for r in rows:
            if not isinstance(r, list):
                rows_dropped += 1  # P2：畸形行显式计数，不静默丢
                continue
            ws.append([_cell(x) for x in r])
        # 列宽自适应（前 50 行采样，上限 40）
        for ci in range(1, max(len(headers), 1) + 1):
            width = len(str(headers[ci - 1])) if ci <= len(headers) else 6
            for r in rows[:50]:
                if isinstance(r, list) and ci <= len(r) and r[ci - 1] is not None:
                    width = max(width, min(len(str(r[ci - 1])), 40))
            ws.column_dimensions[_xl_col(ci)].width = min(width + 2, 42)

    file_id = _uuid4().hex
    wb.save(EXPORT_DIR / f'{file_id}.xlsx')
    manifest = _export_manifest_load()
    manifest[file_id] = {
        'filename': filename, 'title': title,
        'sheets': len(sheets), 'created_at': _time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    _export_manifest_save(manifest)
    return {'file_id': file_id, 'filename': filename, 'sheets': len(sheets),
            'rows_dropped': rows_dropped, 'url': f'/export/download/{file_id}'}


@app.get('/export/download/{file_id}')
def export_download(file_id: str):
    """xlsx 下载（浏览器直链；file_id 必须 manifest 命中——hex id 构造路径，天然防穿越）"""
    entry = _export_manifest_load().get(file_id)
    if not entry:
        raise HTTPException(404, '导出文件不存在')
    path = EXPORT_DIR / f'{file_id}.xlsx'
    if not path.exists():
        raise HTTPException(404, '导出文件已清理')
    from fastapi.responses import FileResponse
    return FileResponse(path, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', filename=entry['filename'])


@app.get('/skills')
def list_skills():
    """技能库清单（社媒深挖能力包 M6）：读 .pi/skills/*/SKILL.md frontmatter，只读。
    与 agent 侧 load_skill 同源（allowlist 目录），前端 SkillsPanel 展示用。"""
    import re as _re2
    skills_dir = Path(__file__).parent.parent / '.pi' / 'skills'
    out = []
    try:
        for d in sorted(skills_dir.iterdir()):
            if not d.is_dir():
                continue
            md = d / 'SKILL.md'
            if not md.exists():
                continue
            try:
                text = md.read_text(encoding='utf-8')
            except Exception:
                continue
            fm = text.split('---')[1] if text.startswith('---') else ''
            def _fm(k):
                m = _re2.search(rf'^\s*{k}:\s*(.+)$', fm, _re2.M)
                return m.group(1).strip().strip('\'"') if m else ''
            out.append({
                'id': d.name,
                'name': _fm('name') or d.name,
                'summary': _fm('summary'),
                'description': _fm('description'),
                'version': _fm('version'),
                'files': [f.name for f in d.rglob('*') if f.is_file() and f.name != 'SKILL.md'],
            })
    except FileNotFoundError:
        pass
    return {'skills': out, 'hint': 'agent 侧经 load_skill(name) 按需加载全文（渐进披露）'}


@app.get('/tikhub/status')
async def tikhub_status():
    """TikHub 余额/用量探针（10min 缓存；无 key → configured:false 不报错）"""
    if not _TIKHUB_KEY_PRISM:
        return {'configured': False}
    now = _time.time()
    if _tikhub_status_cache['data'] and now - _tikhub_status_cache['ts'] < 600:
        return _tikhub_status_cache['data']
    headers = {'Authorization': f'Bearer {_TIKHUB_KEY_PRISM}'}
    out = {'configured': True, 'fetched_at': _time.strftime('%Y-%m-%d %H:%M:%S')}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r1 = await client.get(f'{_TIKHUB_BASE}/api/v1/tikhub/user/get_user_info', headers=headers)
            j1 = r1.json() if r1.status_code == 200 else {}
            # api_key_data 在响应顶层（非 data 下）——2026-10-12 实测
            ak = j1.get('api_key_data') or (j1.get('data') or {}).get('api_key_data') or {}
            out['key_name'] = ak.get('api_key_name')
            out['scopes_count'] = len(ak.get('api_key_scopes') or [])
            out['http_info'] = r1.status_code
            # 线B：非 200（如 429 限流）显式标异常——否则前端状态灯在限流时仍显绿 ✓（盲区）
            if r1.status_code != 200:
                out['error'] = f'HTTP {r1.status_code}（限流或上游异常）'
            # 日用量（2026-10-12 实测形态：usage 美元/total_request_per_day）——黄灯盯日消耗
            # （TikHub 无公开余额 API；防御式捞 balance 键保留，捞到算赚到）
            for cand in (j1, j1.get('data') if isinstance(j1.get('data'), dict) else {}):
                for k, v in cand.items():
                    if any(t in k.lower() for t in ('balance', 'quota', 'remaining', 'points')) and isinstance(v, (int, float)):
                        out.setdefault(k, v)
            r2 = await client.get(f'{_TIKHUB_BASE}/api/v1/tikhub/user/get_user_daily_usage', headers=headers)
            j2 = r2.json() if r2.status_code == 200 else {}
            du = j2.get('data') or {}
            if isinstance(du, dict) and 'usage' in du:
                out['daily_usage'] = {
                    'date': du.get('date'), 'spend_usd': du.get('usage'),
                    'requests': du.get('total_request_per_day'),
                }
            else:
                # 审查 P2-6：日用量拉取失败不静默——key 正常但用量未知时前端要可见
                out['daily_usage_error'] = f'HTTP {r2.status_code}' if r2.status_code != 200 else '响应缺 usage 字段'
    except Exception as e:
        out['error'] = f'get_user_info 失败：{e}'
    # P2 修复：error 结果不进缓存（网络抖动不该让"异常"红灯钉 10 分钟）
    if 'error' not in out:
        _tikhub_status_cache.update(ts=now, data=out)
    return out

# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------
@app.get('/health')
def health():
    conn = _open_live()
    try:
        n = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        return {'status': 'ok', 'live_db_tables': n, 'db': AUTOHOME_DB}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# POST /verify/claim · 出口闸行ID查库（M1 服务端真值校验）
# 背景：pi.exe(Bun 运行时) 内 better-sqlite3 原生模块触发 NAPI FATAL panic（2026-10-07
# 探针确定性复现），extension 进程内查库不可行 → 行ID存在性校验移到本端点（Python sqlite3
# 实时读 Prism 主库，与 completion.ts checkRefExists 同口径）
# 2026-10-11 出口闸舆情源登记：新增 sentiment_* 行 ID 分支（直读舆情库只读），
# 治"带数字舆情结论必被拒→必触发保底重试"的结构性缺口（风云T7 实案）。
# ---------------------------------------------------------------------------
SENTIMENT_DB = os.environ.get('PRISM_SENTIMENT_DB',
    str(Path(__file__).parent.parent / 'prism-sentiment' / 'data' / 'vehicle_sentiment.db'))
_SENTIMENT_TABLES = ('sentiment_overview', 'sentiment_trend', 'sentiment_dimension',
                     'sentiment_posts', 'sentiment_competitive', 'sentiment_events',
                     'sentiment_defects', 'sentiment_board')


def _is_uuidish(s: str) -> bool:
    """uuid 形态粗判（8-4-4-4-12 连字符）。只用于区分帖/事件 id 与车系名两种引用形态。"""
    return len(s) == 36 and s.count('-') == 4


def _sent_vehicle_exists(conn, name: str) -> bool:
    """舆情车存在性：与 extension resolveVehicleId 同语义（精确去空格 → 包含）。
    与 /identity/resolve 的 P2-7 同款 LIKE 转义。"""
    nm = name.replace(' ', '')
    if not nm:
        return False
    if conn.execute("SELECT 1 FROM vehicles WHERE REPLACE(name,' ','')=? LIMIT 1", (nm,)).fetchone():
        return True
    esc = nm.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return conn.execute(
        "SELECT 1 FROM vehicles WHERE name LIKE ? ESCAPE '\\' LIMIT 1", (f'%{esc}%',)
    ).fetchone() is not None


def _check_sentiment_ref(conn, table: str, parts: list) -> bool:
    """sentiment_* 行 ID 校验。设计 D2/G2：
    - posts/events 参数为 uuid → 精确查行；为车系名 → 车存在（工具参数本身就是 vehicle_name）
    - dimension：车存在 + 该车 analyzed_posts.dim_sentiment 含该维度（维度名可含'/'，用 join 还原）
    - overview/trend/competitive/board：车存在（board 是模型自造格式的宽容分支）"""
    if not parts or not parts[0]:
        return False
    if table == 'sentiment_posts' and _is_uuidish(parts[0]):
        return conn.execute('SELECT 1 FROM raw_posts WHERE id=? LIMIT 1', (parts[0],)).fetchone() is not None
    if table == 'sentiment_events' and _is_uuidish(parts[0]):
        return conn.execute('SELECT 1 FROM event_groups WHERE id=? LIMIT 1', (parts[0],)).fetchone() is not None
    if table == 'sentiment_dimension' and len(parts) >= 2:
        dim = '/'.join(parts[1:])
        dim_esc = dim.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        return _sent_vehicle_exists(conn, parts[0]) and conn.execute(
            "SELECT 1 FROM analyzed_posts ap JOIN vehicles v ON ap.vehicle_id=v.id "
            "WHERE REPLACE(v.name,' ','')=? AND ap.dim_sentiment LIKE ? ESCAPE '\\' LIMIT 1",
            (parts[0].replace(' ', ''), f'%"{dim_esc}"%'),
        ).fetchone() is not None
    return _sent_vehicle_exists(conn, parts[0])


@app.post('/verify/claim')
async def verify_claim(req: dict):
    import re as _re
    supported_by = req.get('supported_by') or []
    failures = []
    # G3 条件开连接：按引用族分组，无该族引用不开（无谓双连接开销）
    refs = [r for r in supported_by if isinstance(r, str)]
    _split = [r.split(':', 1) for r in refs if ':' in r]
    has_sent = any(t in _SENTIMENT_TABLES for t, _ in _split)
    has_core = any(t not in _SENTIMENT_TABLES for t, _ in _split)
    conn = _open_live() if has_core else None
    sent_conn = None
    sent_unreachable = False
    if has_sent:
        try:
            sent_conn = sqlite3.connect(f'file:{SENTIMENT_DB}?mode=ro', uri=True)
        except sqlite3.Error:
            sent_unreachable = True  # fail-closed：库不可达 → sentiment_* 引用全拒，三维度不受影响
    try:
        for ref in supported_by:
            if not isinstance(ref, str):
                failures.append(f'supported_by "{ref}" 格式错误（应为 table:key/value/...）')
                continue
            m = _re.match(r'^([A-Za-z0-9_]+):(.+)$', ref)  # 对齐 JS \w（不含中文）
            if not m:
                failures.append(f'supported_by "{ref}" 格式错误（应为 table:key/value/...）')
                continue
            table, rest = m.group(1), m.group(2)
            parts = rest.split('/')
            if table in _SENTIMENT_TABLES:
                if sent_unreachable or sent_conn is None:
                    failures.append(f'supported_by "{ref}" 舆情库不可达（fail-closed，稍后重试）')
                    continue
                try:
                    ok = _check_sentiment_ref(sent_conn, table, parts)
                except (ValueError, sqlite3.Error):
                    ok = False
            else:
                ok = False
                try:
                    if table in ('review_tags', 'mv_reviews_dim'):
                        if len(parts) >= 2:
                            ok = conn.execute(
                                'SELECT 1 FROM review_tags WHERE CAST(model_id AS TEXT)=? AND tag_category=? LIMIT 1',
                                (str(parts[0]), parts[1]),
                            ).fetchone() is not None
                    elif table in ('sales_trim', 'mv_sales_monthly'):
                        if len(parts) >= 2:
                            ok = conn.execute(
                                'SELECT 1 FROM sales_trim WHERE series=? AND year=? LIMIT 1',
                                (parts[0], int(parts[1])),
                            ).fetchone() is not None
                    elif table in ('config_snapshots', 'mv_config_spec'):
                        if len(parts) >= 1:
                            ok = conn.execute(
                                'SELECT 1 FROM config_snapshots WHERE series_id=? LIMIT 1',
                                (int(parts[0]),),
                            ).fetchone() is not None
                    elif table == 'config_diff':
                        # 配置赋值口径改造 M3：compare_configs_valued 配对引用。
                        # 格式 config_diff:midA/specA/midB/specB（4 段全数字，沿用 table:part/part 语法）；
                        # 只查两侧 series_id 在 config_snapshots（spec 段在 categories 内非独立行，不单独查）。
                        # 主库不可达时走同款 try/except → ok=False：仅拒 config_diff，三维度不受影响。
                        if len(parts) == 4 and all(p.isdigit() for p in parts):
                            ok = all(
                                conn.execute(
                                    'SELECT 1 FROM config_snapshots WHERE series_id=? LIMIT 1',
                                    (int(p),),
                                ).fetchone() is not None
                                for p in (parts[0], parts[2])
                            )
                except (ValueError, OverflowError, sqlite3.Error):
                    # OverflowError：超大数字段 int 绑定 SQLite 溢出（审查 P1-3）
                    ok = False
            if not ok:
                failures.append(f'supported_by "{ref}" 库中无对应数据')
    finally:
        if conn:
            conn.close()
        if sent_conn:
            sent_conn.close()
    return {'failures': failures}


# ---------------------------------------------------------------------------
# /identity/resolve · T-2.6 身份解析 + 覆盖率守卫（红线#7）
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# T-C1：被拒输入日志（series_alias 决策数据后路，2026-10-11 拍板）
# D4：只记输入词 + 拒绝理由，不记 user_id（端点本无 user 参数；alias 决策只需输入词分布）
# best-effort：写失败静默，绝不影响端点返回；目录已存在不必建
# ---------------------------------------------------------------------------
_IDENTITY_REJECTED_LOG = os.path.join(str(Path(__file__).parent.parent), 'logs', 'identity-rejected.log')

def _log_identity_rejected(series_key: str, reason: str) -> None:
    try:
        from datetime import datetime
        line = json.dumps({
            'ts': datetime.now().astimezone().isoformat(timespec='seconds'),
            'series_key': series_key,
            'reason': reason,
        }, ensure_ascii=False)
        with open(_IDENTITY_REJECTED_LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass  # 日志是 best-effort，失败静默


@app.get('/identity/resolve')
def identity_resolve(series_key: str):
    import sqlite3 as _s
    conn = _s.connect(f'file:{AUTOHOME_DB}?mode=ro', uri=True)
    conn.row_factory = _s.Row
    try:
        # 1. series_alias 查 series_key（精确 raw_name + LIKE）
        # P2-7 修复：LIKE 转义 %/_/\ 防通配符误匹配
        # 2026-10-07 环境适配：上游 autohome.db 重建后 series_alias 表已不存在（schema 变更）
        # → 降级路径：跳过 alias 步骤，直接以输入为 sk 走 series_summaries 归一化匹配
        #   （series_name 本身就是库源权威名，红线#6 不破；歧义检测能力随 alias 表缺失而降级）
        escaped = series_key.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        aliases = []
        alias_table_missing = False
        try:
            for r in conn.execute(
                "SELECT DISTINCT series_key FROM series_alias WHERE raw_name = ? OR raw_name LIKE ? ESCAPE '\\'",
                (series_key, f'%{escaped}%')
            ):
                aliases.append(r['series_key'])
        except sqlite3.OperationalError:
            alias_table_missing = True

        if not aliases and not alias_table_missing:
            # alias 表在但未命中 → fail-closed 提示
            _log_identity_rejected(series_key, 'alias 未命中，对象身份未确认')
            return {
                'series_key': series_key, 'series_id': None, 'canonical_name': None,
                'ambiguous': False, 'needs_online_verify': True,
                'coverage': {}, 'warnings': ['alias 未命中，对象身份未确认'],
                'candidates': []
            }

        # 环境适配降级（2026-10-07，alias 表缺失）：精确名命中才放行——
        # 简称/子串匹配不给过（红线#7 fail-closed：降级模式下宁拒不猜，如 "7X" 不猜成极氪7X）
        if alias_table_missing and not aliases:
            exact = conn.execute(
                "SELECT series_id, series_name FROM series_summaries WHERE series_name = ? OR REPLACE(series_name,' ','') = ?",
                (series_key, series_key.replace(' ', ''))
            ).fetchone()
            if not exact:
                _log_identity_rejected(series_key, 'alias 表缺失（降级模式）：对象身份未确认——请提供完整车系名（如 银河E5）')
                return {
                    'series_key': series_key, 'series_id': None, 'canonical_name': None,
                    'ambiguous': False, 'needs_online_verify': True,
                    'coverage': {}, 'warnings': ['alias 表缺失（降级模式）：对象身份未确认——请提供完整车系名（如 银河E5）'],
                    'candidates': []
                }

        # 去空格去重（"比亚迪 海豚"和"比亚迪海豚"是同一车系两种写法，非真歧义）
        # 环境适配降级：alias 表缺失时 aliases 为空 → sk 直接取输入（走下方 series_summaries 匹配）
        aliases_dedup = list({a.replace(' ', '') for a in aliases}) if aliases else [series_key.replace(' ', '')]
        if len(aliases_dedup) > 1:
            # 真歧义 → 走 ask-user 澄清
            _log_identity_rejected(series_key, f'输入"{series_key}"歧义，命中 {len(aliases_dedup)} 个候选')
            return {
                'series_key': series_key, 'series_id': None, 'canonical_name': None,
                'ambiguous': True, 'needs_online_verify': False,
                'coverage': {}, 'warnings': [f'输入"{series_key}"歧义，命中 {len(aliases_dedup)} 个候选'],
                'candidates': sorted(aliases_dedup)
            }

        sk = aliases_dedup[0]  # 去空格后的 series_key

        # 2. series_summaries 查 series_id（归一化：sk 去空格后含 series_name 子串，或反过来）
        # 2026-10-26 修复（红线#7）：原 LIMIT 1 无排序——"MG4X" 会先命中子串系列 "MG4"，
        # 导致用户问 "MG 4X" 被解析成 MG4。改为优先级排序：精确名 > 去空格精确 > 去空格包含 > 反向包含。
        series_id = None
        canonical = sk
        row = conn.execute(
            """SELECT series_id, series_name,
                      CASE
                        WHEN series_name = ? THEN 0
                        WHEN REPLACE(series_name,' ','') = ? THEN 1
                        WHEN REPLACE(series_name,' ','') LIKE ? THEN 2
                        ELSE 3
                      END AS pri
                 FROM series_summaries
                WHERE series_name = ?
                   OR REPLACE(series_name,' ','') = ?
                   OR REPLACE(series_name,' ','') LIKE ?
                   OR ? LIKE '%' || REPLACE(series_name,' ','') || '%'
                ORDER BY pri ASC, LENGTH(REPLACE(series_name,' ','')) DESC
                LIMIT 1""",
            (sk, sk, f'%{sk}%', sk, sk, f'%{sk}%', sk)
        ).fetchone()
        if row:
            series_id = row['series_id']
            canonical = row['series_name'] or sk

        # 3. 覆盖率守卫（归一化：REPLACE(series,' ','') LIKE pattern）
        coverage = {}
        pattern, _ = normalize_series_for_sales(sk, conn)
        try:
            sales_rows = conn.execute(
                "SELECT COUNT(*) FROM sales_trim WHERE REPLACE(series,' ','') LIKE ?", (pattern,)
            ).fetchone()[0]
            coverage['sales_trim'] = {'hit': sales_rows > 0, 'rows': sales_rows}
        except Exception as e:
            coverage['sales_trim'] = {'hit': False, 'rows': 0}

        if series_id:
            try:
                review_count = conn.execute(
                    "SELECT COUNT(*) FROM owner_reviews WHERE model_id = ?", (series_id,)
                ).fetchone()[0]
                coverage['owner_reviews'] = {'hit': review_count > 0, 'count': review_count}
            except Exception:
                coverage['owner_reviews'] = {'hit': False, 'count': 0}
            try:
                config_count = conn.execute(
                    "SELECT COUNT(*) FROM config_snapshots WHERE series_id = ?", (series_id,)
                ).fetchone()[0]
                coverage['config_snapshots'] = {'hit': config_count > 0}
            except Exception:
                coverage['config_snapshots'] = {'hit': False}
        else:
            coverage['owner_reviews'] = {'hit': False, 'count': 0}
            coverage['config_snapshots'] = {'hit': False}

        coverage['series_summaries'] = {'hit': series_id is not None}

        # needs_online_verify：alias 命中但数据全空 → 需联网核验
        all_empty = all(not v.get('hit') for v in coverage.values())
        needs_verify = all_empty or (series_id is None)

        warnings = []
        if not coverage['sales_trim']['hit']: warnings.append('sales_trim 无该车系销量数据')
        if coverage['owner_reviews'].get('count', 0) == 0: warnings.append('owner_reviews 口碑数据缺失')
        if not coverage['config_snapshots']['hit']: warnings.append('config_snapshots 配置快照缺失')
        if series_id is None: warnings.append('series_summaries 不收录（非主流车系）')

        return {
            'series_key': sk, 'series_id': series_id, 'canonical_name': canonical,
            'ambiguous': False, 'needs_online_verify': needs_verify,
            'coverage': coverage, 'warnings': warnings, 'candidates': []
        }
    finally:
        conn.close()


if __name__ == '__main__':
    import uvicorn
    # 容器内需绑 0.0.0.0 才能被同网络访问；默认仍 127.0.0.1，本机启动行为不变
    uvicorn.run(app, host=os.environ.get('PRISM_API_HOST', '127.0.0.1'), port=8002)
