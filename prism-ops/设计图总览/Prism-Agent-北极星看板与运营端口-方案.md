# Prism-Agent · 北极星看板与运营端口 · 方案 v1.0

> 2026-10-13 定稿。来源：两个 change 的收敛（`openspec/changes/北极星看板与badcase四象限/` + `北极星看板独立端口化/`，均十步归档）+ 用户三项拍板（做四象限 / 运营数据不进主站 / D8 上云=方案 A）。本文档是北极星线的**单一方案真相源**，change 目录为过程归档。

## 一、为什么（问题链）

1. 埋点采集闭环早已打通（tracker 8 类事件 → prism_events.db），但**零消费**——北极星四个指标的 SQL 躺在裸 API 里没有任何页面
2. badcase 界定只有两条渠道（trajectories verdict=fail 每周翻 + 👎 点踩）且**从未交叉**；fail 率 68%（含回灌/保底/闲聊轮）不归一就会被淹没
3. 产品形态拍板：DAU/点踩/会话回放是**管理者运营数据**，不进给 ~49 人用的主站——独立端口物理分离

## 二、指标体系（口径表）

| 指标 | 口径 | 已声明近似 |
|---|---|---|
| 看板 DAU ⚠️ | 近24h page_view 去重 local_id | **命名待修**：page_view 在挂载即发且默认视图=对话 → 实为"打开过去重"（见 §八 待办） |
| 对话 DAU | 近24h chat_start 去重 | — |
| 总 DAU | 近24h 任意事件去重（含心跳） | local_id 浏览器自报，清缓存重计；与看板 DAU 高重合 |
| 周活跃 WAU | 近7天任意事件去重 | 同上 |
| 黏性 | 总DAU ÷ WAU | 窗口不一致（24h 分子÷7d 分母），小样本抖动 |
| **周成功交付结论数**（产品北极星） | 近7天有「过闸结论」的会话去重（`conclusion_emitted` value=ok，会话级归一） | **埋点自 2026-10-13 起**；此前的历史为 0。旧口径曾用 settled 会话数顶替（含 fail/闲聊），已废 |
| 交付率 | 交付结论会话 ÷ 终轮(settled)会话 | 解释"多少对话真正产出了合格结论" |
| 采纳率 | 👍/近7天交付结论（另示净采纳 (up−down)/交付结论） | 同一会话多次反馈分别累计，可>100%；👍 稀疏，"沉默≠不采纳" |
| 人均结论 | 交付结论₇d ÷ WAU | 分母含只看看板不对话的用户（稀释） |
| 每人轮数 | 近7天 chat_start 数 ÷ WAU | 同上 |
| 轮时长中位 | 每 settled 配对其前最近 chat_start 的 ts 差 | 含重试（偏大）；abort 轮无 settled 不计（幸存者偏差，偏小）；>15min 跨天脏配对排除 |
| 四象限 | 终轮 verdict(机器) × 点踩(用户) | verdict 是机器完成度校验、非用户满意度 |

> **2026-10-13 口径修订**：① 移除"在线时长"（口径可被"挂机"污染 + 看板/对话分线依赖失效的 session_id 代理，见 §八）；② 「周结论数」升级为真产品北极星**周成功交付结论数**（新埋点 `conclusion_emitted`，见 §九）；③ 补 WAU/黏性/每人轮数/交付率 衡量使用深度。

> 指标体检遗留（待办）：看板 DAU 命名/口径、总 DAU 与 WAU 的"任意事件"含糊、黏性窗口不一致、采纳率沉默偏差、人均与每人轮数分母应限定"有对话用户"、轮时长幸存者偏差——均为已知问题，排期见 §七。

统一技术底座：ts 窗口 `julianday()` 比较（兼容 ISO+Z 与无时区两种存量格式）；写入端全 UTC 坐实。趋势分桶 `date(ts,'localtime')` **本地日**——上云依赖 ECS 时区=Asia/Shanghai（已入上云清单）。

## 三、badcase 四象限方法论

**终轮归一**：每 session 取最后一条 chat_settled 的 verdict（重试轮也发事件，末条即终轮；rowid 次级键去并列不确定性）。

| | 用户点了踩 | 无反馈 |
|---|---|---|
| **机器 fail** | 双确认·最高优先处置 | 可能判分过严或用户未细看 |
| **机器 pass** | **假阴性·最有信息量**（判分盲区或预期错位，此前完全漏掉的一类） | 健康区 |

- feedback 按 **session 级**归属终轮（点踩时用户看到的是该会话终答，轮级配对误差在 session 级消失）
- 辅助信号：retry_heavy（session 内 settled≥3 标"重试多"）
- 处置流程：`eval/badcases.md` 台账（判断三问：谁说了算/可复现吗/红线级吗；红线级不等轮次 hotfix）；搜通道三路=四象限/verdict-fail 周翻/人工抽检（详见评估方案 §7.5 v3.4.4）

## 四、架构

