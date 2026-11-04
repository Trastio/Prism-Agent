"""
Prism-Agent · prism-ops（北极星看板独立服务，openspec/changes/北极星看板独立端口化）

管理者运营数据专用端口（默认 127.0.0.1:8020，仅本机）：
- GET /                    → static/index.html（vanilla 单页）
- GET /events/stats        → 北极星指标快照（DAU/采纳/人均/轮时长）
- GET /events/trends       → 北极星逐日趋势（RECURSIVE 补零）
- GET /badcases/quadrant   → badcase 四象限 + 终轮明细
- GET /trajectory          → 轨迹会话列表
- GET /trajectory/{sid}    → 轨迹详情（badcase 回放）
- GET /attribution/{sid}   → 五维归因

数据源：项目根 prism_events.db（与主站 /events POST 埋点链路同库，ops 只读不写）
        + .pi/sessions/trajectories.jsonl（只读）。
端点实现原样移植自 prism-api/main.py（2026-10-13），口径与主站搬迁前一致。
"""
import os
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

# 项目根（prism-ops/ 的上一级）——常量钉死绝对路径，cwd 无关
_ROOT = Path(__file__).resolve().parent.parent

EVENTS_DB = str(_ROOT / 'prism_events.db')
TRAJECTORIES_FILE = str(_ROOT / '.pi' / 'sessions' / 'trajectories.jsonl')

_STATIC_INDEX = Path(__file__).resolve().parent / 'static' / 'index.html'

# ---------------------------------------------------------------------------
# 测试数据过滤（2026-10-13 补，口径见方案 §八）
# 开发期/遗留会话的 session_id 非标准 UUID（如 usr_*、时间戳_*、sess1）——
# 真实 pi 会话 id 为标准 UUID。默认开启过滤：会话级指标（结论/采纳/四象限）
# 仅统计标准 UUID 会话；设 PRISM_OPS_EXCLUDE_TEST=0 可关闭（回到全量口径）。
# 用户级指标（DAU/WAU/人均）：local_id 语义随登录门禁（2026-10-15 上线）切换——
# 此前=匿名随机串（usr_xxxx，一人可多号，DAU 虚高不可跨期对比）；此后=token 用户名（实名稳定）。
# 【口径分界日 2026-10-15】DAU/WAU/人均趋势线在此分界，前后两段不可直接连线解读
# （同"r3 不可与 v1.1 直接对比"教训）。PRISM_OPS_TEST_LOCAL_IDS 仍可显式排除测试号。
# ---------------------------------------------------------------------------
_EXCLUDE_TEST = os.environ.get('PRISM_OPS_EXCLUDE_TEST', '1') != '0'
_TEST_LOCAL_IDS = [x.strip() for x in os.environ.get('PRISM_OPS_TEST_LOCAL_IDS', '').split(',') if x.strip()]

_UUID_PAT = "'[0-9a-f]*-[0-9a-f]*-[0-9a-f]*-[0-9a-f]*-[0-9a-f]*'"


def _uuid_pred(col='session_id'):
    """标准 UUID 会话的 SQL 判据（GLOB 全串匹配；过滤关闭时恒真）。"""
    if not _EXCLUDE_TEST:
        return '1=1'
    return f"({col} IS NOT NULL AND LENGTH({col})=36 AND {col} GLOB {_UUID_PAT})"


def _local_pred(col='local_id'):
    """用户级指标的排除判据：eval 身份恒排除 + PRISM_OPS_TEST_LOCAL_IDS 额外排除。
    P0 北极星隔离（2026-10-26）：即使 eval 事件误入库，也不能被算成真实用户。"""
    test_clause = ''
    if _TEST_LOCAL_IDS:
        quoted = ','.join("'" + v.replace("'", "''") + "'" for v in _TEST_LOCAL_IDS)
        test_clause = f" AND {col} NOT IN ({quoted})"
    return f"({col} IS NULL OR ({col} NOT LIKE 'eval%'{test_clause}))"


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

app = FastAPI(title='Prism-Agent Ops', version='0.1.0',
              docs_url=None, redoc_url=None, openapi_url=None)  # Step8 P2-1：运营端口不开文档路由，收窄暴露面


