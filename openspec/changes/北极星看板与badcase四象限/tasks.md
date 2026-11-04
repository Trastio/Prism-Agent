# 北极星看板与badcase四象限 · Step3 tasks（2026-10-13）

> 里程碑：M1 后端指标（可独立验收）→ M2 前端页面（依赖 M1 端点）→ M3 收尾（台账+回归+走查）。
> Step5 施工协议：先派探针子代理自报工具面（本 harness 子代理曾无文件工具而空转的教训）；工具面齐→派施工子代理；不齐→主会话代行施工，Step7 一律用"代码内嵌隔离审查"法。

## M1 后端指标（prism-api/main.py）

### T1.1 ts 窗口修复（坑①，D2）
- 新增模块级 helper `_ts_ok(col)` 返回 `julianday({col})` 比较式；/events/stats 与新端点统一走它
- 验证：`julianday('2026-10-13T03:31:25.776Z')` 与 `julianday('2026-10-06T12:00:00')` 均可解析（两种存量格式），日期边界手工对账

### T1.2 /events/stats 扩展（D4/D8）
- 现有 4 指标保留（改走 _ts_ok）+ 新增：
  - `total_dau`：page_view ∪ chat_start（近 24h，distinct local_id 并集）
  - `adoption`：up/down/settled₇d 三计数 + 三比率（D4）
  - `per_user`：settled₇d ÷ 近7天 distinct local_id
  - `latency`：每 settled 配对其之前最近 chat_start（同 session_id，相关子查询），中位数+P90，样本数 n；n=0 时置 null（前端空态）
- 口径注释写进 docstring（含"时延含验证重试"）

### T1.3 新端点 GET /events/trends?days=14（D5）
- days 参数 clamp 1-90，默认 14
- 逐日序列：date(ts,'localtime') 分桶，每日 {date, board_dau, chat_dau, total_dau, conclusions, thumbs_up, thumbs_down}（DAU=当日 distinct local_id）
- 空日期补零（序列连续，图表不缺口）

### T1.4 新端点 GET /badcases/quadrant（D3/D6/D9）
- **终轮归一**：每 session_id 取最后一条 chat_settled 的 verdict（窗口近 14 天）
- **feedback 匹配**：每条 👎（value='down'）配对其 ts 之前最近的 settled（同 session）→ 该轮标 thumbs_down=true；up 同理标 thumbs_up
- 聚合：{pass_with_down, pass_clean, fail_with_down, fail_clean} 四格计数
- 明细：最近 50 条终轮，字段 {session_id, last_ts, verdict, conclusion_preview(80字), tool_count, settled_count(≥3 标 retry_heavy), feedback}；结论预览从 /trajectory 侧取（读 trajectories.jsonl 匹配 sessionId；无匹配时空串，不阻塞——手造/旧格式 session 允许缺）
- 纯 GET 只读；trajectories 读取复用现有 TRAJECTORIES_FILE 常量

### T1.5 M1 验收
- curl/python 实测四个端点返回真数据；四象限聚合与手工 SQL 对账；latency 中位数与手工抽 3 轮对账

## M2 前端（prism-web）

### T2.1 vite.config.ts 三条代理
- /trajectory、/attribution、/badcases → 8002（/events 前缀已覆盖 stats/trends）

### T2.2 MetricsView.tsx（G1/G4，依赖 M1）
- 布局：KPI 行（看板 DAU/对话 DAU/总 DAU/周结论/采纳率/人均结论/轮时长中位+P90）→ DAU 双线 AreaChart（R5：_shared.tsx 若不支持双序列，用两条单序列并列，不新造图表）→ 周结论+反馈 BarChart → 四象限块（2×2 格，计数+说明文案）→ 明细表
- 明细表列：时间/会话短id/象限徽标/结论预览/反馈/重试轮数；行点击开 BadcaseDrawer
- 空态：trends 全 0 / 四象限全 0 / latency null 三种优雅降级（G4 坑②）
- 口径脚注：数据起点 2026-10-06、含开发期测试数据、时延含验证重试、local_id 口径（R2/R3/R4）
- TanStack Query：30s refetchInterval + 手动刷新按钮（invalidate 同 queryKey）

### T2.3 BadcaseDrawer.tsx（D9）
- 打开时 fetch /trajectory/{session_id}，渲染：verdict + verdict_reason、final_conclusion 全文、toolCalls 列表（name+次数）、settled_count（该 session 轨迹条数）
- 复用 EvidenceDrawer 抽屉样式（drawer/drawer-head 等 className）；加载态+无轨迹空态

### T2.4 App.tsx + Sidebar.tsx 接入
- View 联合类型 +'metrics'；view-stack 第三视图保活（display:none 模式一致）
- Sidebar sb-nav 第四项"北极星看板"（Icon 建议用现有 chart 类 symbol）；Props.active 类型扩；onNavigate 联动
- 切入 metrics 时 track('page_view')（visibilitychange 语义一致——由 view 切换驱动 page 字段，tracker 的 page 取 pathname 不变，够用）

### T2.5 tracker.ts 兜底 flush（D10）
- initTracker 里加 setInterval(flush, 60000)；卸载时清理（对齐既有 clearTimeout 纪律）

### T2.6 M2 验收
- web tsc 零新增错 + build 通过；dev server 下四端点数据渲染实测；抽屉回放实测（点一条真实 fail）

## M3 收尾

### T3.1 eval/badcases.md 台账初始化（D7）
- 表头：日期/来源(象限|verdict-fail|人工抽检)/session_id/现象/归因(五维)/处置(修复|转题|误报)/状态；附处置流程三问（谁说了算/可复现吗/红线级吗）与"红线级不等轮次"规则

### T3.2 回归门禁（R1）
- 跑前查 logs/ 网关重启记录（并行会话碰撞）；smoke:all 全绿 + 根 tsc 零新增（11 历史基线）+ web tsc + build

### T3.3 UI 走查（tabbit 或 CDP）
- 侧栏入口→北极星页；视图切换往返不丢状态；30s 轮询生效（network 面板可见）；手动刷新；空态截图留档

## 关键路径与并行簇

- M1 → T2.2（前端依赖端点契约）；T2.1/T2.5/T3.1 可与 M1 并行
- 端点契约（前端可先行 mock 的形状）：
  - `GET /events/stats` → {dau, chat_dau, total_dau, weekly_conclusions, feedback:{up,down}, adoption:{up_rate,down_rate,net_rate}, per_user, latency:{median_ms,p90_ms,n}}
  - `GET /events/trends?days=14` → {days:[{date,board_dau,chat_dau,total_dau,conclusions,thumbs_up,thumbs_down}]}
  - `GET /badcases/quadrant` → {quadrant:{pass_with_down,pass_clean,fail_with_down,fail_clean}, items:[{session_id,last_ts,verdict,conclusion_preview,tool_count,settled_count,retry_heavy,feedback}]}
