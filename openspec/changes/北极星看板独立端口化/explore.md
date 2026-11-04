# 北极星看板独立端口化 · Step1 explore（2026-10-13）

> 用户拍板产品形态：北极星看板不进 Prism 主站前端，独立端口子服务（对齐 prism-dashboards:8010/prism-sentiment:8000 模式）。管理者运营数据与产品用户面物理分离，顺带收口审查 P2-9 的无鉴权暴露。

## 实测事实

1. **消费面干净**：主站对 5 个北极星端点（stats/trends/quadrant/trajectory×2/attribution）的消费方只有 MetricsView.tsx + BadCaseDrawer.tsx（即将删除的两个组件）；eval/、tests/、根 py 零引用
2. **待搬端点定位**（并行会话在改 main.py，行号会漂，以函数名为准）：/events/stats、/events/trends、/badcases/quadrant、/trajectory（列表+详情）、/attribution/{sid} + ATTRIB_DIMS 常量
3. **TRAJECTORIES_FILE 四个使用点**全在待搬端点内（定义+3 处使用）→ 可整体搬走；**EVENTS_DB 保留**在主站（/events POST 埋点接收 + _init_events_db），ops 服务自建同款常量（绝对路径指项目根，幂等建表）
4. **端口 8020 空闲**（netstat 确认）
5. **prism.py SERVICES**：加 dict 模式（name/port/cwd/command），有 dashboards 先例（Anaconda 拉起）——ops 用系统 python（同 api 服务）
6. **样式令牌**：北极星页用 .kpi-*/.chart-*/.tag/.drawer*/.board-bar/.board*/.card/.legend/table——styles.css 抽段内嵌进 ops 单页（含 :root 色变量）
7. **UI 现状**：Sidebar 第四入口 / App View 'metrics' / view-stack 第三子级 / vite 三条代理（/trajectory /attribution /badcases）/ styles.css #viewMetrics 规则——全部待删