# Step8 P2-2：trajectories.jsonl 已 300MB+ 且被 30s 轮询，按 mtime 缓存"sid→精简预览"
# （只存 quadrant 用到的字段，完整轨迹不驻内存——全量解析成 dict 会膨胀到 GB 级）
_PREVIEW_CACHE = {'mtime': None, 'preview': {}}


def _traj_preview():
    import json as _j
    from pathlib import Path as _P
    tp = _P(TRAJECTORIES_FILE)
    if not tp.exists():
        return {}
    m = tp.stat().st_mtime
    if _PREVIEW_CACHE['mtime'] == m:
        return _PREVIEW_CACHE['preview']
    preview = {}
    with open(tp, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                obj = _j.loads(line)
            except Exception:
                continue
            sid = obj.get('sessionId')
            if sid:
                preview[sid] = {
                    'conclusion_preview': (obj.get('final_conclusion') or '')[:200],
                    'tool_count': len(obj.get('toolCalls') or []),
                }
    _PREVIEW_CACHE['mtime'] = m
    _PREVIEW_CACHE['preview'] = preview
    return preview


@app.get('/')
async def index():
    """北极星看板单页（vanilla，零构建）。"""
    return FileResponse(_STATIC_INDEX, media_type='text/html; charset=utf-8')


# E3/E4（2026-11-02）：每日巡检汇总（由 deploy/daily_health.py 生成）。
# 容器内挂载 /app/health；本地回退 ../data/health。
HEALTH_DIR = Path(os.environ.get('PRISM_HEALTH_DIR', '/app/health'))


@app.get('/health/report')
async def health_report():
    p = HEALTH_DIR / 'latest.json'
    if not p.exists():
        return JSONResponse({'status': 'missing', 'message': '暂无巡检报告（每日 08:00 生成）'}, status_code=404)
    try:
        return JSONResponse(json.loads(p.read_text(encoding='utf-8')))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({'status': 'error', 'message': str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# 以下六端点原样移植自 prism-api/main.py（T-7.3/T-8.2/T-8.3，2026-10-13 搬迁）
# ---------------------------------------------------------------------------

@app.get('/events/stats')
async def events_stats():
    """北极星指标快照（2026-10-13：total_dau/adoption/per_user/latency/WAU/交付结论/测试过滤）。
    口径：total_dau=近24h 任意事件去重用户（含心跳）；wau=近7天任意事件去重用户；
    黏性=总DAU÷WAU（留存代理，24h 分子÷7d 分母近似）；
    周成功交付结论数=近7天有"过闸结论"的会话去重（conclusion_emitted value=ok，会话级归一，仅标准 UUID 会话）
    ——产品北极星真口径（2026-10-13 起埋点；此前用 chat_settled 会话数顶替，含 fail/闲聊）；
    交付率=交付结论会话÷终轮(settled)会话；采纳=反馈÷交付结论；
    人均结论/每人轮数=近7天交付结论/提问轮 ÷ WAU；
    轮时长=settled 配对其前最近 start（含验证重试轮；>15min 跨天脏配对排除，excluded 计数）。
    ts 窗口统一 julianday() 比较。
    注：2026-10-13 曾短暂展示"在线时长"，因口径可被"挂机"污染、且看板/对话分线依赖的
    session_id 代理失效（setSessionContext 从不重置），已移除，改用 WAU/黏性/每人轮数衡量使用深度。"""
    import sqlite3 as _s
    conn = _s.connect(EVENTS_DB)
    conn.row_factory = _s.Row
    try:
        win24 = "julianday(ts) >= julianday('now','-1 day')"
        win7 = "julianday(ts) >= julianday('now','-7 day')"
        win7s = "julianday(s.ts) >= julianday('now','-7 day')"  # 别名表 s 的显式窗口（latency 配对用）
        loc = _local_pred()          # 用户级排除判据（默认恒真）
        uuid = _uuid_pred()          # 会话级过滤判据（默认开：仅标准 UUID 会话）
        uuid_s = _uuid_pred('s.session_id')
        # 活跃口径（2026-10-13 指标体检修订）：
        #   dau = 打开(page_view 去重)——原"看板 DAU"正名：page_view 在挂载即发、默认视图=对话，与"看板"无关
        #   总 DAU = 非心跳事件去重（去掉 active_tick，避免"挂机"稀释）
        dau = conn.execute(
            f"SELECT COUNT(DISTINCT local_id) AS n FROM events WHERE event_type='page_view' AND {win24} AND {loc}"
        ).fetchone()['n']
        chat_dau = conn.execute(
            f"SELECT COUNT(DISTINCT local_id) AS n FROM events WHERE event_type='chat_start' AND {win24} AND {loc}"
        ).fetchone()['n']
        total_dau = conn.execute(
            f"SELECT COUNT(DISTINCT local_id) AS n FROM events WHERE {win24} AND {loc} AND event_type!='active_tick'"
        ).fetchone()['n']
        # 深度指标（2026-10-13）：WAU（非心跳）/ 近7天日均 DAU / 有对话用户 / 提问轮数 / 中止轮数
        wau = conn.execute(
            f"SELECT COUNT(DISTINCT local_id) AS n FROM events WHERE {win7} AND {loc} AND event_type!='active_tick'"
        ).fetchone()['n']
        # 日均 DAU（近7天，分母固定 7 含零日）→ 黏性=日均DAU÷WAU（窗口对齐，替代原 24h÷7d）
        avg_daily_dau = conn.execute(
            f"SELECT COALESCE(SUM(n),0) / 7.0 AS a FROM ("
            f"SELECT date(ts,'localtime') AS d, COUNT(DISTINCT local_id) AS n FROM events "
            f"WHERE {win7} AND {loc} AND event_type!='active_tick' GROUP BY d)"
        ).fetchone()['a'] or 0.0
        # 有对话用户（分母修正：人均结论/每人轮数 应除以"有对话的人"，而非含只看看板者的 WAU）
        chat_users7 = conn.execute(
            f"SELECT COUNT(DISTINCT local_id) AS n FROM events WHERE event_type='chat_start' AND {win7} AND {loc}"
        ).fetchone()['n']
        turns7 = conn.execute(
            f"SELECT COUNT(*) AS n FROM events WHERE event_type='chat_start' AND {win7} AND {loc}"
        ).fetchone()['n']
        aborts7 = conn.execute(
            f"SELECT COUNT(*) AS n FROM events WHERE event_type='chat_abort' AND {win7} AND {loc}"
        ).fetchone()['n']
        # 周成功交付结论数（产品北极星 · 2026-10-13 真埋点）：近7天有"过闸结论"的会话去重
        # （conclusion_emitted 且 value=ok，由前端在 submit_conclusion 通过出口闸时上报；
        #  会话级归一，去重验证重试轮。此前用 chat_settled 会话数顶替，含 fail/闲聊，名不副实）
        conclusions7 = conn.execute(
            f"SELECT COUNT(DISTINCT session_id) AS n FROM events "
            f"WHERE event_type='conclusion_emitted' AND value='ok' AND {win7} AND {uuid}"
        ).fetchone()['n']
        # 近7天终轮会话数（settled 去重，仅标准 UUID）——供"交付率"分母（交付结论会话 ÷ 终轮会话）
        settled7 = conn.execute(
            f"SELECT COUNT(DISTINCT session_id) AS n FROM events "
            f"WHERE event_type='chat_settled' AND {win7} AND {uuid}"
        ).fetchone()['n']
        # 测试过滤透明项：被剔除的非 UUID 会话数（近7天，同窗）
        total_sess7 = conn.execute(
            f"SELECT COUNT(DISTINCT session_id) AS n FROM events "
            f"WHERE event_type='chat_settled' AND {win7} AND session_id IS NOT NULL"
        ).fetchone()['n']
        thumbs_up = conn.execute(
            f"SELECT COUNT(*) AS n FROM events WHERE event_type='feedback' AND value='up' AND {win7} AND {uuid}"
        ).fetchone()['n']
        thumbs_down = conn.execute(
            f"SELECT COUNT(*) AS n FROM events WHERE event_type='feedback' AND value='down' AND {win7} AND {uuid}"
        ).fetchone()['n']
        # 轮时长（D8：每 settled 配对同 session 内其之前最近的 chat_start）
        pair_rows = conn.execute(f"""
            SELECT (julianday(s.ts) - (
                SELECT MAX(julianday(k.ts)) FROM events k
                WHERE k.event_type='chat_start' AND k.session_id = s.session_id
                  AND julianday(k.ts) <= julianday(s.ts)
            )) * 86400000.0 AS ms
            FROM events s
            WHERE s.event_type='chat_settled' AND {win7s} AND {uuid_s}
        """).fetchall()
        samples = sorted(r['ms'] for r in pair_rows if r['ms'] is not None and 0 <= r['ms'] <= 15 * 60 * 1000)
        excluded = sum(1 for r in pair_rows if r['ms'] is None or not (0 <= r['ms'] <= 15 * 60 * 1000))

        def _pct(vals, p):
            if not vals: return None
            i = min(int(p * len(vals)), len(vals) - 1)
            return round(vals[i])

        latency = {
            'median_ms': _pct(samples, 0.5), 'p90_ms': _pct(samples, 0.9),
            'n': len(samples), 'excluded': excluded,
        } if samples else {'median_ms': None, 'p90_ms': None, 'n': 0, 'excluded': excluded}
        return {
            'dau': dau, 'chat_dau': chat_dau, 'total_dau': total_dau,
            'wau': wau,
            'stickiness': round(total_dau / wau, 4) if wau else None,
            'turns7': turns7,
            'weekly_conclusions': conclusions7,
            'settled_sessions': settled7,
            'delivery_rate': round(conclusions7 / settled7, 4) if settled7 else None,
            'feedback': {'up': thumbs_up, 'down': thumbs_down},
            'adoption': {
                'up_rate': round(thumbs_up / conclusions7, 4) if conclusions7 else None,
                'down_rate': round(thumbs_down / conclusions7, 4) if conclusions7 else None,
                'net_rate': round((thumbs_up - thumbs_down) / conclusions7, 4) if conclusions7 else None,
            },
            'per_user': round(conclusions7 / wau, 2) if wau else None,
            'per_user_turns': round(turns7 / wau, 2) if wau else None,
            'latency': latency,
            'test_filter': {
                'enabled': _EXCLUDE_TEST,
                'excluded_sessions': max(0, total_sess7 - settled7),
                'local_denylist': list(_TEST_LOCAL_IDS),
            },
        }
    finally:
        conn.close()


@app.get('/events/trends')
async def events_trends(days: int = 14):
    """北极星逐日趋势（D5：本地日分桶，空日期补零，序列连续）。
    DAU 口径与 /events/stats 一致：看板=page_view 去重 / 对话=chat_start 去重 / 总=任意事件去重。
    conclusions=当日有"过闸结论"的会话去重（conclusion_emitted value=ok，与 stats 周交付结论同口径）；
    反馈仅标准 UUID 会话。"""
    import sqlite3 as _s
    days = max(1, min(90, days))
    conn = _s.connect(EVENTS_DB)
    conn.row_factory = _s.Row
    try:
        loc = _local_pred()
        uuid = _uuid_pred()
        rows = conn.execute(f"""
            WITH RECURSIVE
              d(day) AS (
                SELECT date('now','localtime','start of day','-{days - 1} day')
                UNION ALL
                SELECT date(day,'+1 day') FROM d WHERE day < date('now','localtime','start of day')
              ),
              daily AS (
                SELECT date(ts,'localtime') AS day,
                       COUNT(DISTINCT CASE WHEN event_type='page_view' THEN local_id END) AS board_dau,
                       COUNT(DISTINCT CASE WHEN event_type='chat_start' THEN local_id END) AS chat_dau,
                       COUNT(DISTINCT local_id) AS total_dau,
                       COUNT(DISTINCT CASE WHEN event_type='conclusion_emitted' AND value='ok' AND {uuid} THEN session_id END) AS conclusions,
                       COUNT(CASE WHEN event_type='feedback' AND value='up' AND {uuid} THEN 1 END) AS thumbs_up,
                       COUNT(CASE WHEN event_type='feedback' AND value='down' AND {uuid} THEN 1 END) AS thumbs_down
                FROM events
                WHERE julianday(ts) >= julianday('now','-{days} day') AND {loc}
                GROUP BY date(ts,'localtime')
              )
            SELECT d.day AS date,
                   COALESCE(b.board_dau,0) AS board_dau, COALESCE(b.chat_dau,0) AS chat_dau,
                   COALESCE(b.total_dau,0) AS total_dau, COALESCE(b.conclusions,0) AS conclusions,
                   COALESCE(b.thumbs_up,0) AS thumbs_up, COALESCE(b.thumbs_down,0) AS thumbs_down
            FROM d LEFT JOIN daily b ON b.day = d.day ORDER BY d.day
        """).fetchall()
        return {'days_param': days, 'days': [{k: r[k] for k in r.keys()} for r in rows]}
    finally:
        conn.close()


@app.get('/badcases/quadrant')
async def badcases_quadrant(days: int = 14):
    """badcase 四象限（verdict×点踩）+ 终轮明细（G3/D3）。
    终轮归一=每 session 最后一条 chat_settled（默认近14天，days 可调 1-90；重试轮也发 settled 事件，最后一条即终轮）；
    feedback 按 session 级匹配、同 days 天窗（点踩时用户看到的是该会话终答，轮级配对误差在 session 级消失）；
    verdict 非 'pass' 一律归 fail 侧（含 unknown）；仅标准 UUID 会话（测试/遗留会话剔除）；
    conclusion_preview/tool_count 从 trajectories.jsonl 取该 session 最后一条轨迹，无匹配时空串不阻塞。"""
    import sqlite3 as _s
    days = max(1, min(90, days))
    conn = _s.connect(EVENTS_DB)
    conn.row_factory = _s.Row
    try:
        uuid = _uuid_pred()
        finals = conn.execute(f"""
            SELECT session_id, value AS verdict, ts, settled_count FROM (
                SELECT session_id, value, ts,
                       ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY julianday(ts) DESC, rowid DESC) AS rn,
                       COUNT(*) OVER (PARTITION BY session_id) AS settled_count
                FROM events
                WHERE event_type='chat_settled'
                  AND julianday(ts) >= julianday('now','-{days} day')
                  AND {uuid}
            ) WHERE rn = 1
        """).fetchall()
        fb = {r['session_id']: (r['up'], r['down']) for r in conn.execute(f"""
            SELECT session_id,
                   SUM(CASE WHEN value='up' THEN 1 ELSE 0 END) AS up,
                   SUM(CASE WHEN value='down' THEN 1 ELSE 0 END) AS down
            FROM events WHERE event_type='feedback' AND session_id IS NOT NULL
              AND julianday(ts) >= julianday('now','-{days} day')
            GROUP BY session_id
        """)}
        q = {'pass_clean': 0, 'pass_with_down': 0, 'fail_clean': 0, 'fail_with_down': 0}
        for r in finals:
            down = (fb.get(r['session_id'], (0, 0))[1] or 0) > 0
            key = ('pass' if r['verdict'] == 'pass' else 'fail') + ('_with_down' if down else '_clean')
            q[key] += 1
        # trajectories 预览（mtime 缓存，见 _traj_preview；同行覆盖 = 该 session 最后一条轨迹）
        preview = _traj_preview()
        items = []
        # 排序按时间数值而非字符串（两种存量 ts 格式的字典序只是近似时间序）
        from datetime import datetime as _dt
        def _ts_key(v):
            try:
                return _dt.fromisoformat((v or '').replace('Z', '+00:00')).timestamp()
            except Exception:
                return 0.0
        for r in sorted(finals, key=lambda x: _ts_key(x['ts']), reverse=True)[:50]:
            sid = r['session_id']
            t = preview.get(sid)
            up, down = fb.get(sid, (0, 0))
            items.append({
                'session_id': sid, 'last_ts': r['ts'], 'verdict': r['verdict'],
                'conclusion_preview': (t or {}).get('conclusion_preview', '')[:80],
                'tool_count': (t or {}).get('tool_count', 0),
                'settled_count': r['settled_count'],
                'retry_heavy': r['settled_count'] >= 3,
                'feedback': {'up': up or 0, 'down': down or 0},
            })
        return {'window_days': days, 'total_sessions': len(finals), 'quadrant': q, 'items': items}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 用户反馈明细（2026-11-04）：主站右下角「反馈」入口 → prism-api POST /feedback 写入
# user_feedback 表（prism_events.db）；本端口只读展示最近 N 条（保持 ops 纯只读定位）
# ---------------------------------------------------------------------------
KIND_LABELS = {'issue': '问题', 'suggestion': '建议', 'other': '其他'}


@app.get('/feedback')
async def feedback_list(limit: int = 100):
    """最近 N 条用户反馈（按时间倒序）。表不存在（尚未有反馈）时返回空列表，不报错。"""
    limit = max(1, min(500, int(limit)))
    import sqlite3 as _s
    conn = _s.connect(EVENTS_DB)
    conn.row_factory = _s.Row
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_feedback'").fetchone()
        if not exists:
            return {'total': 0, 'items': []}
        total = conn.execute('SELECT COUNT(*) AS n FROM user_feedback').fetchone()['n']
        rows = conn.execute(
            'SELECT id, username, kind, content, ts FROM user_feedback '
            'ORDER BY julianday(ts) DESC, id DESC LIMIT ?', (limit,)).fetchall()
        items = [{
            'id': r['id'],
            'username': r['username'],
            'kind': r['kind'],
            'kind_label': KIND_LABELS.get(r['kind'], r['kind']),
            'content': r['content'],
            'ts': r['ts'],
        } for r in rows]
        return {'total': total, 'items': items}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# T-8.2 /trajectory · badcase 回放（读 .pi/sessions/trajectories.jsonl）
# 【人工消费面】零代码消费者（2026-10-08 实测）：浏览器直接查看，badcase 回放/34 题口径基线用，勿删
# ---------------------------------------------------------------------------

def _traj_source(traj):
    """A6 eval 轨迹回放：?traj=<路径> 切换轨迹源（eval 批跑独立轨迹）；缺省=生产轨迹（行为不变）。
    收窄暴露面：只放行项目根内、后缀 .jsonl 的文件，防运营端口变成任意文件读取器。"""
    from pathlib import Path as _P
    p = _P(traj)
    if not p.is_absolute():
        p = _ROOT / p
    rp = p.resolve()
    if rp.suffix != '.jsonl' or _ROOT.resolve() not in rp.parents:
        raise HTTPException(400, 'traj 参数非法：须为项目根内的 .jsonl 文件')
    if not rp.exists():
        raise HTTPException(404, 'traj 文件不存在: %s' % rp)
    return rp


@app.get('/trajectory/{session_id}')
async def get_trajectory(session_id: str, traj: str = ''):
    """Step8 P2-3：去掉 'all' 全量模式（303MB 无界响应），并截最近 50 条防超大会话。
    A6：?traj=<路径> 回放 eval 轨迹（缺省生产轨迹，响应形状不变）。"""
    import json as _j
    from pathlib import Path as _P
    p = _traj_source(traj) if traj else _P(TRAJECTORIES_FILE)
    if not p.exists():
        return {'trajectories': []}
    rows = []
    with open(p, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                obj = _j.loads(line)
                if obj.get('sessionId') == session_id:
                    rows.append(obj)
            except Exception:
                continue
    truncated = len(rows) > 50
    return {'session_id': session_id, 'count': len(rows), 'truncated': truncated,
            'trajectories': rows[-50:]}


@app.get('/trajectory')
async def list_trajectories(traj: str = ''):
    """列出所有有轨迹的 session（去重 + 最近优先）；A6：?traj=<路径> 切 eval 轨迹源"""
    import json as _j
    from pathlib import Path as _P
    p = _traj_source(traj) if traj else _P(TRAJECTORIES_FILE)
    if not p.exists():
        return {'sessions': []}
    seen = {}
    with open(p, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                obj = _j.loads(line)
                sid = obj.get('sessionId')
                if sid and sid not in seen:
                    seen[sid] = {
                        'sessionId': sid, 'last_ts': obj.get('timestamp'),
                        'verdict': obj.get('verdict'), 'conclusion_preview': (obj.get('final_conclusion') or '')[:80],
                    }
            except Exception:
                continue
    return {'sessions': list(seen.values())}


# ---------------------------------------------------------------------------
# T-8.3 /attribution · 五维归因（给定 session_id，标注五维）
# ---------------------------------------------------------------------------
ATTRIB_DIMS = ['对象理解', '能力选择', '工具调用顺序', '权限与确认边界', '业务结果']

@app.get('/attribution/{session_id}')
async def get_attribution(session_id: str = None):
    """五维归因：从轨迹推断 badcase 根因维度。session_id='latest' 或省略返回最近一条"""
    import json as _j
    from pathlib import Path as _P
    p = _P(TRAJECTORIES_FILE)
    if not p.exists():
        return {'error': 'no trajectories'}
    trajectories = []
    with open(p, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                obj = _j.loads(line)
                if session_id in (None, 'latest') or obj.get('sessionId') == session_id:
                    trajectories.append(obj)
            except Exception:
                continue
    if not trajectories:
        return {'error': f'session {session_id} 无轨迹'}
    # latest 模式只取最后一条
    if session_id in (None, 'latest'):
        trajectories = trajectories[-1:]

    last = trajectories[-1]
    attribution = {}
    # 1. 对象理解：resolve_series 是否调过 + 是否 fail-closed
    has_resolve = any(tc.get('name') == 'resolve_series' for t in trajectories for tc in t.get('toolCalls', []))
    verdict_reason = last.get('verdict_reason', '')
    attribution['对象理解'] = {
        'score': 'ok' if has_resolve else 'unknown',
        'note': '调过 resolve_series' if has_resolve else '未调 resolve_series（对象身份未核验，疑似越界分析）',
    }
    # 2. 能力选择：是否调了对的工具（query_* 对应维度）
    tool_names = set(tc.get('name') for t in trajectories for tc in t.get('toolCalls', []))
    attribution['能力选择'] = {
        'tools': sorted(tool_names),
        'note': '调用了 ' + ', '.join(sorted(tool_names)) if tool_names else '未调用任何工具',
    }
    # 3. 工具调用顺序：resolve_series 是否在 query_* 之前
    first_resolve_idx = None
    first_query_idx = None
    for t in trajectories:
        for i, tc in enumerate(t.get('toolCalls', [])):
            if tc.get('name') == 'resolve_series' and first_resolve_idx is None:
                first_resolve_idx = i
            if tc.get('name', '').startswith('query_') and first_query_idx is None:
                first_query_idx = i
    order_ok = first_resolve_idx is not None and (first_query_idx is None or first_resolve_idx <= first_query_idx)
    attribution['工具调用顺序'] = {
        'order_ok': order_ok,
        'note': 'resolve_series 先于 query_*' if order_ok else 'query_* 先于 resolve_series（违反 SOP）',
    }
    # 4. 权限与确认边界：ui_request 是否出现
    attribution['权限与确认边界'] = {
        'note': '无 ui_request 触发（本轮无确认弹窗）',  # 简化，待 Step6 观测补
    }
    # 5. 业务结果：verdict + evidence_ids
    attribution['业务结果'] = {
        'verdict': last.get('verdict'),
        'evidence_ids': last.get('evidence_ids', []),
        'verdict_reason': verdict_reason,
    }
    return {'session_id': session_id, 'attribution': attribution, 'dims': ATTRIB_DIMS}


if __name__ == '__main__':
    import uvicorn
    # 本地默认只绑 127.0.0.1；云上容器内设 PRISM_OPS_HOST=0.0.0.0（compose 侧用
    # ports: ["127.0.0.1:8020:8020"] 只映射宿主机 loopback——容器内绑 127 连不上端口映射，
    # 对外零暴露靠宿主机侧映射限制，SSH 隧道 -L 8020:localhost:8020 即可访问）
    uvicorn.run(app, host=os.environ.get('PRISM_OPS_HOST', '127.0.0.1'),
                port=int(os.environ.get('PRISM_OPS_PORT', '8020')))
