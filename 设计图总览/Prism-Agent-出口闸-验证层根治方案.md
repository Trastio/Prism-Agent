# Prism-Agent · 出口闸（submit_conclusion）——验证层根治方案

> 日期：2026-10-07 · v1.5（D1-D6 已拍板；v1.2→v1.5 四轮审核收敛，见修订记录）
> 性质：**方案文档，未施工**。审阅通过后按十步流程走（explore → propose → 3.5 自查 → Step5-10）。
> 起因：前端两大症状——**回答变慢/收不到回复** + **回答无关消息（验收整改体）**。
> 前置文档：《Prism-Agent-回答变慢根因治理方案》（设计图总览/）、《Prism-Agent-验证器回灌误判-审查报告与解决方案-2026-10-07》（文档/）。
> 本方案定位：上述两文档的**根治继任者**——其止血项（已落地部分）保留，其治标倾向在此纠正。
> v1.2 变更：①**上游工具层（G5）并入**（决策 D6），以 §十 线 C 承载；②修正轨迹行号口径（#56-58）；③补 L1 保底漏洞（tier=none 编造漏网），并**防其反噬**（② 分支绑定"数字不在台账"判定，避免复述被误伤）；④补 submit_conclusion 的 tier 归属；⑤校正 E/N 对应关系与单测口径；⑥修正悬空引用。
> v1.4 变更：①**台账回写改分信任级**（P-a）——derived 只记 `declared-derived` 弱信任项，不并入真值集、不得作次级 derived 源，堵住"洗白跨轮固化"；②**台账排除标识符数字**（P-b）；③N8 单测数 **32→36** 校正；④新增 **E9** 防洗白链用例（E1-E8 升为 E1-E9）；⑤运维项引用与错误码口径校正。

---

## 〇、摘要

一句话：**把"完成验证"从"事后用正则检查散文、失败后注入用户消息让模型重答"改造为"结论必须通过 `submit_conclusion` 工具提交、验证失败以工具结果返回、模型同轮内修正"——即出口闸协议。散文退出**主验证对象**（仅保留一道"数字形态"保底扫描，判据从"像不像分析"换成"数字有没有出处"），闲聊误判从"复述与编造一起拦"收敛为"只拦编造"，回灌从"重跑一个 agent"降为"再调一次工具"。**

三个支点：
1. **出口闸**（治验证层之本）：模型可提出完成，不能批准自己的完成——验证执法从散文移到结构化提交。
2. **会话状态台账**（治状态层之本）：series_key / attempt / 同因签名 / verdict 全部落 session entry，消除"易失文件 + 命名约定"家族缺陷。
3. **评估回归门**（治防复发之本）：本次全部症状转评估用例，任何修复效果可断言、可回归。

**v1.2 追加第四个支点**：
4. **工具层可用性与失败语义**（治上游之本，决策 D6 并入）：业务工具大面积不可用（实测 50% 轨迹含工具错误）迫使模型绕路（`bash` 成调用第一工具），绕路产物污染上下文并喂养 G1/G3。**不修上游，出口闸只是让污染"不被检出"，而非不被产生**——故并入本 change，以 §十 线 C 承载。

---

## 一、根因结论（为什么现行架构必然复发）

### 1.1 四层根因

| # | 根因 | 层 | 表现 |
|---|---|---|---|
| G1 | **代理指标验证器**：用"有行 ID"代理"没编造"、用"数字+维度词"代理"是分析"，事后正则扫散文 | 验证层 | 闲聊复述真数字被判 fail（10-04 修过一次，10-07 复发） |
| G2 | **会话状态无单一事实源**：状态散落易失文件/进程内存/命名约定 | 架构 | verdict 路径错位、ctx 首轮丢失、回灌轮身份被空值覆盖、attemptMap 重启即丢 |
| G3 | **上下文工程纪律缺失**：工具结果全量入库、失败轮残留 | 上下文层 | 越聊越慢 **且** 历史数字堆积 → 误判窗口变大（两症状在此合流） |
| G4 | **回灌代价错配**：每次回灌 = 完整 agent 重跑；验证意见以 user 消息注入 | 编排层 | 模型对"验收意见"作答 = 答非所问；三连环回灌 = 单轮耗时 ×3 |
| **G5** | **上游工具层大面积不可用 + 失败无语义**：业务工具报错静默、失败以裸 HTTP 码直返，模型无法"如实报告缺失"，只能绕路 | **工具层** | 实测 50% 轨迹含工具错误；`bash` 成调用第一工具；绕路产物（端口探测/源码片段/目录列表）入上下文 → **喂养 G3，并制造 G1 的误判素材**（v1.2 并入，治本层） |

### 1.2 关键史实（本次排查实锤）

