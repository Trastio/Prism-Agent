# Step10 archive · 北极星看板与badcase四象限（2026-10-13 归档）

## 一句话

把"分析自家产品用户"的埋点闭环从"采（已通）→ 零消费"收口为"采→看→挖"：北极星指标可视化页面（7 KPI+DAU 双线+逐日趋势）+ badcase 四象限（verdict×点踩，终轮归一）+ 会话回放抽屉 + badcase 台账骨架。

## 交付物

**后端（prism-api/main.py）**
- /events/stats 扩展：total_dau（任意事件去重）/adoption 三率/per_user/latency（settled 配对最近 start，15min cap 排脏配对，中位+P90+n+excluded）；ts 窗口统一 julianday()（修复字符串比较近似——旧口径 35→精确 32）
- GET /events/trends：RECURSIVE 日 spine 补零，本地日分桶，days clamp 1-90
- GET /badcases/quadrant：终轮归一（每 session 末条 settled，rowid 次级键）+ feedback session 级同窗匹配 + trajectories 预览 + retry_heavy（settled≥3）

**前端（prism-web）**
- MetricsView.tsx（第三视图）：7 KPI / DAU 双线+结论柱图（手写 SVG，复用 .chart-*/.kpi-* 幸存令牌，零新依赖）/ 四象限 4 格 / 明细表 / 错误横幅 / 口径脚注 / 30s 轮询+手动刷新（enabled=active 切走即停）
- BadCaseDrawer.tsx：/trajectory 回放（verdict 以 events 终轮为准防双源矛盾 / 结论全文 / 工具清单跨轮累计）
- Sidebar 第四入口"北极星看板"（atom）+ App View 扩 'metrics' + styles.css `#viewMetrics.is-active` + vite 三条代理 + tracker 60s 兜底 flush（含清理函数）

**流程件**
- eval/badcases.md：台账骨架（三通道来源/判断三问/五维归因/记录格式，不填种子）

## 关键决策（D1-D10 全按推荐执行）

D2 查询侧 julianday / D3 终轮归一 events 内自洽 / D4 采纳三率+近似成功结论 / D5 本地日分桶 / D6 重试轮数轻量信号 / D7 台账立骨架 / D8 轮时长配对+15min cap / D9 抽屉复用 drawer 样式族 / D10 60s flush。详见 proposal.md。

## 施工与审查

- 探针协议先行：子代理工具面证实无文件工具（Read/Write/Bash 全缺）→ 主会话代行施工 + 隔离审查走代码内嵌法（~30KB）
- 施工自抓 2 集成 bug：①MetricsView 锚在 ChatView 组件闭合处→嵌进 viewChat 被 display:none 连坐（tabbit 诊断 7 KPI 在 DOM 但 0×0）②视图点亮 CSS 按 id 写死无 #viewMetrics 规则
- 隔离审查 13 条（1P0+2P1+10P2）：修 6 / 误报关闭 4 / 记录 3。两个误报根因相同——**审查包拼装漏行**（trends import / tracker 既有 flush 段），教训：内嵌包必须磁盘提取或 diff 校验
- P1-1 时区疑点坐实为写入端全 UTC 无偏移；残留进上云清单（ECS 时区 Asia/Shanghai）

## 验收

7/7 全过（对照表见 verification.md）：SQL 对账 ALL MATCH / KPI 与后端逐项一致 / 四象限对账 / 空态 / flush（后补浏览器实测：入队→落库 60s 整）/ smoke+tsc+build 全绿 / tabbit 走查两轮。

## 收尾补录（10-13 同日，用户确认后补）

- **60s 兜底 flush 浏览器实测 PASS**（原验收为代码级证据，已升级为实测：1 条不满批 page_view 入队→落库 60s 整）
- **设计图同步**：评估体系完整方案 §7.5 补第三搜集通道（北极星四象限，含"68% fail 率需终轮归一"警示与 pass+点踩=假阴性优先）+ 账本状态更新（badcases.md 已立骨架）+ 标题版本注 v3.4.4

## 教训沉淀

1. **内嵌审查包的拼装失真是新的失败模式**——审查者对残缺代码的推理完全正确，错的是我给的输入。与教材"评测集先于 agent 排查"同构：输入错了，下游全对也白搭
2. 视图接入的两个坑（嵌套层级 + id 点亮 CSS）都是"以为插对了"型——DOM 诊断（computed display + stackChildren）比盯代码快
3. tabbit 走查 waitForSelector(state:visible) 抓隐 bug 好用：元素在但 0×0 立刻暴露
4. 并行会话纪律实践：查 logs 重启记录→避开对方验收面（8010）→单服务最小窗口重启

- **Step5 合规补救**（用户拍板"主会话代行施工不合规"后）：①探针实测打通 **fork 型=claude 型子代理有 Bash+Read**（留痕验证；general-purpose 仍无文件工具第 4 次实证；附带发现 ToolSearch `select:` 精确语法才是可靠载入方式）②派 claude 型施工复核子代理独立核验 11 项（step5-recheck.md 87 行）：**10 PASS / 1 FAIL**——FAIL=badcases.md 落在 prism-web/eval/（cwd 漂移事故），已移回根 eval/ 并删空目录。备忘偏差（不计 FAIL）：T1.1 `_ts_ok` helper 未抽公共函数（内联实现目标已达成）
- 附注：**归档件两轮被外部删除**（第一轮 review-response/verification/archive 三件、第二轮 verification.md 单件再消失，均发生在并行会话活跃期；删除者未明）——本目录文件均为重建版，留意并行会话的清理脚本

## 留 v2

trajectories mtime 缓存 / adoption session 级配对 / unknown verdict 独立计数 / 上云前鉴权收口与时区锁定 / langfuse 接线（独立 change）/ 弹窗两问（阶段⑤）
