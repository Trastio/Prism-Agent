# Prism-Agent · 对话 Agent 架构重构方案

> 2026-10-07
> 起因：用户"Prism 是一个对话 agent，棱镜理论是支撑点，用户也会闲聊，用不上棱镜理论"
> 性质：**改造方案**（v4 已收敛，审阅通过后施工）
> 审查方法：逐行读代码 + 前端组件 + 提示词层 + 验证层 + 工具层
> 修订 2026-10-07（v2）：新增「层 0 会话隔离（正统方案）」；新增 §二 问题 6/7；新增 §八 架构层审查总览；修订 §七「不做」。
> 修订 2026-10-07（v3）：按"汽车类分析/判断问题"口径细化棱镜两层（数据能力 / 分析框架）；修订 §一 口径、层 1 触发条件与关键词集；层 2 补"保留 URL 真值集门"；§七/§八 口径统一；验收可断言化。
> 修订 2026-10-07（v4）：问题 7 结论定为**彻底删除 memory.json**（读 + 写）——同会话延续由 pi session branch 承担；同步修订层 1、项 15、验收。

---

## 一、根因：架构理念错位

Prism 的整个 Harness 从提示词到验证层全是"汽车分析专用工具"的设计，但你要的是"通用对话 agent + 汽车分析能力"。

**棱镜理论应该是 agent 的可选能力（用户问汽车数据时才启用），不是默认身份（每轮都注入）。当前架构把"可选能力"当"默认身份"用了。**

**口径细化（2026-10-07 定，方案 A）**：棱镜分两层，不要混为一个词——

| 层 | 内容 | 何时启用 |
|---|---|---|
| **棱镜数据能力** | 配置 / 口碑 / 销量 / 舆情 四维取数（query_*） | 用户问**任何**汽车数据即启用（含"续航多少""何时上市"这类纯事实查询） |
| **棱镜分析框架** | 三维度交叉视角 + 报告纪律六条 + 口径 as_of + 不越界归因 + 缺口假设范式 | **仅当**用户提出**汽车类分析/判断问题**（针对 配置/口碑/销量/舆情 任一面做分析、对比、评估、归因）时启用 |

- **纯事实查询**（"银河E5续航多少"）只启用数据能力，**不注入分析框架**。
- **通用问题**（闲聊 / 旅游 / 行业政策）完全走通用能力，两者都不启用。
- **数据红线常驻**：`supported_by` / `as_of` / 不编造 / 对象核验——只要动用库数据即生效，**不挂在"分析框架"下**（否则纯查询会漏掉红线）。

**第二根因（更深）：没有"会话"这个一等实体。** 后端 `getOrCreateRpc(userId)` 把"用户=会话"——一个用户只有一个常驻会话；前端列表是文件、运行时 id 是 userId、`/chat` 根本不读 `session_id`、"新建会话"不真建会话。因此：上下文永不隔离（上一话题 + memory.json 一起污染下一轮）、会话历史点开空白、切换会话无效。**这是"乱回答/答非所问"与"没有历史"的共同地基。**

---

## 二、7 个结构性问题（代码实测）

### 问题 1：提示词每轮注入 2000 字汽车 SOP

**AGENTS.md**（每轮注入 prompt）：
- `<prism_dimensions>` 棱镜三维度——用户问"芜湖去哪玩"，agent 看到配置/口碑/销量维度词，上下文被汽车框架污染
- `<expected_behavior>` "收到分析请求 → 先 resolve_series → 三维度顺序查询"——告诉 agent 每次都走汽车分析流程
- `<discipline>` 报告纪律六条——全是汽车分析纪律（行 ID/as_of/越界/缺口）
- `<layered_rules>` "默认按 配置→口碑→销量 顺序推进"——强制汽车分析顺序

**SYSTEM.md**（每轮注入 prompt）：
- "当前会话上下文"对象块——即使 series 为空也注入"对象: 未指定"
- 纪律 5"每个数字带来源 supported_by 行 ID"——通用问题不需要