- **`submit_conclusion` 出口闸在 2026-09-16 施工图里已设计、代码从未实现**（`文档/Prism-Agent-pi改造研究.md:111`："最终交付走 submit_conclusion 工具……不一致则 block 并要求修正。模型可以提出完成，不能批准自己的完成"；grep 当前 **extension/verify 内无实现**（全仓另有 `文档/Prism-Agent-pi改造研究.md` 与 `设计图总览/设计图核心/Prism-Agent-运行架构.html` 两处**设计性提及**，均非实现；v1.2 校正原"全仓无"表述））。现行"事后验证 + user 消息回灌"是在被放弃的地基上打补丁。
- **P1-a（数字溯源）按其自身规则治不了它的触发案例**：案发回复"4,436 辆（环比 −14.1%）"中，`4,436` 可溯源，`−14.1%` 是模型派生计算、任何工具从未返回——按"全部数字可溯源才放行"仍 fail、仍回灌。给派生数字开洞（容差/白名单）= 下一轮误判入口。**代理指标打补丁的死循环，证明该路径不可收敛。**
- **事发轨迹**（trajectories **#56-58**，2026-10-07 10:38-10:44，1-based；v1.2 校正口径）：三连回灌、三种失败原因接力（缺行ID → 未核验身份 → 缺行ID+越界），工具累计 **53→58→58**；**#56 含 bash×36**（#57/#58 为 bash×37）。旧进程 EXCLUDE_TOOLS 未生效为运维前置项。
  - 校正说明：#53 实测为 `pass / 闲聊放行 / toolCalls=0`，非事发行；#54-#55 为同簇更早的两条 fail。故"三连回灌 + 53→58→58"精确落在 **#56/#57/#58**。
- **上游工具层实测（v1.2 新增、v1.3 校正、v1.4 标口径，60 条轨迹全量统计）**：含工具错误的轨迹 **30/60（50%）**；错误码 `502`×105、`404`×18、`504`×8、`422`×7、`400`×9（**口径=`conversation` 全文字段；若按 `toolResult` 段落匹配则为 502×100 / 400×7**，详见附录口径说明）；**`bash` 调用 110 次为全工具第一**（`query_sales` 78 次居次）。错误构成分解（v1.3 逐条复核）：
  - ① **Atuohome :8001 未启动/不可达 → `/autohome` 反代返 502×105（环境项，错误主因；`main.py` 明写 502='Atuohome 服务不可达'）**；
  - ② **sentiment_events 一处路径错（代码项）**：工具模板 `/top-events/{vehicle_id}`，服务真实路由为 **router 内相对路径 `/vehicles/{vehicle_id}/events`**（含 prefix 的完整路径 = `/api/dashboard/vehicles/{vehicle_id}/events`；dashboard.py:1399）。⚠️ **施工时须填相对路径**——extension 已拼 `/api/dashboard` 前缀（index.ts:214），若照抄完整路径会变成 `/api/dashboard/api/dashboard/...` 双前缀（v1.4 提示）。**v1.3 证伪 v1.2 的"6 工具错配"**：逐条对照 dashboard.py 全部 21 条路由，其余 5 个舆情工具（overview/trend/dim-sentiment/top-posts/competitor-comparison）路径全部正确——v1.2 系误读 OpenAPI 全局前缀 `/api/vehicles` 所致；
  - ③ **`get_sales_detail` 参数语义歧义（代码项）**：模型误传 `model_id`，上游要 `series` → HTTP 400；
  - ④ **失败裸抛 HTTP 码（设计项）**：模型无法"如实报告缺失"。
  - **关键区分**：旧进程（运维项）是"bash **可用**"的原因；**工具报错 + 无失败语义才是"模型想用 bash"的原因**。环境项与代码项必须分别治。

### 1.3 症状 → 根因映射

| 症状 | 直接原因 | 根因归属 |
|---|---|---|
| 收不到回复（曾） | 系统代理劫持 8002 | 已修（trust_env=False） |
| 闲聊被答成"验收整改" | 判据误判 → user 消息回灌 | G1 + G4 |
| 单轮数十秒 | 回灌 ×2~3 + 串行工具循环 | G4 + G3 |
| 越聊越慢 | 上下文只增不减 | G3 |
| 挂死到超时（潜伏） | verdict 读写路径错位 → 网关误判 can_continue | G2 |
| 长会话闲聊高概率误判 | 历史数字堆积 | G3 喂养 G1 |
| **身份跑偏**（自称 "coding agent"） | 工具不可用 → 绕路读源码 / 探端口 → 上下文混入工程细节 | **G5**（v1.2） |
| **绕路使上下文加速膨胀** | 绕路产物（端口探测、源码片段、目录列表）全量入上下文 | **G5 → G3**（v1.2） |
| **答不出业务（潜伏）** | 业务工具恒错 → 模型无数据可用 | **G5**（v1.2） |

---

## 二、方案总览：核心转变

| 维度 | 现行（事后验证） | 出口闸（提交协议） |
|---|---|---|
| 验证对象 | 最终回复散文（正则抽取 CLAIM，脆） | `submit_conclusion` 结构化提交（可精确查库） |
| 验证时机 | agent_settled 之后 | 工具 execute 内（settle 之前） |
| 失败分发 | 注入 user 消息（模型当用户说话） | **tool_result 返回**（模型天然视为工具反馈） |
| 修正代价 | 重跑完整 agent（工具全重来） | 同一轮内再调一次工具 |
| 闲聊复述数字 | 被执法 → 误判 | 不进出口闸；保底按"数字是否在台账"判定 → **复述放行、仅编造被拦**（v1.2 校正原"整类消失"表述） |
| 派生数字（环比/同比） | 无处安放（P1-a 死穴） | 提交时声明 derived + 源数字验证 |
| agent_settled 职责 | 全量验证 + 回灌 | **保底检查**（该提交没提交才拦） |
| 回灌频率 | 频繁（判据误判驱动） | 趋近于零（只剩漏提交一种场景） |

