# 北极星看板独立端口化 · Step5 施工报告（2026-10-13）

施工子代理执行 T1/T2/T3.1；T3.2/3.3/3.4（重启验证/tabbit 走查/smoke 回归）按任务单留主会话。
移植源全部从磁盘读取（prism-api/main.py + prism-web/src/components/MetricsView.tsx + BadCaseDrawer.tsx + styles.css），未凭记忆拼。

## M1 新服务 prism-ops

### T1.1 ops_server.py — PASS
- 新建 `prism-ops/ops_server.py`（FastAPI，title='Prism-Agent Ops' v0.1.0）。
- 常量绝对路径（cwd 无关）：`EVENTS_DB = _ROOT/prism_events.db`、`TRAJECTORIES_FILE = _ROOT/.pi/sessions/trajectories.jsonl`（`_ROOT = Path(__file__).resolve().parent.parent`，与 main.py 的 `Path(__file__).parent.parent` 同语义）。
- 幂等建表照抄 main.py `_init_events_db`：CREATE TABLE IF NOT EXISTS events（8 列）+ 3 索引（idx_events_type_ts / idx_events_session / idx_events_local），模块加载即执行。
- 六端点**逐字移植**（源行号=施工时磁盘状态）：/events/stats（main.py L162-233）、/events/trends（L236-272）、/badcases/quadrant（L275-348，含终轮归一+rowid 次级键+feedback 同窗+trajectories 预览）、/trajectory/{session_id}（L759-777）、/trajectory 列表（L780-803）、/attribution/{session_id}（L811-875）+ ATTRIB_DIMS 五维。每函数内 `import sqlite3 as _s`/`import json as _j`/`from pathlib import Path as _P` 就地导入，自包含（G6 审查 P0-1 教训落实）。
- GET / 用 `fastapi.responses.FileResponse(_STATIC_INDEX, media_type='text/html; charset=utf-8')`（实测响应头 content-type: text/html; charset=utf-8）。
- `__main__`：`uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('PRISM_OPS_PORT','8020')))`。
- ast.parse 通过。

### T1.2 static/index.html — PASS
- 新建 `prism-ops/static/index.html`，vanilla 单页零构建零依赖，功能对照 MetricsView.tsx/BadCaseDrawer.tsx 逐项移植：
  - 顶栏：`北极星看板 · 运营` + `30s 自动刷新` 标注 + 手动刷新 icon-btn（旋转箭头 SVG）。
  - 7 KPI（同款口径 foot）：看板 DAU/对话 DAU/总 DAU/周结论数（成功结论≈减点踩近似）/采纳率（含净）/人均结论/轮时长中位（P90+n 含验证重试）。
  - DAU 双线 SVG：照 DauChart 数学（viewBox 560×150、L30/R10/T10/B20、网格 0/0.5/1 三线、轴标 0/max、dots r=2.6、首尾日期 slice(5)）；结论柱图照 ConclChart 数学（bw=max(3, iw/n×0.62)、峰值 is-peak、height 下限 2）。色用 :root 令牌（accent=#b85638 / xt=#7C3AED / pos=#2348b8 / neg=#9c2a25 原值内嵌）。
  - 四象限 4 格：fail+点踩=tag-neg「双确认 · 最高优先处置」/pass+点踩=tag-warn「假阴性 · 最有信息量…」/fail 无反馈=tag-accent「机器判负…」/pass 无反馈=tag-pos「健康区」。
  - 明细表 50 行：fmtLocal（带 Z 解析/naive 补 Z/zh-CN 本地化）、短 id slice(0,8)、verdict 色 tag、预览 ellipsis（maxWidth 320）、工具数、轮数+settled≥3「重试多」tag-warn、👍👎。
  - 行点击回放抽屉：scrim+滑入 drawer；verdict 以行数据（events 终轮）为准、缺省回落轨迹末条；verdict_reason/as_of/轨迹条数（含重试轮）/终轮结论 pre-wrap 全文/工具清单计数 tag（tag-xt，按次数降序）；数据 fetch /trajectory/{sid}；竞态用 drawerReq 序号防旧响应覆盖。
  - 错误横幅：任一 fetch !r.ok → `接口异常：stats / trends / quad —— 30s 自动重试`（红色横幅，恢复后隐藏）。
  - setInterval 30s 轮询 + `document.hidden` 跳过（G5 对齐 tracker 心跳纪律）+ 手动刷新按钮。
  - 口径脚注全文照抄 MetricsView 页脚（数据起点 2026-10-06/测试数据/含重试/15min 排除/点踩会话级/local_id 自报/badcases.md 三问）。
  - 样式内嵌 <style>：从 styles.css 抽取指定段（:root 全量色变量/body/button/svg/[hidden]/.kpi*/.chart*/.legend/.tag 五变体/.card*/.drawer 族/.board-bar/.bar-*/.icon-btn/table 基础/.table-scroll/.board-scroll/.board）+ 手写等价补齐（.err-banner/.charts-grid/.quad-grid/.quad-cell/.eyebrow/.board-head 等），并保留 1180/900 两档 kpi-grid 响应式；未整份拷贝。
  - 所有插值文本过 esc() HTML 转义（DB/轨迹内容按不可信输入处理）。