**影响**：agent 每轮被注入 ~2000 字汽车分析 SOP，即使用户问"芜湖去哪玩"。agent 自然把所有问题往汽车分析上靠。

### 问题 2：验证层只信任汽车网站

**verifyWeb host 白名单**（index.ts L459）：
```ts
const HOST_WHITELIST = ['autohome.com.cn', 'dongchedi.com', 'pcauto.com.cn', 'yiche.com', 'xcar.com.cn', ...]
```

用户问"芜湖去哪玩"→ agent 调 web_search 搜旅游攻略 → tier=web → verifyWeb 检查 host 白名单 → 旅游网站不在白名单 → 告警"来源 host 未验证"。

**影响**：验证层没有"通用问题"的正路径。只信任汽车网站，通用 web 来源被降级。

### 问题 3：series_key 跨轮污染

before_agent_start 每轮注入 SYSTEM.md 的 `{series_key}`。前几轮 series_key="银河E5"，后续轮次即使用户不提车系，SYSTEM.md 仍注入"对象: 银河E5"（前端一直传同一个 series_key）。

**影响**：通用问题继承汽车分析上下文。"芜湖去哪玩"的回复混入银河E5数据。

### 问题 4：工具每轮全开

`setActiveTools([...ALLOWED_TOOLS])` 每轮全开 24 业务工具 + web + ask_user。agent 看到 24 个汽车工具，自然倾向用汽车工具。

**影响**：工具描述全是汽车维度词，引导 agent 往汽车分析方向走。

### 问题 5：前端 UI 以车系为核心

| 位置 | 元素 | 问题 |
|---|---|---|
| 顶栏 | SeriesCombobox（车系选择器+蓝点） | 用户一进来就看到"选车系"——暗示必须先选 |
| 侧栏 | "车系" tab（搜索+最近车系+核验） | 侧栏一半空间给车系，与对话 agent 无关 |
| 状态栏 | "三维度：配置○ 口碑○ 销量○" | 闲聊时这行字毫无意义 |
| 状态栏 | "数据源就绪"蓝点 | 暗示数据源是核心 |

**影响**：UI 暗示"先选车系才能用"，与"打开就能对话"矛盾。

### 问题 6：没有"会话"实体——历史空白 + 切换无效 + 上下文永不隔离

**实测**：
- `pi_gateway.mjs` 只有 4 个路由：`/health`、`/chat`、`/session`(GET 列目录 / POST 新建)、`/ui-response`；**没有取历史消息的端点**（L472-519）。
- `/chat` 只读 `message/scope/user_id/series_key`，**完全忽略前端传的 `session_id`**（L381-L419）。
- RPC 是 `getOrCreateRpc(userId)`（L427）——一用户一常驻会话；`session_info` 返回的是 `userId`（L432），与列表返回的 `.jsonl` 文件名对不上。
- 前端 `ChatView` 的 `msgs` 纯内存，`sessionIdProp` 变化只 `setSessionId`，**从不加载历史**（ChatView.tsx L56/L67）。
- Sidebar "新建会话"只切视图不建会话；`/session/rename` 网关未实现（静默 404）。

**影响**：点会话全空白；切会话不是切上下文；跨话题污染（→"乱回答"）。**这是所有问题的地基。**

### 问题 7：memory.json 每轮注入，且与 session branch 冗余

- 存储为 **per-user**（`<.pi/sessions>/<userId>/memory.json`），写入在 `agent_settled`（index.ts L605-627，字段 series/question/conclusion/tier，5 条上限）；读取在 `before_agent_start` **每轮**注入，文案即「最近对话上下文（跨会话记忆）」（index.ts L778-L792）。
- **两条问题**：① 跨话题污染——把上一话题结论灌进下一轮（"答非所问"嫌疑源）；② **与 branch 冗余**——pi session branch 已保留同会话历史，模型能自行推断"那口碑呢"的指代，memory 在同一会话内只是重复注入。
- **结论：彻底删除**（读 + 写）。跨轮指代由 branch 承担；跨会话记忆本方案不做。
- **施工前须核实**：pi 是否对长会话 branch 做压缩/截断（若压缩，删除后同会话远期结论会丢；但 compaction 通常保留近期，影响有限）。