---

## 三、出口闸设计（核心）

### 3.1 `submit_conclusion` 工具契约

注册为业务工具（进 TOOL_CATEGORIES.business 白名单），参数（TypeBox）：

```
conclusion_text      : string   结论一句话（先结论后依据）
supported_by         : string[] 行 ID，格式沿用现行 REF_RE（table:key/value/...）
as_of                : string   数据时点
scope                : '口碑内'|'配置内'|'市场侧不归因'|'跨维度'
data_gaps_declared   : string[] 数据缺口声明
numbers              : Array<{
                       value: string          归一化裸数值（去千分位/去单位）
                       source: 'tool' | 'derived'
                       derived_from?: string[]  source=derived 时必填，引用的源数字（须在台账内）
                     }>
```

**execute 内服务端验证（执行层执法，符合红线#5——不靠提示词自检）**，复用既有件：

1. 四件套：行 ID 查库 / as_of / 越界（NEG_RE 逐词判定）/ 缺口声明 —— 直接调 `verifyCompletion`（不改其内部逻辑）。
2. 数字台账比对：`source=tool` 的 value ∈ 会话数字真值集；`source=derived` 的每个 `derived_from` 源 ∈ 真值集。
3. 名称校验：`verifyNames(text, truthNames)`（真值集来自 prism-name-truth entry，现行逻辑）。
4. 通过 → `appendEntry('prism-conclusion-verified', {...})`，返回 pass 文本。
5. 拒绝 → 返回 `[出口闸] 拒绝：- 失败项清单… 请修正后重新提交`（**普通工具结果文本**，限长 ~2KB）。v1 不验 derived 算式正确性（源数字真实性已保证，算式错误属语义质量问题，交人工抽检/后续 judge）。

**tier 判定归属（v1.2 补充）**：`submit_conclusion` 须计入 library 判据。现行 `decideTier` 以 `calledTools.some(t => t.startsWith('query_'))` 认库工具（index.ts:51），`submit_conclusion` **不匹配该前缀**——若不同步扩展，"只调提交、未调 query_*"的轮次会被误判为 `tier=none`，出口闸结果无法进入 verdict。改法：加入 `TOOL_CATEGORIES.business` 的同时，在 `hasLib` 判据中**显式包含 `submit_conclusion`**（保留原有 `query_` 前缀判据，仅追加，不移除）。

### 3.2 数字台账

- `tool_result` hook 扩展（现行 collectNameTruth 范式）：抽取数字 token、归一化（去千分位逗号/去单位/统一裸数值）、去重，`appendEntry('prism-numeric-truth', {...})`。
- **采集范围（v1.3 修正一）**：覆盖 **TOOL_CATEGORIES.business 全部数据工具**（query_* + Atuohome + 舆情），非仅 query_*——否则模型复述 `get_sales_detail`/`search_cars`/舆情工具来源的数字时不在台账，被保底②误拦。
- **标识符排除（v1.4 修正三）**：归一化时**排除标识符类数字**——`series_id` / `spec_id` / `model_id` / `post_id` / `vehicle_id` 等 ID 字段一律不入台账。理由：它们是**标识符**而非**度量值**，混入会（a）使台账无谓膨胀、（b）造成"模型随口说个 7650 也算可溯源"的误放行。
- **错误载荷排除（v1.5 修正）**：`isError=true` 的工具返回 / C3 的 `unavailable` 结构化载荷**不入台账**——否则错误文本里的数字（"HTTP 502"、"返回 400"）会进真值集，"502 辆"变成"可溯源"。与 C3 同批对齐（C3 改变失败返回形态，正好一并处理）。
- **提交回写·分信任级（v1.3 修正二 → v1.4 再修正）**：submission pass 后回写台账，但**必须按 `source` 分级**：
  - `source=tool` 的数字 → **并入真值集**（直接来自工具返回，是真值）；
  - `source=derived` 的数字 → 只记为 **`declared-derived` 弱信任项**，**仅供"复述放行"判定使用；不并入真值集，且不得作为后续 `derived_from` 的源**。
  - **理由（P-a，v1.4 核心修正）**：v1.3 的"含 derived 一并并入台账"会把 derived 的洗白效果**跨轮固化**——模型只需成功提交一次"同比 −99%"（`derived_from` 源数字在台账内、算式按 D1 不验），该假值即**永久**获得"可溯源"身份。分级后：**复述仍放行**（堵住 v1.3 想堵的漏），但**派生数字无法为下一个派生数字背书**（堵住 v1.3 新开的口）。
- 只存归一化裸数值集合（不存原文），控制体积。
- **P1-a 的归位**：数字溯源不再是主门禁，而是出口闸的一环 + agent_settled 保底判据的观测辅助。其"全部可溯源才放行"的严格性在结构化提交场景正好合适（散文里的数字不再被它扫）。

### 3.3 验证失败的分发（与现行回灌的本质区别）

- 拒绝理由作为 tool_result 回到模型 → 模型在同一 turn 内读反馈、修正、重新提交（工具循环继续）。
- 不注入 user 消息 → 不消耗用户轮次 → 模型不会把验收意见当用户话 → **"答非所问"结构性消失**。
- 网关不需要"fail 不 break 继续读"特殊逻辑（pi_gateway.mjs:467-475 现行分支随本方案简化）。

