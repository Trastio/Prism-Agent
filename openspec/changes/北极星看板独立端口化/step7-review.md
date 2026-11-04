# Step7 隔离审查报告 · 北极星看板独立端口化（2026-10-13）

审查者：Step7 隔离审查子代理（只审不改）。审查对象全部从磁盘直读：

- `prism-ops/ops_server.py`（384 行，全文）
- `prism-ops/static/index.html`（483 行，全文）
- `prism-api/main.py`（1146 行，重点 1-200 区 + 全文 grep）
- `prism-web/src/App.tsx`（152 行全文）、`Sidebar.tsx`（Props 区）、`vite.config.ts`（37 行全文）、src 全树文件清单 + 全 src grep
- `prism.py`（438 行全文）+ `python -c ast.parse` 双文件通过（AST-OK）

结论：**P0=0，P1=0，P2=3，P3（记录性）=3**。七项清单全 PASS（其中第 3 项带 P2 附注）。

---

## 一、逐项清单

### 1. 移植保真（ops_server.py 全文核对）—— PASS

| 设计要点 | 证据（行号） | 判定 |
|---|---|---|
| ① /events/stats：win24/win7/win7s julianday 窗 | ops_server.py:79-81 | PASS |
| ① latency 配对子查询 MAX(julianday(k.ts)) | :107-114（同 session 内 settled 前最近 chat_start） | PASS |
| ① 15min cap + excluded 计数 | :115-116（`0 <= r['ms'] <= 15*60*1000` 过滤；None/越界计入 excluded） | PASS |
| ① adoption 三率 + settled7 空分母保护 | :132-134（`if settled7 else None` ×3） | PASS |
| ① per_user + active7 空分母保护 | :136（`if active7 else None`） | PASS |
| ② /events/trends：RECURSIVE 日 spine | :153-157 | PASS |
| ② 本地日分桶 | :160/:169（`date(ts,'localtime')`，spine 同用 localtime 对齐） | PASS |
| ② days clamp 1-90 | :148（`max(1, min(90, days))`） | PASS |
| ② COALESCE 补零 | :172-174（6 列全 COALESCE） | PASS |
| ③ quadrant：ROW_NUMBER 终轮归一含 rowid 次级键 | :198（`ORDER BY julianday(ts) DESC, rowid DESC`） | PASS |
| ③ feedback 同 14 天窗 session 级匹配 | :206-213（`-14 day` 窗 + GROUP BY session_id） | PASS |
| ③ trajectories preview 同行覆盖（每 sid 最后一条） | :221-232（顺序读，`preview[sid] = obj` 后行覆盖前行） | PASS |
| ③ items 排序用时间数值非字符串 | :235-241（`_dt.fromisoformat(...).timestamp()` 键，解析失败退化 0.0） | PASS |
| ③ retry_heavy≥3 | :250（`settled_count >= 3`） | PASS |
| ④ /trajectory 列表+详情 | :263-281（详情）/ :284-307（列表，去重+首见即最近） | PASS |
| ④ /attribution 五维归因完整 | :313（ATTRIB_DIMS 五维）+ :345-378（对象理解/能力选择/工具调用顺序/权限与确认边界/业务结果 逐维实现） | PASS |

注：本仓库非 git 仓库、无搬迁前快照，"与搬迁前主站逐字节一致"无法 diff 验证；以上是对照设计要点在磁盘代码上的逐点实证，要点全部真实存在。

### 2. 路径与建表 —— PASS

- `EVENTS_DB`：ops_server.py:24-26 `_ROOT = Path(__file__).resolve().parent.parent` → 项目根 `prism_events.db`；与 main.py:76 `Path(__file__).parent.parent / 'prism_events.db'` 解析到同一绝对路径。磁盘实证：`prism_events.db` 存在于项目根（1.18MB，mtime 当日 21:21，仍在被主站写入）。
- `TRAJECTORIES_FILE`：ops_server.py:27 → 项目根 `.pi/sessions/trajectories.jsonl`；磁盘实证存在（317,761,439 字节 ≈303MB）。
- 幂等建表：ops_server.py:36-48 与 main.py:82-94 的 CREATE TABLE IF NOT EXISTS events（同 8 列）+ 3 个同名索引（idx_events_type_ts / idx_events_session / idx_events_local）逐行一致。

### 3. 安全面 —— PASS（附 P2-1）