---

## 三、改造方案

### 层 0：会话层——会话隔离 + 历史加载（正统方案，最高优先级）

**依据**：pi RPC 原生已提供会话切换/读取能力，我们未接（`pi-windows-x64/docs/rpc.md`）：
- `switch_session {sessionPath}`：加载另一个会话文件，真正切换上下文（rpc.md L620-636）
- `get_messages`：取当前会话全部消息（rpc.md L217-219）
- `get_state`：返回 `sessionFile/sessionId/sessionName/messageCount`（rpc.md L184-215）
- `new_session`：新建会话（网关已在用）

**改为**：
1. `GET /session` 列表返回 `{id, sessionFile, name, lastActivity}`，**id 统一 = jsonl 文件名 basename**，与运行时 id 同源。
2. 新增 `POST /session/switch {user_id, session_id}` → `rpc.send('switch_session', {sessionPath})`。
3. 新增 `GET /session/messages?user_id=&session_id=` → 先 `switch_session`（或只读解析 jsonl）再 `get_messages`。
4. `/chat` 读 `parsed.session_id`：与当前 active 不一致 → 先 `switch_session`；`session_info` 返回**真实会话 id**（`get_state.sessionId`），不再返回 userId。
5. 前端 `ChatView`：`sessionIdProp` 变化 → fetch `/session/messages` 回填 `msgs`，并**先清空旧 msgs**；Sidebar "新建会话"改调 `POST /session`。
6. **安全硬约束**：`session_id` 必须白名单校验（只允许 `<.pi/sessions>/<user_id>/*.jsonl`），防路径穿越 / 越权读他人会话。

**施工前须核实**：
- `get_messages` 返回结构（role/content/toolCall 形态）→ 决定前端渲染映射。
- `ctx.json` 现为 **per-user** 而非 per-session（pi_gateway L413-419）：切会话后 `before_agent_start` 读到的 series_key 会错配到另一会话，需一并改为 per-session 或在 switch 时清空。
- `session_before_switch` 是否被扩展取消（当前 prism-guardrails 未注册，安全）。

**影响**：同时解决"历史空白""切会话无效""跨话题污染"三件事；是"层 3 series_key 轮次级"的前置容器（会话是隔离单位，series 是会话内对象）。

### 层 1：提示词层——分"通用层 + 汽车分析层"

**当前**：每轮全注入 AGENTS.md（汽车 SOP）+ SYSTEM.md（汽车角色+对象上下文）

**改为**：分两层（通用层常驻；汽车分析层按需，其内再分两个子层），按用户意图选注入：

**通用层（每轮注入）**：
- 角色："你是 Prism-Agent，一个面向汽车产品经理的助手。能做通用对话 + 联网搜索 + 汽车数据分析。"
- 全局红线：不编造 + injection 防护 + 护栏在执行层
- 通用纪律：结论先行 + 简洁 + Markdown

**汽车分析层（按需注入）**，再分两个子层（对应 §一 口径细化）：

- **数据能力子层（涉及汽车数据即注入）**：对象上下文（`as_of` / `warnings`；**series_key 不再注入固定值**——见层 3，由 agent 本轮 `resolve_series` 自持）+ 数据红线（supported_by / as_of / 不编造 / 对象核验）+ "汽车数据用 query_*"。
  - 触发：用户消息含车系名 / 维度词 / **分析词**（任一）。
- **分析框架子层（仅分析/判断问题注入）**：棱镜三维度 / 报告纪律六条 / 分层规则 / expected_behavior。
  - 触发：用户消息含**分析词**（见下），即针对 配置/口碑/销量/舆情 任一面做分析 / 对比 / 评估 / 归因。
  - 纯事实查询（"续航多少""什么时候上市"）**只注入数据能力子层，不注入分析框架子层**。