### 3.4 `agent_settled` 改道（变薄）+ 保底

新职责（替换现行 G1 全量验证路径）：

1. 本轮 branch 含通过的 `prism-conclusion-verified` entry → verdict=pass（写 entry + verdict.json + trajectory，现行落盘件全沿用）。
2. **保底拦截（唯一剩余回灌场景）**：散文命中数字结论形态（`NUMERIC_CLAIM_RE` 降级到只干这件事）+ 本轮无通过提交 + **满足下列任一** → 拦截：
   - **① 漏提交**：`tier=library`（本轮调过库工具）→ 做了库数据分析却未走出口闸；
   - **② 凭空编造**：`tier=none`（本轮未调工具）**且回复中的数字不在 ② 判定集内** → 无任何工具返回过该数字。**② 判定集 = 真值集 ∪ `declared-derived` 弱信任项（v1.5 显式定义**——若窄读为仅真值集，复述已验证派生数字会被误拦，与 E9 第二半句自相矛盾）。多数字口径：**任一数字不可溯源即拦**（与 E4 同口径，fail-closed）。

   **v1.2 修正（L1 漏洞 + 防反噬）**：原条件仅 `tier=library`，会使 ② 漏网（不调工具、不提交、直接给数时 tier=none，红线#1 在该格失守）；但**简单去掉 tier 限定会反向误伤**——截图案发场景正是"闲聊复述本会话已核验的真数字"（tier=none 且数字在台账内），若 ② 不带"数字不在台账"判定，原事故将原样重现。故 ② 必须绑定台账判定：**复述（在台账）放行，编造（不在台账）拦截**。

   回灌机制（appendCustomMessageEntry + isVerifierRetryTurn + 同因截断 + 上限）全部保留为此保底服务。
3. tier=web / mixed：**维持现行逻辑不变**（URL 真值集 + 降级告警），本 change 不动（见 §七）。
4. tier=none（纯闲聊 / 复述）：命中数字结论形态者走第 2 条 **②**（数字在台账内 → 放行 = 复述；不在 → 拦截 = 编造）；未命中数字形态者直接 pass。**现行"数字+维度词"粗筛退役**——判据从"像不像分析"换成"数字有没有出处"，不再猜意图。

### 3.5 提示词配套（教协议，不执法）

- AGENTS.md `<discipline>` 加一条：结论交付必须走 `submit_conclusion` 提交 CLAIM；正文散文是展示层。
- SYSTEM.md 作答纪律第 5 条改写：数字来源由出口闸验证；报告类交付在提交的 CLAIM 中带 supported_by（用户可见的可复算性不变）。
- PRISM_ANALYSIS.md：CLAIM 结构示例改为工具调用形态。

---

## 四、会话状态台账（治雷 1 / 雷 2 / attemptMap 家族）

原则：**跨轮持久的语义状态一律落 session entry（pi 官方持久化），临时传参才走文件。**

| 状态 | 现行 | 改为 |
|---|---|---|
| series_key | ctx.json 读后即删 + prism-session-series-key 被空值覆盖 | entry **只 append 非空值**；读取取最新非空（修雷 2 的回灌轮覆盖）；ctx.json 保留为轮次传参通道，读后转 entry 再删 |
| ctx 首轮错位 | 前端首轮 session_id=null → 写 default.ctx.json → extension 读不到 | 网关把 ctx 写入挪到 `get_state` 之后（pi_gateway.mjs:449 已先拿 realSessionId），用 `<realSessionId>.ctx.json` 做 key——首轮必中 |
| attempt / 同因签名 | 进程内存 Map（重启丢、多进程不共享） | `prism-verifier-state` entry |
| verdict 送达网关 | extension 写 `<pi sessionId>/verdict.json`，网关从无字段的 agent_settled 事件里取不存在的 sessionId → 永远 fallback 全局 last-verdict.json（跨会话串读 + 竞态） | 网关在 /chat 内把已持有的 **realSessionId 传给 mapEvent**，读 `<realSessionId>/verdict.json`（修雷 1，两行级改动）；last-verdict.json 保留为兼容兜底并标注 sunset |

---

## 五、止血项并入（显式 sunset，防活成永久补丁）

| 止血项 | 状态 | 本 change 处置 |
|---|---|---|
| 旧进程重启验证（EXCLUDE_TOOLS 生效） | 运维 | **施工前置检查**：/health 的 startedAt vs 代码 mtime；`ls`/`bash` 不再出现在闲聊轨迹 |
| **上游服务启动（Atuohome :8001 / 舆情 :8000）** | 运维 | **v1.3 新增前置**：502×105 主因即 8001 未启动；服务不启动则线 C 验收无意义 |
| **sentiment_events 路径错（`/top-events` 不存在）** | 未做·代码缺陷 | **v1.3 缩范围**：仅此 1 处（其余 5 个舆情工具路径经逐条对照正确），改路径见 §十 线 C |
| **`get_sales_detail` 参数语义歧义** | **未做·代码缺陷** | **v1.2 并入（D6）**：明确入参为车系名 `series`，schema 描述与 `AUTOHOME_TOOL_MAP` 对齐，见 §十 线 C |
| **工具失败无语义（裸抛 HTTP 码）** | **未做·设计缺陷** | **v1.2 并入（D6）**：失败统一返回结构化 `unavailable` 状态，使模型能走红线#4"如实报缺"话术，见 §十 线 C |
| P1-b 回灌文案语义化 | 未做 | 随保底路径一起改（文案标注"系统校验通知，直接输出修正后的答复"）；保底频率趋零后此文案几乎不出场 |
| verdict 路径 / ctx 覆盖 | 未做 | 由 §四台账**治本**（不是接管道，是换载体） |
| P1-a 数字溯源 | 未做 | 降级为出口闸组件 + 保底观测（§3.2），不做散文主门禁 |