- 只绑 127.0.0.1：ops_server.py:384 `uvicorn.run(app, host='127.0.0.1', port=...)`；prism.py 以 `sys.executable ops_server.py` 直跑脚本（prism.py:61-63）→ 走 `__main__` 分支，不经 uvicorn CLI 另配 host。
- 路由面：全文仅 7 个 `@app.get`（`/`、`/events/stats`、`/events/trends`、`/badcases/quadrant`、`/trajectory/{session_id}`、`/trajectory`、`/attribution/{session_id}`）= 声明的 6+GET /，无多余自定义路由、无 POST/写路由。**附注**：FastAPI 默认自动暴露 `/docs` `/redoc` `/openapi.json`（构造处 :56 未关），严格口径下路由面比声明多 3 个只读文档路由 → P2-1。
- XSS：index.html 全部 DOM 写入点逐个核过——
  - `innerHTML` 共 6 处写入容器（kpiGrid/dauChart/conclChart/quadGrid/quadTableWrap/drawerBody），无 `insertAdjacentHTML`；
  - 库侧字符串全部过 `esc()`（:253-25257 定义，转义 `& < > " '`）：结论预览 :389、verdict :385/:388/:435、verdict_reason :436、as_of :437、final_conclusion :441、工具名 :432、session id :385/:387、fmtLocal(ts) :386、日期轴 :320/:321/:345/:346、KPI label/value/foot :291-293、错误消息 :446；
  - 属性注入面：`data-sid`/`data-verdict` 均经 esc（引号已转义，无法出属性）；动态拼接进 class 的 `verdictCls`/`d.cls` 为三元/静态常量（'tag-pos'/'tag-neg'），非库侧原串；
  - style 注入面：仅静态内联（`style="margin-top:4px"` :370、`margin-left:6px` :384、`color:var(--neg)` :446），无动态 style 值；
  - 错误横幅/标题用 `textContent`（:366/:471/:408），天然安全。
  - 未发现漏网点。
- 请求侧：抽屉 fetch 用 `encodeURIComponent(sid)`（:412），无路径注入。

### 4. 单页健壮性 —— PASS

- `fetch !r.ok` 抛错：jfetch :246-251。
- 错误横幅：errBanner :461-475（分段收集 stats/trends/quad 失败名，textContent 写入，30s 重试标注）。
- 30s 轮询 + `document.hidden` 跳过：:478 `setInterval(function () { if (!document.hidden) loadAll(); }, REFRESH_MS)`。
- drawerReq 竞态：:403/:411/:413/:445/:450——每次 openDrawer `my = ++drawerReq`，响应回来 `my !== drawerReq` 即丢弃；closeDrawer 也自增使在途回包作废。快速连点 A→B：B 立即改标题+置"加载中"，A 的迟回报被丢弃，只有 B 渲染 → 抽屉内容不会串。
- 行点击绑定不丢：renderQuad 每次 `wrap.innerHTML` 重建后立刻 `querySelectorAll('tr.row-click')` 重挂 listener（:394-399），数据刷新重建 DOM 不丢事件。

### 5. 主站清理完整性 —— PASS

- 埋点链路完整：main.py:76 `EVENTS_DB`、:78-97 `_init_events_db`（含 3 索引）、:120-159 `POST /events`（批量入库+脱敏 sanitize_text）全在。前端写侧配套未动：tracker.ts:10 `ENDPOINT='/events'`（sendBeacon+fetch 兜底），vite.config.ts:29 `/events` 代理保留。
- 残留 grep（main.py 全文，大小写不敏感）：`TRAJECTORIES_FILE|ATTRIB_DIMS|trajectory|attribution|badcases|MetricsView|metrics|quadrant|events/stats|events/trends` → **零匹配**；`北极星` 仅命中 :74 一行注释（描述保留的 /events 写链路数据源，语义准确，非端点残留）。
- 前端：App.tsx:20 `type View = 'kanban' | 'chat'`，import 区无 MetricsView；Sidebar.tsx:13-15 Props 已收窄回 `'kanban' | 'chat'`；src 全树 grep（MetricsView|BadCaseDrawer|quadrant|trajectory|attribution|events/stats|events/trends|metrics，大小写不敏感，含 styles.css）→ 零匹配；文件树实证 `components/` 下无 MetricsView.tsx / BadCaseDrawer.tsx。
- vite.config.ts（:14-35）：无 `/trajectory` `/attribution` `/badcases` 三条代理。

### 6. prism.py —— PASS

