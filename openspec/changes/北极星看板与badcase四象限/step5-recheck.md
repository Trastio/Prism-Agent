# Step5 施工复核（独立子代理补位，2026-10-13）

> 背景：本 change 施工时主会话代行了施工子代理步骤（用户判定流程不合规），本文件为独立复核位补跑结果。
> 方法：只读代码 + 重跑验收命令，零代码修改。后端验收用 `python - <<EOF` heredoc（TestClient 直调，无临时文件残留）；前端验收 `npm run build` 实跑。
> 环境注意：并行会话在改 main.py 其他区域，行号可能漂移；本次行号以 2026-10-13 复核时点 grep 为准，只核"存在且逻辑在"。

## M1 后端

### 1. 三端点定位与扩展逻辑 —— PASS
grep 结果（prism-api/main.py）：
- `/events/stats`：`@app.get('/events/stats')` @ **L162**，`async def events_stats()` @ L163。扩展字段逻辑均在：
  - `total_dau`：近24h 任意事件 `COUNT(DISTINCT local_id)`（L185-187 附近）
  - `adoption`：up/down/settled₇d 三计数 + up_rate/down_rate/net_rate 三比率
  - `per_user`：settled₇ ÷ active7（distinct local_id 近7天）
  - `latency`：相关子查询配对同 session 其前最近 chat_start，median_ms/p90_ms/n/excluded（>15min 跨天脏配对排除）
- `/events/trends`：`@app.get('/events/trends')` @ **L236**，`async def events_trends(days: int = 14)` @ L237；days clamp `max(1, min(90, days))`，RECURSIVE 日历 LEFT JOIN 空日期补零，返回 {days:[{date,board_dau,chat_dau,total_dau,conclusions,thumbs_up,thumbs_down}]}
- `/badcases/quadrant`：`@app.get('/badcases/quadrant')` @ **L275**，`async def badcases_quadrant()` @ L276；终轮归一 + feedback 匹配 + 四格聚合 + 最近 50 条明细（conclusion_preview/tool_count 从 trajectories.jsonl 取，无匹配空串不阻塞，复用 TRAJECTORIES_FILE 常量）

### 2. 后端验收重跑 —— PASS（实际值如下）
TestClient 实测（sys.path.insert prism-api → from main import app）：
- `GET /events/stats` → **200**；键齐全：dau=3, chat_dau=1, **total_dau=3**, weekly_conclusions=33, feedback={up:0,down:0}, adoption={up_rate:0.0,down_rate:0.0,net_rate:0.0}, per_user=4.71, **latency={median_ms:23314, p90_ms:73742, n:23, excluded:10}** ✅ 含 total_dau/latency 键
- `GET /events/trends?days=3` → **200**；**返回 3 行**，首行键含 **date/board_dau**（另有 chat_dau/total_dau/conclusions/thumbs_up/thumbs_down）：`{'date':'2026-10-11','board_dau':2,'chat_dau':1,'total_dau':2,'conclusions':8,'thumbs_up':0,'thumbs_down':0}`（序列连续：10-11/10-12/10-13）
- `GET /badcases/quadrant` → **200**；**quadrant 四键齐全**：`{pass_clean:7, pass_with_down:0, fail_clean:1, fail_with_down:0}`（合计=total_sessions=8，items=8 条明细）
脚本末尾 `ALL BACKEND ASSERTIONS PASSED`。

### 3. quadrant SQL 细节 —— PASS
- 终轮归一：**L291** `ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY julianday(ts) DESC, rowid DESC)` —— 窗口函数 ✅ + **rowid 次级排序键** ✅（外层取 rn=1，即每 session 最后一条 chat_settled）
- feedback 查询 14 天窗：**L304** `julianday(ts) >= julianday('now','-14 day')`（settled 侧同窗 L295，均为近14天）

## M2 前端

### 4. MetricsView.tsx —— PASS
prism-web/src/components/MetricsView.tsx（259 行）存在，逐项确认：
- `jfetch`：`fetch(url).then(r => { if (!r.ok) throw new Error(...) })` —— **!r.ok throw** ✅
- 错误横幅：`(stats.isError || trends.isError || quad.isError)` → 红色"接口异常：… —— 30s 自动重试" ✅
- `DauChart`（看板/对话双线 SVG）/ `ConclChart`（结论柱图，峰值高亮）均定义 ✅
- `QUAD_DEFS` 四象限常量（fail_with_down/pass_with_down/fail_clean/pass_clean + 说明文案）✅
- `fmtLocal`（last_ts 本地化，兼容有无 Z 两种存量格式）✅
- `const REFRESH_MS = 30000` —— **30s** ✅（三查询均 refetchInterval + 手动刷新 invalidate 同 queryKey；enabled=active 切走即停）
- 另含：KPI 行七卡、空态三种（trends 全0 标"区间无数据"/四象限空态文案/latency null 显示"—"）、口径脚注（数据起点 2026-10-06/含测试数据/时延含重试/local_id 自报），均与 T2.2 对齐