---

## 六、防复发：评估回归门

- 新增评估用例（进 eval/，runner 已具备读 trajectories verdict 能力）：
  - E1 长会话（≥5 轮含数字，**且至少含一轮派生数字结论 + 一轮非 query_* 工具来源的数字**，v1.3 补强覆盖台账扩采与回写）问"你好，你是谁" → settled=1、无回灌、无整改体（原 V1）
  - E2 结论含派生数字（环比）+ derived 声明 → submission pass（−14.1% 案例固化）
  - E3 编造数字提交 → 出口闸拒绝 → 同轮修正后 pass（原 V3）
  - E4 部分数字不可溯源 → 拒绝（原 V4）
  - E5 库数据分析 + 数字结论 + 未提交 → 保底拦截（新）
  - E6 多次被拒后放弃/换路 → 同因截断 + 上限生效（新）
  - **E7**（v1.2，治 G5）上游工具不可用（舆情 down / `get_sales_detail` 参数错）→ 模型**报告能力缺失**，不绕路（断言：该轮 `bash` 调用数 = 0）
  - **E8**（v1.2，补 L1 漏洞）`tier=none` + **凭空编造数字（不在台账）** + 未提交 → 保底拦截生效；**必须与 E1 同批通过**（E1 验"复述放行"、E8 验"编造拦截"，二者是同一判据的两侧）
  - **E9**（v1.4，防洗白链）derived 数字提交 pass 后，**再基于该 derived 数字构造下一级 derived 提交** → 出口闸**拒绝**（`declared-derived` 不得作为 `derived_from` 源）；同时该 derived 数字**被复述**（非提交）时仍由保底②放行——验证"分级回写"两侧都对
- appendTrajectory 增加 submission 字段（提交次数/最终 pass），供 runner 断言。
- ci.sh 门禁跑 **E1-E9**；**不绿不合档**。
- 元规则：今后任何验证层改动必须先在评估集上拿到前后对照（治"10-04 修复无法证明不复发"的元缺陷）。

---

## 七、不做清单（边界）

1. 不动 `verifyCompletion` 四件套内部逻辑（出口闸复用它）。
2. 不动 web/mixed tier 验证（URL 真值集 + 降级告警维持）；出口闸是否扩展到 web tier，观察一个版本后再定。
3. 不删回灌机制（降级为保底，见 §3.4）。
4. 工具结果截断/旁路（G3 的另一半）——**独立 change、与出口闸并行推进**（D5 已拍板：要做，不排后），不并入本 change 以控制单 change 体积，见 §十 线 B。
5. 不改 pi 网关进程模型（一用户一进程 + 池治理维持）。
6. 不引入 LLM-as-Judge 判闲聊（可复算判据已够；judge 留在评估侧）。
7. **不改上游服务的部署与启动方式**（线 C 只修工具侧的路径模板、参数语义与失败返回；不动 :8000 舆情服务 / :8001 Atuohome 的进程与部署）。

---

## 八、验收标准（可断言）

| # | 场景 | 期望 |
|---|---|---|
| N1 | 长会话闲聊"你是谁" | settled=1，无回灌，回复为正常自介 |
| N2 | 派生数字结论（环比 −14.1% 型）+ derived 声明 | submission pass，无回灌 |
| N3 | 编造数字提交 | 出口闸 tool_result 拒绝 → 同轮修正 → pass；全程无 user 消息注入 |
| N4 | 库数据分析 + 数字结论 + 未提交 | 保底拦截（唯一回灌场景），文案为语义化系统通知 |
| N5 | settled 事件 verdict | 网关读到的 verdict 与 extension 写入一致率 100%（雷 1 消除）；无 last-verdict.json 跨会话串读 |
| N6 | 首轮带 series_key 新会话 | ctx 首轮即中，身份不丢；回灌轮 series_key 不被空值覆盖（雷 2 消除） |
| N7 | 评估门 **E1-E9** | ci.sh 全绿 |
| N8 | 既有 16 题 + 单测（v1.4 复核 **36**：completion 3 + grounding 12 + tool_call 17 + **identity_api 4**；**v1.3 记"32"有误**——`tests/identity_api.test.ts` 文件仍存在且 `package.json` 的 `smoke:verify` 仍引用它，未删） | smoke:all 全过（不回归）；**若确需删除该文件，须同步移除 `package.json` 引用**，否则 `smoke:verify` 直接失败 |
| N9 | 网关重启后同会话续聊 | attempt/同因签名从 entry 恢复（台账持久性） |
| **N10** | **上游工具层（v1.2，治 G5；v1.3 缩正口径）** | 服务启动前提下舆情 6 工具全部可用（含 sentiment_events 路径修复）；工具失败返回结构化 `unavailable` 而非裸 HTTP 码；含工具错误的轨迹占比显著下降；非必要 `bash` 绕路归零（E7 断言） |