- ops 条目 :61-63：`dict(name="ops", port=8020, cwd=OPS_DIR, cmd=[sys.executable, "ops_server.py"], env={}, health="http://127.0.0.1:8020/", timeout=30)`——字段集/顺序与相邻 api 条目（:55-57）一致；`sys.executable` 用法与 api 完全同款；OPS_DIR 定义于 :35。
- health URL 正确：GET / 返回 index.html 200；probe()（:220-228）任何 HTTP 应答即算活，与注释"无独立 /health 端点"匹配。
- 语法：`python -c ast.parse` 对 prism.py 与 ops_server.py 双双通过（AST-OK both）。
- SERVICES 现 6 条与文件头 docstring"六个服务"一致。

### 7. 数据一致 —— PASS

- ops_server.py grep `INSERT|UPDATE|DELETE|REPLACE INTO` → 零匹配；全文唯一写动作是 import 时的 `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`（幂等空转，与主站启动同款）。
- ops 每请求 connect→SELECT→close，与主站 POST /events 写入同库不同进程；SQLite 跨进程读写由默认 5s busy timeout 兜底，无锁死风险面。

---

## 二、问题清单（分级）

**P0：无。**

**P1：无。**

**P2（3 条）**

1. **P2-1 ops 暴露 FastAPI 默认文档路由**
   - 位置：prism-ops/ops_server.py:56（`FastAPI(title=..., version=...)` 未关文档）。
   - 触发路径：GET `http://127.0.0.1:8020/docs|/redoc|/openapi.json`。
   - 影响：路由面比"声明的 6+GET /"多 3 个；泄露 API schema（端点/参数结构）。因仅绑 127.0.0.1 且无敏感参数，实际风险低，属暴露面收口不彻底（proposal D3 的精神是收口）。
   - 建议修法：`FastAPI(title='Prism-Agent Ops', version='0.1.0', docs_url=None, redoc_url=None, openapi_url=None)`。

2. **P2-2 303MB trajectories.jsonl 每请求全量重解析 × 30s 自动轮询**
   - 位置：ops_server.py:221-232（/badcases/quadrant 建 preview）、:271-281（/trajectory 详情）、:293-307（列表）、:324-333（/attribution）——均逐行 json.loads 全文件。
   - 触发路径：看板页 setInterval 每 30s 调 /badcases/quadrant（index.html:466/:478）→ 每次轮询都全量解析 ≈303MB JSONL。
   - 影响：单次解析秒级 CPU 峰 + preview 字典常驻内存（按 sid 数量）；轮询放大后 ops 进程周期性高负载，quadrant 响应变慢。属"原样移植"保留下来的既有行为，非本次引入的回归，但独立端口+自动轮询使其被放大。
   - 建议修法：按文件 mtime 缓存解析结果（ trajectories.jsonl 只追加，mtime 不变直接复用），或看板侧对 quadrant 降频/手动刷新。

3. **P2-3 /trajectory/all 与 /attribution 'all' 可一次性回吐全量 303MB**
   - 位置：ops_server.py:277（`session_id == 'all'` 放行全部）、:330（attribution 同款 'all' 分支）。
   - 触发路径：GET /trajectory/all → 全文件解析后整体 JSON 序列化返回。
   - 影响：无界响应体 + 全对象驻内存，浏览器/进程内存尖峰。同样是搬迁前既有语义。
   - 建议修法：ops 侧去掉 'all' 支持或加条数上限（页面只用具体 sid，不依赖 all）。

**P3（记录性，不建议本次动）**

1. loadAll 无在途去重：30s 轮询与上一轮未完成时可重叠，陈旧响应可能短暂覆盖新渲染（本机毫秒级延迟，影响可忽略；index.html:460-479）。
2. 若外部环境预设了 `PRISM_OPS_PORT`，ops 实际监听端口会偏离 prism.py 注册表的 8020 → 探活误报失败。可在 SERVICES ops 条目 env 显式钉 `{"PRISM_OPS_PORT": "8020"}`（prism.py:61-63 / ops_server.py:384）。
3. main.py:74 注释含"北极星指标数据源"字样——描述的是保留的 /events 写链路，语义准确，无需清理。

---

## 三、审查局限（如实声明）

1. 本目录非 git 仓库、无搬迁前 main.py 快照："六端点原样移植、口径与搬迁前一致"只能按设计要点在现磁盘代码上逐点实证（全部命中），无法做逐字节 diff。
2. 运行时验收项（TestClient 六端点 200 + 数字对账、主站 8002 五端点 404、tsc/build、smoke:all、tabbit UI 走查）属 Step8/T3.x 范畴，本次只读代码审查未复跑。
3. index.html 审读覆盖全部 innerHTML/textContent 写入点与属性/style 注入面；"等价转义"仅 esc() 一种，未发现第二套转义函数（也就无从漏核）。
