# Step10 archive · 北极星看板独立端口化（2026-10-13 归档）

## 一句话

用户产品形态拍板：北极星看板从主站前端撤出，独立为 prism-ops:8020 运营子服务（对齐 dashboards/sentiment 子服务模式）——管理者运营数据与产品用户面物理分离，运营端口默认仅本机，主站暴露面同步收窄。

## 交付物

**prism-ops/**（新子服务，FastAPI + vanilla 单页，零 node 依赖）
- ops_server.py（384→410 行）：六端点从 main.py 逐字移植（stats/trends/quadrant/trajectory×2/attribution）；绝对路径常量+幂等建表；Step8 加固：文档路由三关（P2-1）、_traj_preview() mtime 缓存只存精简字段（P2-2，303MB 轨迹文件轮询零成本化）、'all' 无界分支删除+50 条截断（P2-3）
- static/index.html（482 行）：vanilla 全功能——7 KPI/双线 SVG/柱图/四象限/明细表/回放抽屉（verdict 以 events 终轮为准）/30s 轮询/错误横幅/口径脚注/esc 全转义/抽屉竞态防护

**主站瘦身**
- main.py 1456→1146 行（删 5 端点族+2 常量，埋点链路 EVENTS_DB/_init_events_db/POST /events 完整保留）
- prism-web：删 MetricsView/BadCaseDrawer/接线/3 代理/#viewMetrics 规则；侧栏回到三项
- prism.py：SERVICES +ops（六服务文案已同步）

## 十步与子代理协议（本 change 的方法学价值）

- **fork 型重试制首次全程实战**：施工 2 派（1×NO-TOOLS 守卫退出 + 1×命中施工）、审查 2 派（同款）——命中率 ~40%，每次失败成本 ~1 分钟零副作用
- **审查自读磁盘模式**：隔离子代理直接 Read 审查对象（唯一真相源），彻底消除内嵌拼装失真（上一 change 两误报的根因）
- 施工子代理 1 处错报（atom 死码判断）被主会话 Step6 复核纠正——子代理报告逐条核实原则继续生效
- 探针数据点：claude 型两次命中均带完整工具面（Bash/Read/Edit/Write/Grep），两次未命中均纯 web 面——工具面 spawn 随机性再次确认

## 关键事实沉淀

- **trajectories.jsonl 已 303MB**（explore 时按 990 行评"无压力"是低估——单行含完整 conversation/toolResults）——评估文件 IO 看字节不看行数
- 主站→ops 的数据契约：prism_events.db（只读共用，埋点写端在主站）+ trajectories.jsonl（只读）
- 运营页验证口径：30s 轮询用 performance resource entries 计数实证（32s 窗口 2 次）

## 验收

6/6 全过（verification.md）：TestClient 对账 / 主站 404+埋点活 / tsc 基线+build+入口移除 / ops 页全功能含轮询实证 / 六服务注册+smoke 全绿 / 子代理施工+隔离审查合规。

## 留 v2

preview 重扫增量 / trajectory 列表端点 sqlite 化 / ops 上云形态（Basic-Auth）待上线方案拍板 / eval 快照如需 op 端点另行接入