---

## 九、风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| 模型不调 submit_conclusion（"漏提交"，抢答的镜像） | 中 | agent_settled 保底拦截（§3.4）+ 提示词教协议 + E5 评估用例 |
| derived 声明被滥用来洗编造数字 | 中 | derived_from 源数字必须全部在台账；算式 v1 不验但进人工抽检；**v1.4 加固**：derived 回写为 `declared-derived` 弱信任项，不并入真值集、不得作为次级 derived 的源（断洗白链，见 §3.2） |
| **标识符数字混入台账（v1.4，P-b）** | 中 | 归一化排除 `series_id`/`spec_id`/`model_id`/`post_id`/`vehicle_id` 等 ID 字段，只采度量类数字（见 §3.2） |
| 多次提交/部分提交 | 低 | 最后一次通过提交为准；提交次数 >3 写 verdict 告警字段 |
| 旧会话兼容（无 submission 的恢复会话） | 低 | 走保底路径，行为等同现行 |
| 数字归一化漏形态（万/亿换算等） | 中 | 归一化规则进单测；漏掉的形态表现为"拒绝"而非"放行"（fail-closed 方向，红线#1 不被削弱） |
| 保底 ② 分支误伤闲聊复述（v1.2，L1 修正的反噬风险） | 中 | ② 分支**必须**带"数字不在台账"判定：复述已核验数字（截图场景）放行、凭空编造拦截；**E1 与 E8 必须同批通过**（同一判据两侧，只过一侧即视为该修正失败） |
| 数字台账缺失导致 ② 误判 | 中 | 采集范围=全部业务数据工具 + submission pass 回写（§3.2 v1.3 两项修正）；② 多数字口径=任一不可溯源即拦；台账抽取与截断（线 B）/失败语义化（C3）的时序在 explore 对齐并加用例 |
| 线 C 与线 A/B 并行导致交割冲突（v1.2） | 中 | 线 C 只改工具**路径 / 参数 schema / 失败返回**，不碰出口闸与 agent_settled；与线 A 的交点：C3 改变工具返回文本形态，故**数字台账抽取（M1）须在 C3 之后或同批对齐** |
| 回滚 | — | 出口闸为新增工具 + agent_settled 判据切换，可整体 revert 回现行粗筛路径；线 C 为路径/文案级改动，同样可单独 revert |

---

## 十、施工计划（十步流程）

- **Step1 explore**：核验四件事——① pi registerTool 的 execute 返回文本在 RPC 事件流中的形态（tool_execution_end.result）；② appendCustomMessageEntry 保底路径在出口闸下的触发面；③ 网关 mapEvent 传 realSessionId 的改动点清单；④ submit_conclusion 在 agent 模式工具列表中的描述写法（防漏调）。
- **Step2 propose**（四件套：proposal/design/specs/tasks）+ **Step3.5 自查**：重点自查——**E1-E9 与 N1-N4/N10 对应；N5-N9 由 smoke:all + 手工验证覆盖**（v1.2 修正：原"E1-E6 与 N1-N9 一一对应"不成立，E4/E6 无对应 N、N5/N6/N9 无对应 E）；保底路径与出口闸路径互斥完备（四种 tier × 有/无提交的全枚举，**含 `submit_conclusion` 的 tier 归属**，见 §3.1）；台账 entry 体积上限；**台账数字归一化的字段白/黑名单（v1.4，含标识符排除）**。
- **Step5 施工**（里程碑）：
  - M1 数字台账 + 出口闸工具（tool_result hook 扩展 + submit_conclusion 注册 + 服务端验证）
  - M2 agent_settled 改道 + 保底路径 + 回灌文案语义化
  - M3 状态台账（series entry 非空 append / verifier-state entry / verdict 送达 / ctx 首轮时序）
  - M4 评估用例 **E1-E9** + trajectory submission 字段 + ci.sh 接入
  - M5 提示词配套（AGENTS/SYSTEM/PRISM_ANALYSIS）
  - M6 全量验收（**N1-N10** + smoke:all + tsc）
- **Step6-10**：simplify / code-review / receiving / verification / archive，照常。

依赖：M1→M2→(M3、M4、M5 可并行)→M6。**前置运维检查**（§五前两行：旧进程重启 + 上游服务启动，即线 C 的 C0）在 M1 前完成。
**线 C 并行**：C1/C2 可与 M1 同时启动；C3 完成后才做 M1 的数字台账抽取对齐；线 C 全部完成后 N10 才能验收。
**三线收口**：线 A（出口闸）+ 线 B（截断）+ 线 C（工具层）在 M6 一次性全量验收（N1-N10）。