### 5. BadCaseDrawer.tsx —— PASS
prism-web/src/components/BadCaseDrawer.tsx（80 行）存在：
- `verdict` prop（可选），注释与 UI 均标注 **"events 终轮"**（`verdict（events 终轮）`，避免与轨迹文件末条不同步自相矛盾）✅
- `q.isError` 分支（"回放接口异常"红字）✅；另有 Loading 态与"无轨迹"空态；fetch /trajectory/{session_id}、verdict_reason、final_conclusion 全文、工具跨轮计数、轨迹条数，复用 drawer 样式族 ✅

### 6. App.tsx —— PASS
- `type View = 'kanban' | 'chat' | 'metrics'` ✅ 含 'metrics'
- `<MetricsView active={view === 'metrics'} />` 是 `<div className="view-stack">` 的**直接子级**（在 viewChat div 之后平级；代码注释明确写"必须是 view-stack 直接子级——嵌在 viewChat 内会被其 display:none 连坐隐藏"）✅
- `useEffect(() => initTracker(), [])` ✅（注释注明 tracker 自带清理）

### 7. Sidebar.tsx —— PASS
`北极星看板`入口按钮在 sb-nav 内（**L89-90**）：`onClick={() => onNavigate('metrics')}`，`<Icon name="atom" /><span>北极星看板</span>`，active 联动 `active === 'metrics'`；Props.active/onNavigate 类型已扩含 'metrics'（L14-15）✅

### 8. vite.config.ts 三条代理 —— PASS
`/trajectory`、`/attribution`、`/badcases` 三条均 → `http://127.0.0.1:8002`（/events 前缀已有覆盖 stats/trends）✅

### 9. tracker.ts —— PASS
- `const FLUSH_INTERVAL_MS = 60000` ✅；`flushTimer = setInterval(flush, FLUSH_INTERVAL_MS)`（initTracker 内）
- 清理函数 ✅：initTracker 返回 `() => { clearInterval(heartbeatTimer); clearInterval(flushTimer); }`

### 10. 前端验收重跑 —— PASS
`cd prism-web && npm run build` → **成功**：`✓ built in 1.88s`（vite build 全程 wall time ≈4.2s；产物 index-BKtwyBVl.js 482.42 kB / css 280.39 kB，无报错）

## M3

### 11. eval/badcases.md —— **FAIL（位置偏差；内容本身齐备）**
- 预期路径 `eval/badcases.md`（根目录，proposal.md "新建"/tasks.md T3.1/archive.md 交付清单均此写法，根 eval/ 亦为台账目录——EVAL_STATUS.md 所在地）**不存在**该文件
- 实际落在 **`prism-web/eval/badcases.md`**（prism-web/eval/ 目录仅此一文件，创建于 2026-10-13 13:31，即施工时段）
- 内容核验：判断三问 ✅（谁说了算/可复现吗/红线级吗，含"红线级不等轮次，hotfix+冻结集回归"）、三通道来源、五维归因（对齐 /attribution）、记录格式表头（日期/来源/session_id/现象/归因/处置/状态）、处置枚举——T3.1 内容要求全满足
- 定性：**文件放错目录**（多套了一层 prism-web），交付清单与实际路径不符。修复动作（归属后续处置，本复核不改码）：把 prism-web/eval/badcases.md 移至根 eval/badcases.md 并删除空目录

## 总结论

**11 项：10 PASS / 1 FAIL**（唯一 FAIL = 第 11 项台账文件位置偏差，内容完整）

### 偏差清单
| # | 偏差 | 严重度 | 说明 |
|---|------|--------|------|
| 1 | eval/badcases.md 落在 prism-web/eval/ 而非根 eval/ | P1（流程交付物位置不符） | 内容齐全（判断三问等全在）；根 eval/badcases.md 不存在；需移动归位 |
| 2 | T1.1 的模块级 helper `_ts_ok(col)` 未按字面实现 | P3（备忘，不构成 FAIL） | main.py 无 `_ts_ok` 符号（grep=0）；julianday 窗口以内联字符串 win24/win7/win7s 实现（L172-174），trends/quadrant 直接内联 julianday 比较。T1.1 目标（两种存量 ts 格式统一 julianday 窗口）已达成，仅未抽公共 helper——复核清单第 1/3 项不含此项，不计 FAIL |

### 其他观察（不计分）
- /events/stats latency 含 excluded 计数（>15min 跨天配对排除），比任务单契约多一个字段，属超额交付非缺失。
- 行号基线（本次 grep）：stats L162 / trends L236 / quadrant L275 / ROW_NUMBER L291 / feedback 14d 窗 L304；并行会话改 main.py 其他区域会造成漂移，以"存在且逻辑在"为准。

—— 复核人：Step5 独立复核子代理（只读，未改任何代码；验收脚本为 heredoc 即用即弃，无临时文件残留）