**实现**：before_agent_start 检测用户消息意图：
- 含**分析词** → 注入通用层 + 数据能力子层 + 分析框架子层
- 只含车系名 / 维度词（无分析词）→ 注入通用层 + 数据能力子层
- 都不含 → 只注入通用层

**时序约束（关键）**：before_agent_start 在本轮开始前触发，此时 agent 还没调工具——**触发条件只能基于用户消息内容**（关键词匹配），不能基于"agent 调了什么工具"（那是 agent_settled 时才知道的）。

- **提示词注入是 best-effort**——可能漏判（用户说"那辆车怎么样"没提车系名但意图是分析）或误判（用户说"舒适性是个主观概念"提了维度词但不是分析请求）
- **验证层兜底**——agent_settled 时 tier 路由按实际工具调用判定（library/web/mixed/none），与提示词注入层互补而非替代
- **关键词集**（修订）：车系名（从 series_alias 表拉常见 30 个 + LIKE 匹配）/ 维度词（舒适/动力/操控/外观/空间/内饰/安全/价格/智能/辅助驾驶/售后/油耗/续航/电耗/充电）/ **分析词**（销量/口碑/配置/对比/分析/报告/结论/环比/同比/市占率/零售/交付/**舆情/市场/表现/评价/怎么样/值不值/好不好/推荐**）
- **判定优先级**（修订）：**分析词为主**——命中分析词 → 注入"数据能力子层 + 分析框架子层"；**维度词单独命中 → 只注入"数据能力子层"**（不注入整套框架）；车系名单独命中 → 只注入数据能力子层。

**同时删除 memory.json**（问题 7）：写入（L605-627）与读取注入（L778-L792）一并移除——**同会话延续由 pi session branch 承担**，跨会话记忆本方案不做（避免每轮把上一话题结论灌入）。

### 层 2：验证层——通用 web 来源放行

**当前**：verifyWeb host 白名单全是汽车网站

**改为**：
- 通用 web 来源（非汽车网站）→ 放行（标注来源 URL + "不可复算"）
- 汽车数据关键词（销量/口碑/配置/零售/同比等）+ web 来源 → 降级告警"建议用 query_* 核验"
- host 白名单降级为"可信汽车来源"标记（非强制门禁）
- **保留 URL 真值集门**（verifyWeb 第一道门：URL 必须出现在本轮 web 工具实际返回内容中）——**只降级 host 白名单，真值集不动**（防编造 URL，红线 #1）

### 层 3：上下文层——series_key 轮次级

**当前**：series_key 会话级（前端一直传同一个值）

**改为**：
- series_key 轮次级——每轮由 agent 从用户消息识别（或前端不传，agent 自己判断）
- 前端不再传 series_key（删 chat.ts seriesKey + App.tsx series state 传 ChatView）
- agent 需要查汽车数据时，自己调 resolve_series

### 层 4：工具层——不收窄（保持全开）

**当前**：每轮全开 ALLOWED_TOOLS

**改为**：保持全开——agent 自己判断用哪些工具。工具描述引导"汽车数据用 query_*"（提示词层 best-effort）。不按意图收窄工具集（收窄会破坏一轮查数体验）。

### 层 5：前端 UI——删车系核心元素

**删**：
- 顶栏 SeriesCombobox（含蓝点）
- 侧栏"车系" tab（含搜索/最近车系/核验逻辑）
- 状态栏"三维度：配置○ 口碑○ 销量○"
- 状态栏"数据源就绪"蓝点

**留**：
- 顶栏 Logo + 品牌名
- 侧栏"会话" tab + 会话列表
- 侧栏"新建会话" / "棱镜工作台" / "SKILLS 库"
- 状态栏"Deepseek V4 Flash" + as_of

**改**：
- App.tsx 删 series state + SeriesCombobox + onSelectSeries + dimStatus
- Sidebar 删车系 tab + tab 切换逻辑（只留会话）
- ChatView 删 series prop（不再传 series_key）

---

## 四、改造清单

| # | 文件 | 改动 | 层 |
|---|---|---|---|
| 1 | AGENTS.md | 拆"通用层 + 汽车分析层"（通用每轮注入，汽车按需） | 提示词 |
| 2 | SYSTEM.md | 通用角色 + 汽车上下文按需注入 | 提示词 |
| 3 | index.ts before_agent_start | 检测用户意图 → 选注入哪层 | 提示词 |
| 4 | index.ts verifyWeb | 通用 web 放行 + 汽车数据降级（host 白名单降为标记；**保留 URL 真值集门**） | 验证层 |
| 5 | chat.ts | 删 seriesKey 传参 | 上下文 |
| 6 | App.tsx | 删 series state + SeriesCombobox + dimStatus | 前端 |
| 7 | Sidebar.tsx | 删车系 tab + tab 切换（只留会话） | 前端 |
| 8 | ChatView.tsx | 删 series prop | 前端 |
| 9 | App.tsx 状态栏 | 删三维度 + 数据源蓝点 | 前端 |
| 10 | pi_gateway.mjs | 删 series_key 透传 + ctx.json series_key | 上下文 |
| 11 | pi_gateway.mjs | 会话列表补 sessionFile；新增 `/session/switch`、`/session/messages`；`/chat` 读 session_id；`session_info` 返真实 id | 会话 |
| 12 | pi_gateway.mjs | session_id 白名单校验（防路径穿越 / 越权） | 会话 |
| 13 | pi_gateway.mjs | ctx.json 由 per-user 改 per-session（或在 switch 时清空） | 会话 |
| 14 | Sidebar.tsx | "新建会话"改调 POST /session；会话 id 与运行时统一 | 会话 |
| 15 | index.ts | **彻底删除 memory.json**：写入（L605-627）+ 读取注入（L778-L792） | 提示词 |

---

## 五、改后行为

| 用户消息 | 提示词注入 | 工具 | 验证 |
|---|---|---|---|
| "你好" | 通用层 | 无 | none 放行 |
| "芜湖去哪玩" | 通用层 | web_search | web 放行（通用来源） |
| "银河E5销量" | 通用层 + 汽车分析层（两子层） | resolve_series → query_sales | library 严格 |
| "银河E5续航多少" | 通用层 + 数据能力子层（不含分析框架） | resolve_series → query_config | library 严格 |
| "银河E5口碑怎么样" | 通用层 + 数据能力子层 + 分析框架子层 | resolve_series → query_reviews | library 严格 |
| "帮我查行业政策" | 通用层 | web_search | web 放行 |
| "银河E5和海豚对比" | 通用层 + 汽车分析层（两子层） | resolve_series × 2 → query_* | library 严格 |
| （点击某会话） | — | — | 加载该会话历史 + `switch_session` 切换上下文 |
| （新建会话） | 通用层 | 无 | `new_session` 建新会话，上下文隔离 |

---

## 六、验收

1. 顶栏无 SeriesCombobox / 蓝点
2. 侧栏无"车系" tab（只有"会话"）
3. 状态栏无三维度 / 数据源蓝点
4. "你好" → 闲聊；**断言本轮注入的 systemPrompt 不含 `<prism_dimensions>` / `<discipline>` / `<expected_behavior>`**
5. "芜湖去哪玩" → web_search（通用来源放行，不告警）
6. "银河E5销量" → resolve_series + query_sales（注入数据能力子层 + 分析框架子层）
7. 前端不传 series_key（agent 自己识别）
8. smoke:all 全过
9. 点击会话 → 显示该会话历史（非空白）
10. 切会话 → 后端上下文随 `switch_session` 真正切换（跨话题不串）
11. "新建会话" → 真建会话（POST /session 返回新 id）
12. session_id 越权 / 路径穿越被拒
13. "银河E5续航多少" → 只注入数据能力子层（systemPrompt 不含 `<discipline>`）；"银河E5口碑怎么样" → 注入分析框架子层（含 `<discipline>`）
14. memory.json 不再写入（`.pi/sessions/<userId>/memory.json` 不再生成）；systemPrompt 不含「最近对话上下文（跨会话记忆）」

---

## 七、不做

- 工具收窄（保持全开）
- ~~session 上下文隔离（pi 原生会话延续，不强制清上下文）~~ → **已移入 §三 层 0（正统方案）**：改用 pi RPC `switch_session` 做真正的会话隔离，不再"一个用户一个常驻会话"
- export_document（独立 change）
- subagent / mem0 / mcp-adapter

---

## 八、架构层 / Harness 层审查总览

以上问题不是零散 bug，而是同几处结构债务的外显：

| 层 | 债务 | 严重度 | 代表问题 |
|---|---|---|---|
| 会话模型层 | 没有"会话"一等实体（用户=会话） | 严重 | 问题 6；历史空白；切会话无效；跨话题污染 |
| 提示词/上下文层 | 业务焊死在身份上（每轮全量注入 + memory 注入） | 严重 | 问题 1、3、7 |
| 验证层 | 与业务强耦合：过严（只信汽车站）与过松（none 旁路）并存 | 中-严重 | 问题 2；mixed tier 反复打回（烧 token / 进上下文再污染） |
| 工具层 | 未分层，24 工具每轮全开 | 中 | 问题 4 |
| 前端交互层 | 与"对话 Agent"定位错位 | 中 | 问题 5；会话列表不可用 |
| 进程/运维层 | 一用户一进程、无池上限；事件契约语义错（session_info 返 userId）；/session/rename 未实现 | 低-中 | 问题 6 |

**一句话总括**：Prism 的 Harness 是为"汽车分析专家"造的，而产品要的是"能闲聊、按需用棱镜的对话 Agent"；其中"没有会话实体"是最底层地基——它同时是"历史空白""切会话无效""乱回答"的共同根因。

**建议施工顺序**：
1. **P0** 会话模型（§三 层 0 正统方案）——同时解决历史空白与跨话题污染。
2. **P0** 提示词分层 + **删除 memory.json**（问题 7；层 1 触发判据基于用户消息关键词——before_agent_start 时 agent 还没调工具，只能用关键词 best-effort + agent_settled tier 路由兜底）。
3. **P1** 验证层通用放行（层 2；同时审查 `BUSINESS_KW_RE` 关键词误判）。
4. **P1** 前端去车系核心元素（层 5）。
5. **P2** 进程治理（进程池上限 / 超时）；工具层仅做"描述引导"（**不做收窄**，见 §七）。

---

## 九、收敛状态（2026-10-07 审计）

**结论：已收敛**——口径无冲突、引用无悬空、编号连续、待办可枚举。

**一致性检查**：
- 编号连续：问题 1-7 / 层 0-5 / 清单 1-15 / 验收 1-14。
- 术语统一：汽车分析层 = 数据能力子层 + 分析框架子层；"汽车分析层"仅作伞形称呼。
- 冲突已消：§七"不做工具收窄" ≡ §八 P2；层 1 对象上下文不再注入 series_key（与层 3/清单 10 一致）；层 2 与清单 4 均含"保留 URL 真值集门"。

**待核实（施工前必查，4 项）**：
1. `get_messages` 返回结构（决定前端渲染映射）。
2. `ctx.json` per-user → per-session（否则切会话时 series / as_of 错配）。
3. `session_before_switch` 是否被扩展取消。
4. pi 是否对长会话 branch 做压缩 / 截断（关系 memory.json 删除后同会话远期结论是否丢失）。

**待决策（本方案内 0 项）**：进程治理细节（进程池上限 / 超时时长）留待 P2 独立定。
