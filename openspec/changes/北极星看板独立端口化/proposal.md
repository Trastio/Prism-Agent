# 北极星看板独立端口化 · Step2 proposal（2026-10-13）

## WHY

用户拍板：北极星看板（DAU/点踩/会话回放/结论全文）是管理者运营数据，不应出现在给 ~49 人用的主站前端。独立端口 = 物理分离 + P2-9 暴露面收口（默认绑 127.0.0.1，上云时挂 Basic-Auth 或不上云）。

## WHAT

**新建 `prism-ops/`（:8020）**：
- `ops_server.py`：FastAPI，绑 127.0.0.1:8020，承载 6 个端点（原样移植）：/events/stats、/events/trends、/badcases/quadrant、/trajectory（列表+详情）、/attribution/{sid}；自建 EVENTS_DB/TRAJECTORIES_FILE 常量（绝对路径指项目根）+ 幂等建表；GET / 返回单页
- `static/index.html`：vanilla 单页（零构建零 node 依赖）——7 KPI / DAU 双线 SVG / 结论柱图 / 四象限 / 明细表 / 回放抽屉 / 30s 轮询 + 手动刷新 / 错误横幅 / 口径脚注；样式从 styles.css 抽令牌段内嵌（:root 色变量 + .kpi/.chart/.tag/.drawer/.board-bar/.card/.legend/table 段）

**主站清理（prism-web + prism-api）**：
- main.py 删 5 端点 + TRAJECTORIES_FILE + ATTRIB_DIMS（EVENTS_DB 与 /events POST 保留——埋点链路不动）
- MetricsView.tsx / BadCaseDrawer.tsx 删除；App.tsx View 'metrics' 与引用删；Sidebar 第四入口删；vite 三条代理删；styles.css #viewMetrics 规则删
- tracker.ts / prism_events.db / eval/badcases.md 不动

**prism.py**：SERVICES 加 ops 条目（port 8020 / cwd prism-ops / python ops_server.py）+ 探活

## 决策

| # | 决策 | 推荐 |
|---|---|---|
| D1 | 端点归属 | 北极星 5 端点整体搬 ops，主站删除（消费面已证零残留）；/events POST 留主站 |
| D2 | 前端形态 | vanilla 单文件（运营页功能固定、交互简单、上云=小容器）；不建第二个 React 链路 |
| D3 | 网络面 | 绑 127.0.0.1（默认仅管理者本机）；上云清单：Basic-Auth 或不上云 |
| D4 | ops 自身埋点 | 不做（v2） |

## 影响范围

prism-ops/（新）、prism-api/main.py（删段）、prism-web/src（删 2 组件+3 处接线+3 代理+1 CSS 规则）、prism.py（+1 服务）、上线方案文档（ops 上云一条待补）。**不动**：extension/网关/AGENTS.md/埋点链路/eval。

## 风险

- R1 并行会话共用 main.py：删除段与对方改动区域重叠风险低（对方在 Agent 工具取数层 L877+），施工前后 grep 函数名核对
- R2 ops 页面与主站数据同源（prism_events.db）：ops 只读不写，无锁冲突（SQLite 只读并发安全）
- R3 vanilla 移植走样：以功能清单逐项对照验收（7 KPI+2 图+4 格+表+抽屉+轮询）

## 验收

1. ops TestClient 六端点 200 且数字与搬迁前主站一致（对账）
2. 主站（8002 重启后）5 端点 404，/events POST 仍 200 写库
3. 主站 tsc 零新增 + build 绿；主站 UI 无北极星入口（tabbit 复查侧栏）
4. ops 页面浏览器走查（tabbit 开 127.0.0.1:8020）：KPI/图/四象限/明细/抽屉/轮询/刷新全过
5. prism.py status 见 ops 服务绿；smoke:all 全绿
6. 施工由 claude 型子代理执行（fork 型新协议），Step7 隔离审查