### T1.3 M1 验收 — PASS（TestClient 实测输出）
- 六端点全 200；GET / 200 且 content-type=`text/html; charset=utf-8`、含「北极星」「30s 自动刷新」「badcase 四象限」「轮时长中位」。
- stats：`{'dau': 3, 'chat_dau': 1, 'total_dau': 3, 'weekly_conclusions': 36}`，latency=`{'median_ms': 26696, 'p90_ms': 87765, 'n': 26, 'excluded': 10}`（有 total_dau/latency，数字合理）。
- trends?days=3：三行连续日期（2026-10-11/12/13）。
- quadrant：四键齐全 `{'pass_clean': 7, 'pass_with_down': 0, 'fail_clean': 1, 'fail_with_down': 0}`，total_sessions=8，items=8。
- trajectory 列表 200（223 sessions）；详情 /trajectory/all 200（count=1026）；attribution/latest 200（五维 dims 齐全）。
- **对账 PASS**：stats 的 dau/total_dau/weekly_conclusions 与直连 SQLite 同口径 SQL 复算一致（3/3/36）；quadrant total_sessions 与终轮 ROW_NUMBER 复算一致（8）。

## M2 主站清理

### T2.1 main.py 删段 — PASS
- 删前复核：grep 六函数名+两常量，代码引用全部在待删段内（其余命中为 openspec/设计文档）；TRAJECTORIES_FILE 四使用点（定义+quadrant+trajectory×2+attribution）全在待删段（G1 复核通过）。
- 删除 Edit A：/events/stats + /events/trends + /badcases/quadrant 三函数整段；删除 Edit B：T-8.2 注释块 + TRAJECTORIES_FILE + /trajectory 详情/列表 + T-8.3 注释块 + ATTRIB_DIMS + /attribution 整段。
- **保留**：EVENTS_DB（L76）、_init_events_db（L78）、POST /events（L120）——埋点链路不动（红线）。
- 行数 1456 → 1146；ast.parse 通过；残留 grep（TRAJECTORIES_FILE/ATTRIB_DIMS/六函数名/六路由）零命中。
- import 清理：待删段全部函数内 import（_s/_j/_P），顶层无仅被删段使用的导入，无需改动。
- 并行会话备注：施工中收到 Edit 工具提示「磁盘文件已在本会话读取后被修改」（对方会话在 L877+ 区活动）。两次 Edit 均以目标段全文精确匹配命中（目标段文本与读取时一致，未受对方改动影响）；删前 grep 行号复核过（162/236/275/352/759/780/811/877），对方活跃区「Agent 工具取数层」一行未动。

### T2.2 前端清理 — PASS
- 删 `prism-web/src/components/MetricsView.tsx`、`BadCaseDrawer.tsx`。
- App.tsx：删 import MetricsView、`type View` 收窄为 `'kanban' | 'chat'`、view-stack 内 `<MetricsView>` 行及其注释。
- Sidebar.tsx：Props 的 active/onNavigate 类型收窄 `'kanban'|'chat'`；删北极星入口按钮（atom icon 行）及注释。
- vite.config.ts：删 /trajectory /attribution /badcases 三条代理及注释。
- styles.css：删 `#viewMetrics.is-active` 规则及注释。

### T2.3 M2 验收 — PASS
- 根目录 `npx tsc --noEmit`：**11 个错误 = 历史基线**（施工前后各跑一次，均为 11；分布 datasource.ts×1、smoke.ts×1、verify/*×9，全部 TS5097/TS2322 存量）。
- `cd prism-web && npm run build`：成功（✓ built in 2.49s）。
- `grep -rn "MetricsView\|BadCaseDrawer" prism-web/src` 零命中；扩展到 prism-web 全目录（排 node_modules/dist）零命中；`'metrics'`/`viewMetrics`/vite 三代理残留零命中。
- `grep TRAJECTORIES_FILE prism-api/main.py` 零命中。
- 语法：`python -c "import ast; ast.parse(...)"` main.py / prism.py / ops_server.py 三文件全过。

## M3 注册

### T3.1 prism.py SERVICES — PASS
- 新增常量 `OPS_DIR = os.path.join(PROJECT_ROOT, "prism-ops")`（对齐 SENTIMENT_DIR/DASHBOARDS_DIR 风格）。
- SERVICES 在 api 条目后插入 ops dict（照现有格式）：
  `dict(name="ops", port=8020, cwd=OPS_DIR, cmd=[sys.executable, "ops_server.py"], env={}, health="http://127.0.0.1:8020/", timeout=30)` —— python 用法对齐 api 服务（sys.executable 直跑脚本），探活 GET /（G7：无 /health 也能探），附注释说明来源与上云口径。
- ast.parse 通过。

## 未做（按任务单留主会话）
- T3.2 重启验证（8002 五端点 404 + /events POST 200 + ops 8020 拉起）
- T3.3 tabbit UI 走查（主站无北极星入口；8020 页面全功能）
- T3.4 smoke:all 回归

## 记录项（不擅改，供主会话裁量）
1. prism.py 文案仍写「五个服务/五个端口」（docstring、cmd_start 打印、cmd_stop 结尾）——SERVICES 现为 6 项，纯文案不影响功能，未越任务单改动。
2. Icons.tsx 的 `atom` 图标定义随入口删除成为无引用死图标（无 tsc 报错），可留待死码清理 change 处理。
3. 并行会话对 main.py 的改动发生在 L877+（Agent 工具取数层），与本次删除段无文本重叠；建议主会话 T3.2 重启前按 G8 惯例查 logs/ 网关重启记录。

## 交付物清单
- 新增：`prism-ops/ops_server.py`、`prism-ops/static/index.html`
- 修改：`prism-api/main.py`（删 ~310 行）、`prism-web/src/App.tsx`、`prism-web/src/components/Sidebar.tsx`、`prism-web/vite.config.ts`、`prism-web/src/styles.css`、`prism.py`
- 删除：`prism-web/src/components/MetricsView.tsx`、`prism-web/src/components/BadCaseDrawer.tsx`
- 未动：tracker.ts、prism_events.db、eval/、openspec 其他文件、8002/8010/9200/5173 运行中进程