### 本地（当前形态）
```
主站 5173 ──埋点 POST /events──▶ 8002 main.py ──写──▶ prism_events.db ◀─只读─┐
                                                                             ├─ prism-ops :8020（绑 127.0.0.1）
pi 网关 agent_settled ──写──▶ .pi/sessions/trajectories.jsonl ◀─只读(mtime缓存)─┘
```
- prism-ops = FastAPI + vanilla 单页（零构建零 node 依赖），prism.py 六服务之一
- 主站已删全部北极星端点与组件（埋点链路保留）；侧栏无入口
- 安全面：ops 只绑本机；文档路由三关（/docs /redoc /openapi.json 均 404）；单页全部 innerHTML 写入点 esc() 转义；对 events 库零写点（除幂等建表）

### 上云（D8 拍板·方案 A，2026-10-13）
- compose 第 5 常驻容器，与 prism-api **只读共享 volume**（events.db + trajectories.jsonl）——数据同机实时读零同步
- **容器内 `PRISM_OPS_HOST=0.0.0.0`**（容器内绑 127 连不上端口映射）+ compose `ports: ["127.0.0.1:8020:8020"]` 只映射宿主机 loopback = **零公网暴露**（不进 Nginx，扫不到）
- 访问：`ssh -N -L 8020:localhost:8020 <ecs>` + 浏览器 localhost:8020（上云时落双击 .bat 壳）
- 选型理由：北极星看**线上实时埋点**（数据源在云上，留本地看不到）；与 langfuse 留本地不矛盾（后者看本地批跑轨迹）
- **登录门（2026-10-15 上线）关系**：ops 有意不在登录体系内——管理者面走网络隔离（SSH 隧道），不叠 Basic-Auth（对应上线方案 D2/D8 拍板）。但登录门改变了用户级指标口径：local_id 此前=匿名随机串（一人多号、DAU 虚高）、此后=token 实名用户名，**趋势线以 2026-10-15 为分界日分段解读，不可连线**（代码注释 ops_server.py 已入档 d78efef）

## 五、端点契约（prism-ops:8020）

| 端点 | 响应要点 |
|---|---|
| GET / | 运营单页（4 聚合 KPI 卡/DAU 双线/交付结论柱图/四象限/明细 50 行/回放抽屉/时间范围切换/四象限↔明细联动/图表缩放平移/30s 轮询） |
| GET /events/stats | {dau, chat_dau, total_dau, wau, stickiness, turns7, weekly_conclusions(交付结论), settled_sessions, delivery_rate, feedback, adoption(三率), per_user, per_user_turns, latency{median_ms,p90_ms,n,excluded}, test_filter{enabled,excluded_sessions,local_denylist}} |
| GET /events/trends?days=14 | 逐日 {date, board_dau, chat_dau, total_dau, conclusions(过闸结论), thumbs_up, thumbs_down}（RECURSIVE 补零，days clamp 1-90） |
| GET /badcases/quadrant?days=14 | {window_days, total_sessions, quadrant 四格, items[50]：session_id/verdict/conclusion_preview/tool_count/settled_count/retry_heavy/feedback}（days clamp 1-90） |
| GET /trajectory | 有轨迹的 session 列表（去重，最近优先；人工消费面） |
| GET /trajectory/{sid} | 该会话轨迹（**最近 50 条截断**+truncated 字段；无 'all' 模式） |
| GET /attribution/{sid} | 五维归因（对象理解/能力选择/工具调用顺序/权限边界/业务结果，规则推断版） |

## 六、运维要点

- 采集侧：tracker.ts 攒批 5 条/60s 兜底 flush/关页 sendBeacon——关键事件（settled/feedback）即时发
- 性能：trajectories.jsonl 已 300MB+——`_traj_preview()` 按 mtime 缓存**只存精简字段**（sid→结论预览+工具数；全量解析驻内存会 GB 级）；轮询期间 mtime 不变零成本
- 探活：prism.py status / `curl 127.0.0.1:8020/events/stats`

## 七、留 v2 / 待办

**性能与功能 v2**：preview mtime 变化后的重扫仍全量（彻底解=轨迹 sqlite 化）/ adoption 改 session 级配对 / unknown verdict 独立计数 / trajectory 列表端点 sqlite 化 / ops 页自身埋点（运营页使用行为）/ **成本·token 聚合**（输入指标 `Pass¹×(1−幻觉率)÷单次成本` 的"成本"项；pi session jsonl 的 usage 未入行为库，需新埋点）/ 会话级环比（较上期对比）/ 弹窗两问+周访谈+种子群（提纲阶段⑤反馈三通道）

**指标体检遗留（2026-10-13 核查出，待排期）**：
1. 看板 DAU 命名/口径：`page_view` 挂载即发且默认视图=对话 → 实为"打开过去重"；修法二选一（改名，或 tracker 补显式 view 埋点）
2. 总 DAU / WAU 的"任意事件（含心跳）"语义含糊、彼此高重合；应改用有明确业务含义的事件集
3. 黏性窗口不一致（24h DAU ÷ 7d WAU）→ 定为"日均 DAU ÷ WAU"
4. 采纳率"沉默≠不采纳"偏差；👍 稀疏时不宜作独立比率
5. 人均结论 / 每人轮数 分母应限定"近7天有对话的用户"，而非 WAU（含只看看板者）
6. 轮时长幸存者偏差：abort 轮无 settled 不计（慢到放弃的被剔除）→ 应把 abort 轮纳入或独立计数
7. 用户身份=浏览器自报（清缓存重计）→ DAU/WAU/人均类本质是"浏览器数"；根治需登录（上云前鉴权清单）