**线 B（并行）：工具结果截断/旁路 change**（D5 已拍板，与线 A 独立立项、同期推进）：
- B1 截断阈值：工具 execute 返回前裁剪（对齐 pi extensions.md 自截断要求），上下文内只留"摘要 + 行 ID + as_of + 关键字段"，超限原文落旁路文件（参照 pi bash 的 full_output_path 模式）
- B2 字段裁剪：/autohome 系列大接口（series-list 160KB）回传必要列
- B3 compaction 阈值复审：keepRecentTokens/reserveTokens 在截断生效后重测再调
- B4 验收：单工具回传 <20KB；20 轮会话第 20 轮 TTFT ≤ 首轮 1.5×；**E1-E9** 不回归
- 与线 A 的唯一交点：出口闸的数字台账（prism-numeric-truth）在 tool_result hook 抽取，须在截断**之前**抽（先抽真值再截断入上下文）——两条线在 explore 阶段对齐此顺序

**线 C（v1.2 并入，D6 拍板；v1.3 缩正范围）：上游工具层修复（治 G5）** —— 与线 A / 线 B **并行推进**：

- **C0（前置·运维）**：启动 Atuohome :8001 与舆情 :8000，纳入施工前置检查——502×105 主因即 8001 未启动，环境不就位则线 C 验收无意义。
- **C1 sentiment_events 路径修正（v1.3 缩范围至 1 处）**：`/top-events/{vehicle_id}` → `/vehicles/{vehicle_id}/events`（服务真实路由 dashboard.py:1399；其余 5 个舆情工具路径经逐条对照**全部正确**，不改）。**可选加固**：施工期路径校验脚本（工具模板 ∈ 服务 21 条 dashboard 路由），防再次静默失效。
- **C2 `get_sales_detail` 参数语义澄清**：入参统一为车系名 `series`，schema 描述与 `prism-api/main.py` 的 `AUTOHOME_TOOL_MAP` 对齐；**顺带解决"工具接口定义两处并存"**——白名单已一源（TOOL_CATEGORIES），接口定义仍两源（extension 的 `makeAutohomeTool` vs main.py 的 `AUTOHOME_TOOL_MAP`），单一真值源原则在此补全。
- **C3 工具失败语义化**：失败返回统一为结构化状态（如 `{status:'unavailable', scope, reason, fallback:'none'}`），不再裸抛 `HTTP 404/502`。目的：让模型能走红线#4 的"如实报告缺失"话术，**而非绕路**（绕路是上下文污染的源头）。
- **C4 验收**：E7 通过；舆情/口碑工具在服务正常时不再恒错；轨迹中 `bash` 调用占比显著下降（N10）。
- **依赖**：C1/C2 可与 M1 并行；**C3 改变工具返回文本形态，故数字台账抽取（M1）须在 C3 之后或同批对齐**（与"线 B 截断先于/后于抽取"同一类时序约束）。

---

## 十一、决策记录（D1-D6 已拍板，2026-10-07）

| # | 决策点 | **定案** |
|---|---|---|
| D1 | derived 数字验证粒度 | **仅验源数字在台账，不验算式**。源真实性由台账保证；算式错误属语义质量，交人工抽检/后续 judge |
| D2 | verdict 送达网关方式 | **网关用 realSessionId 自算路径**（get_state 时序已具备，两行级改动）；last-verdict.json 保留为兼容兜底并标 sunset |
| D3 | 保底回灌的消息注入方式 | **保留 appendCustomMessageEntry + 文案语义化**（"系统校验通知，直接输出修正后的答复"）；频率趋零后几乎不出场，等 pi 原生 continuation 再换 |
| D4 | 出口闸的 tier 覆盖 | **出口闸（submit_conclusion 验证）只管 library tier**；web/mixed 维持 URL 真值集 + 降级告警，观察一版后定。（注：`agent_settled` **保底拦截不受此限**——其条件不限定 tier，见 §3.4 第 2 条） |
| D5 | 工具截断是否做 | **做**——独立 change 与出口闸**并行推进**（非排后），见 §十 线 B；两线唯一交点=数字台账先于截断抽取 |
| **D6** | **上游工具层（G5）是否并入** | **并入**（2026-10-07 拍板）。理由：工具不可用是"绕路 → 上下文污染 → 验证器误判素材"的**源头**，不修则出口闸只是让污染"不被检出"而非不被产生；以 §十 **线 C** 承载（C1 舆情路径 / C2 参数语义 / C3 失败语义化），与线 A/B 并行 |

---

## 附录：证据索引

- 事发轨迹：`.pi/sessions/trajectories.jsonl` **#56-58**（2026-10-07 10:38-10:44，1-based；#56-58 含 bash×36/37 旧进程证据）
- submit_conclusion 原始设计：`文档/Prism-Agent-pi改造研究.md:89/111/157/183`（grep 实锤当前代码无实现）
- 派生数字死穴推演：本方案 §1.2（−14.1% 案例）
- verdict 路径错位：pi 官方 `json.md:45`（agent_settled 无字段）+ extension 写入路径（index.ts:563）vs 网关读取路径（pi_gateway.mjs:75-79）
- ctx 首轮错位：`prism-web/src/lib/chat.ts:39`（首轮 session_id=null）→ `pi_gateway.mjs:419`（|| 'default'）vs extension 候选 key（index.ts:684-704）
- 工具结果不截断：pi `extensions.md:144`（要求自建工具自截断）、`mcp.md:230`（仅 MCP 20KB）、`codemode.md:43`（仅 bash 50KB）vs 我们的 `JSON.stringify(data)` 全量返回（index.ts:121 等）；事发会话 446KB（usr_g5r6h5ye）
- **上游工具层实测**（v1.2 新增、v1.3 复算、**v1.4 标口径**）：含工具错误 **30/60**；`502`×105、`404`×18、`504`×8、`422`×7、`400`×9；调用次数 `bash` **110** 居首（`query_sales` 78 次）。
  - **口径说明（v1.4，P-e）**：上表数字按 **`conversation` 全文字段**匹配错误关键词。若改按 **`toolResult` 段落**匹配，实测为 `502`×100 / `400`×7（`接口错误` 139 次）——**两口径不同，复算时须先声明按哪个字段、什么正则**，否则同一事实会得出不同数字。建议施工时把口径写进脚本注释。
