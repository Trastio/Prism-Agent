# 北极星看板独立端口化 · Step3 tasks + 3.5 自查（2026-10-13）

## M1 新服务 prism-ops

- **T1.1 ops_server.py**：FastAPI 应用（绑 127.0.0.1，端口取 env PRISM_OPS_PORT 默认 8020）；常量 EVENTS_DB/TRAJECTORIES_FILE（绝对路径指项目根）+ 幂等建表（照抄 main.py _init_events_db 的 CREATE IF NOT EXISTS + 3 索引）；六端点原样移植（从 prism-api/main.py 搬代码：/events/stats 含 latency 15min cap + adoption + per_user；/events/trends RECURSIVE 补零；/badcases/quadrant 终轮归一+rowid 次级键+feedback 同窗+trajectories 预览；/trajectory 列表+详情；/attribution/{sid} 五维归因 + ATTRIB_DIMS）；GET / FileResponse 返回 static/index.html；__main__ uvicorn.run(host='127.0.0.1', port)
- **T1.2 static/index.html**：vanilla 单页。功能清单（对照主站 MetricsView/BadCaseDrawer 逐项）：顶栏（标题+30s 自动刷新标注+手动刷新按钮）/ 7 KPI 卡（看板 DAU/对话 DAU/总 DAU/周结论/采纳率/人均/轮时长中位+P90）/ DAU 双线 SVG（accent+xt 两色+网格+轴标+首尾日期）/ 结论柱图（峰值高亮）/ 四象限 4 格（fail+点踩红/pass+点踩警/fail 无反馈/pass 无反馈蓝）/ 明细表（时间本地化 fmtLocal/会话短 id/verdict tag/结论预览/工具数/轮数+重试多标/反馈）/ 行点击回放抽屉（verdict 以 events 终轮为准+结论全文+工具清单计数+轨迹条数）/ 错误横幅（fetch !ok 显示+30s 重试标注）/ 口径脚注（数据起点/测试数据/含重试/15min 排除/点踩会话级/local_id 自报）。样式：内嵌 <style>，从 styles.css 抽 :root 变量 + .kpi*/.chart*/.tag*/.drawer*/.board-bar/.board-scroll/.board/.card/.legend/table 段（原子集，别整份拷）。JS：原生 fetch + setInterval 30s + 手动刷新函数 + fmtLocal（带 Z 解析/naive 补 Z）
- **T1.3 M1 验收**：TestClient 六端点 200；GET / 返回 HTML；对账 stats 数字

## M2 主站清理

- **T2.1 main.py 删段**：5 端点 + TRAJECTORIES_FILE + ATTRIB_DIMS（**EVENTS_DB/_init_events_db/POST /events 保留**）；删前 grep 每个函数名确认无其他引用；import 清理（只被删段用的）
- **T2.2 前端清理**：删 MetricsView.tsx/BadCaseDrawer.tsx；App.tsx 删 import/View 'metrics'/view-stack 第三子级；Sidebar.tsx 删第四入口 + Props 类型收窄回 'kanban'|'chat'（onNavigate 同）；vite.config.ts 删 /trajectory /attribution /badcases 三条；styles.css 删 #viewMetrics 规则（含注释）
- **T2.3 M2 验收**：根 tsc 11=基线；web build 绿；grep 全仓零残留（MetricsView/BadCaseDrawer/badcases 代理）

## M3 注册与端到端

- **T3.1 prism.py**：SERVICES 加 ops dict（name='ops', port=8020, cwd=PRISM_OPS_DIR, 命令=系统 python ops_server.py，探活 30s 同款）
- **T3.2 重启验证**：主站 8002 重启后 5 端点 404 + /events POST 200（curl 发一条测试事件验写库）；ops 8020 起服务
- **T3.3 UI 走查（tabbit）**：主站侧栏无北极星入口；127.0.0.1:8020 页面全功能（KPI/图/四象限/明细/抽屉/30s 轮询/刷新/脚注）
- **T3.4 回归**：smoke:all 全绿

## 3.5 自查（预演 Gap）

- G1 TRAJECTORIES_FILE 使用点全在待搬端点内（explore 已 grep：314/763/785/816）✅ 施工删前再核一次
- G2 ops 与主站同 python 环境（fastapi/uvicorn 在系统 python，api 服务同款）✅
- G3 静态 serve 用 fastapi.responses.FileResponse；确保 UTF-8（HTML 头 meta charset）
- G4 index.html fetch 同源相对路径 ✅；CORS 不需要（同源）
- G5 轮询实现 setInterval + document.hidden 时跳过（对齐 tracker 心跳纪律）
- G6 **审查 P0-1 教训**：ops_server.py 每个函数内 import sqlite3 as _s 保持自包含；施工子代理从磁盘提取 main.py 段落做移植源
- G7 prism.py 探活路径 GET / 返回 HTML 200 即可（无 /health 端点也行）
- G8 并行会话：删除 main.py 段落前 grep 函数名+行号复核（对方活跃区在 L877+ Agent 工具层，低重叠）；重启 8002 前查 logs