## 八、测试数据过滤（2026-10-13 补）

**非标准会话判定**：会话级指标（交付结论/采纳/四象限）仅统计 `session_id` 为**标准 UUID**（36 位 8-4-4-4-12 小写十六进制）的行——真实 pi 会话 id 形态。开发期/遗留会话的 id 非 UUID（实测三类：把 userId 当会话 id 的 `usr_*`、旧复合格式 `2026-10-05T13-…_<uuid>`、手工造 `sess1`/`s1`），会被剔除，避免污染绝对量（交付结论数/人均结论）。

- 开关：`PRISM_OPS_EXCLUDE_TEST`（默认 `1` 开启；设 `0` 回到全量口径）
- 用户级指标（DAU/WAU/人均）无法从 `local_id` 区分真假用户（真实用户与开发浏览器同为 `usr_` 前缀）→ 提供 `PRISM_OPS_TEST_LOCAL_IDS`（逗号分隔，默认空）手动排除
- 透明项：stats 返回 `test_filter.excluded_sessions`，页脚角标展示"已剔除 N 个非标准会话"

**已移除的口径 —— 在线时长（2026-10-13）**：曾按 `active_tick`(30s 心跳) 计数 × 30s 展示"看板/对话在线时长"。核查发现两处硬伤：① 5 分钟空闲窗 + 仅 click/keydown/touchstart 重置 → 挂机也累计（实测单日 10.8h/3人），本质是"页面停留"非"有效使用"；② 分线依赖 `session_id` 有/无作代理，但 `setSessionContext` 从不重置（仅会话建立时设一次）→ 首次对话后所有心跳都算"对话在线"，分线失效。**已整体移除**，改用 WAU/黏性/每人轮数衡量使用深度（原始 `active_tick` 与 total_dau 的心跳仍保留）。

## 九、产品北极星真埋点（conclusion_emitted，2026-10-13）

**缺口**：产品北极星（上游定义"周成功交付结论数=被采纳未点踩的结论绝对量"）在埋点层**无对应事件**——events 表原 8 类事件里没有"结论产出"，`submit_conclusion` 的 CLAIM 只进 `trajectories.jsonl`。看板只能拿"settled 会话数"顶替，含 fail/闲聊/澄清轮，名不副实。

**补埋点**：前端在出口闸判定处上报新事件 [`conclusion_emitted`](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/ChatView.tsx#L367-L379)——
- 触发点：`submit_conclusion` 的 `tool_result`（[ChatView.tsx](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/ChatView.tsx#L367-L379)，与既有"过闸溯源条"同一判据）
- 取值：`value=ok`（CLAIM 通过出口闸=合格结论）/ `value=fail`（被拒）
- 落库：走既有 `POST /events`（无白名单，任意 `event_type` 直接入库），字段 `session_id/local_id/ts` 齐全
- 消费：「周成功交付结论数」= 近7天 `conclusion_emitted` value=ok 的会话去重（会话级归一，仅标准 UUID 会话）；「交付率」= 交付结论会话 ÷ 终轮会话

**接线验收**：受控插入一条 `conclusion_emitted(ok)` → stats `weekly_conclusions` 0→1 → 清理回 0（PASS）。

**边界**：埋点自 2026-10-13 起，**此前历史为 0**（非缺陷）；仅统计走出口闸的数字结论，闲聊/纯澄清轮不计（符合红线#7 语义）。

## 变更历史

- 2026-10-13 change 1「北极星看板与badcase四象限」十步归档：stats 扩展+trends+quadrant+主站第三视图+回放抽屉+badcases 台账；ts julianday 修复（旧口径 35→精确 32）
- 2026-10-13 change 2「北极星看板独立端口化」十步归档：prism-ops:8020 独立子服务+vanilla 单页；主站删净（main.py 1456→1146 行）；审查 P2×3 全修（文档路由/mtime 缓存/无界响应）
- 2026-10-13 D8 拍板：上云方案 A 落入上线方案 v1.3
- 2026-10-13 口径补全（第一轮）：补「在线时长」/「周结论数」改会话级终轮归一/加测试过滤/trends+quadrant 加 `days`/UI 时间范围切换器+四象限↔明细联动+会话列与预览清洗
- 2026-10-13 **指标体检与重构**：全量核查各指标真实含义，发现 3 根因（产品北极星缺埋点 / 看板 DAU 无视图 / 用户身份自报）+ 多条口径偏差（记 §七）；① 移除"在线时长"（§八）② 补 `conclusion_emitted` 埋点、落地真产品北极星"周成功交付结论数"（§九）③ 补 WAU/黏性/交付率/每人轮数④ KPI 改 4 聚合卡、图表加缩放平移（滚轮/拖拽/双击还原）