- **事发轨迹逐行（1-based，v1.2 校正）**：`#56` toolCalls=53 / bash=36 · `#57` toolCalls=58 / bash=37 · `#58` toolCalls=58 / bash=37；`#53` 为 pass/0 工具（非事发行）
- **舆情路由对照证据（v1.3 重做，v1.4 独立复核确认）**：extension 6 个路径模板 vs 服务 `api/routes/dashboard.py` 全部 21 条 `@router.get` 逐条对照——5 个匹配（overview:55 / trend:584 / dim-sentiment:1431 / top-posts:777 / competitor-comparison:963），1 个错（top-events 不存在，真路由 `/vehicles/{vehicle_id}/events`:1399）。v1.2 的"6 工具错配、真实路由为 /api/vehicles/..."系误读 OpenAPI 全局前缀，已证伪。
  - **复核依据（v1.4）**：`dashboard.py:20` 为 `APIRouter(prefix="/api/dashboard", tags=["dashboard"])`；extension 侧已拼该前缀（index.ts:177 注释 + L214），故前缀无误，差异只在实际路由是否存在——6 条中 5 条存在、`/top-events/{vehicle_id}` 不存在。**结论：v1.3 的"5 对 1 错"成立。**
- 回灌机制出处：`openspec/changes/phase2-fix/explore.md`（sendUserMessage 无原生 retry）；复发史：`openspec/changes/phase2-finalize/交互审查发现.md` 问题 2（2026-10-04）

## 修订记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-07 | 初稿 |
| v1.1 | 2026-10-07 | D1-D5 拍板定案，收敛稿 |
| v1.2 | 2026-10-07 | 审核修订：①G5 上游工具层并入（D6）+ §十 线 C；②轨迹行号校正为 #56-58；③补 L1 保底漏洞（tier=none 编造漏网）**并防反噬**：保底拆 ① 漏提交 / ② 凭空编造两分支，② 绑定"数字不在台账"判定，避免闲聊复述被误拦；④补 submit_conclusion 的 tier 归属（§3.1）；⑤E/N 对应关系与 N8 单测口径校正（E1-E8 / 36）；⑥"全仓无实现"表述校正；⑦修正悬空引用（前置文档名） |
| v1.3 | 2026-10-07 | 二次审核修正：①**证伪 v1.2"舆情 6 工具路径错配"**——逐条对照 dashboard.py 21 条路由，实为 5 对 1 错（仅 sentiment_events），C1 缩范围，错误构成重分解（502×105 主因=8001 未启动，环境项，新增 C0 前置）；②**补台账两缺口**（防"你是谁"事故换壳复发）：采集范围扩至全部业务数据工具、submission pass 后回写台账含 derived；③② 分支多数字口径定死（任一不可溯源即拦，与 E4 同口径）；④E1 补强（覆盖派生数字复述 + 非 query_* 来源复述）；⑤N8 单测数实测 32（identity_api.test.ts 已删）；⑥附录第一条口径统一为 1-based #56-58，错误码计数复算校正 |
| v1.4 | 2026-10-07 | 三次审核修正：①**台账回写改分信任级（P-a）**——v1.3 的"derived 一并并入台账"会把派生数字的洗白效果**跨轮固化**（提交一次假派生值即永久"可溯源"）；改为 `source=tool` 并入真值集、`source=derived` 仅记 `declared-derived` 弱信任项（供复述放行，不得作次级 derived 源）；②**台账排除标识符数字（P-b）**——series_id/spec_id/model_id/post_id/vehicle_id 不入台账，避免"随口说个 ID 也算可溯源"；③**N8 单测数 32→36 校正**——`tests/identity_api.test.ts` 文件仍在且 `package.json` 的 `smoke:verify` 仍引用，"已删"有误；④**新增 E9** 防洗白链用例，E1-E8 全线升为 E1-E9；⑤§十 依赖段运维项引用校正为"§五前两行/C0"；⑥错误码计数标明口径（conversation 全文字段 vs toolResult 段落，两口径实测值不同） |
| v1.5 | 2026-10-07 | 四次审核小修（v1.4 三项实质修正经复核全部认可后补齐两处自洽性）：①**§3.4 ② 判定集显式定义** = 真值集 ∪ declared-derived——v1.4 拆两级台账后 ② 仍写"不在数字台账内"，窄读为仅真值集会误拦"复述已验证派生数字"，与 E9 自相矛盾；②**台账排除错误载荷**（isError / C3 unavailable 不入台账）——防"HTTP 502"类数字进真值集变"可溯源"，与 P-b 同类健全性问题。附：N8=36 已独立验证成立（tests/identity_api.test.ts 存在、4 测试、package.json 引用齐全） |
