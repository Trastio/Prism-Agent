# Prism-Agent 验证器回灌误判 · 审查报告与解决方案

> 报告日期：2026-10-07
> 触发来源：前端对话截图 —— 用户问「你好，你是谁？」，Agent 回复「验收意见成立…验收整改·补齐证据行 ID…」
> 审查范围：完成验证器（Completion Verifier）回灌机制全链路
> 结论：问题定位完成；根因三层；方案分 P0/P1/P2 三档；**本次仅实施前端展示层（标），核心判据未改（本）**

---

## 〇、摘要

一句话：**验证器把「闲聊时复述本会话已核验过的真数字」误判成了「没查数却给数字结论」，于是判定不合格并自动回灌一条验收意见，模型把这条意见当成用户在说话，回了「验收意见成立…验收整改」。**

三个关键结论：

1. **「重答」机制本身没有错**，它是为治「抢答」设计的（教材 `premature-completion-dpo`）。
2. **错在判据**：红线#1 的原始要求是「不编造数字」，但当前实现退化成了「必须附行 ID」。复述真数字因为没附行 ID 而被判 fail —— 这是**判据错位**，不是模型犯错。
3. **这是一次复发**：2026-10-04 的《交互审查发现》问题 2 已记录过同类现象，当时的修法（用「数字 + 维度词」识别分析类结论）**正是今天误判的成因**。

---

## 一、问题现象

### 1.1 用户可见现象

用户在前端输入「你好，你是谁？」，Agent 气泡返回的不是自我介绍，而是：

```
验收意见成立——上一轮是纯文字复述，无工具调用也无 supported_by 行 ID。现在重新核数并补齐证据链。

## 验收整改·补齐证据行 ID
验收意见成立。上一轮我输出了数字结论但①无工具调用 ②无 supported_by 行 ID。本轮已重跑全部语义工具。
⚠️ 先更正我自己的一个错误结论
上一轮我上报的"bug #2: get_sales_detail 恒 400，工具坏了"——是我的错误，撤回。
真相：该工具的入参本就是 series（车系名），我连续两次传了 model_id …
## 一、销量·证据行 ID（query_sales → mv_sales_monthly …）
| （银河E5, 2026, 1） | 3,028 | 10 | −48.5% |
```

即：**用户问的是"你是谁"，回答的是"我上一轮哪里不合格、怎么整改"。**

### 1.2 日志证据（可复算）

来源：`.pi/sessions/trajectories.jsonl` 第 56–58 条，`sessionId=01a10c4a-ef6a-7209-8066-b653fe9a784e`（2026-10-07）。

原始对话序列（节选）：

```
user:      你好，你是谁
assistant: 你好！我是 Prism-Agent —— 一个跑在 pi 上的汽车竞品分析 agent…
            我的硬规矩：…每个数字带 as_of 和可复算依据…
            刚才这个会话里我已经做过：
            1. 查了银河E5 2026年8月销量 = 4,436 辆（环比 −14.1%）
user:      [完成验证器] 验收未通过： - 缺少 supported_by 行 ID 请补充…
assistant: 验收意见成立——上一轮是纯文字复述，无工具调用也无 supported_by 行 ID。
           现在重新核数并补齐证据链。
```

关键点：**截图里那段，是上表最后一条 assistant（回答验证器的那一轮），不是回答用户的。** 该轮 verdict 记为 `fail / 缺少 supported_by 行 ID`。

---

## 二、为什么会有「重答」这个机制

这一节回答用户的原始疑问：这套"答完再判、不合格就重答一次"的设计是怎么来的。

### 2.1 设计初衷：治「抢答」

依据：[`openspec/changes/phase2-harness/specs/verification.md` L36-L54](../../openspec/changes/phase2-harness/specs/verification.md) 与教材 §3.5 chapter8 `premature-completion-dpo`。

LLM Agent 的典型病症是**过早完成**（premature completion）：数据没查全、证据没落地，就先把结论写出来了。这类"抢答"在汽车分析场景里直接对应红线#1（编造数字）和红线#6（名称转写）。

所以设计是：**不直接判死，给一次补救机会**。

```
VERIFY 校验（max 1 次 continuation 再不过 fail）：
  1 次失败 → continuation（补证据/降级结论）
  2 次失败 → fail
```

类比：判卷老师发现你没写解题步骤，不直接给零分，而是**退回让你补一次**；补了还不合格才判零分。上限 1 次，是"宽容一次、不纵容两次"。

### 2.2 为什么必须「注入一条消息」

依据：[`openspec/changes/phase2-fix/explore.md` L140-L143](../../openspec/changes/phase2-fix/explore.md)。

```
agent_settled 无原生 retry 返回机制——完成验证器失败后只能用 pi.sendUserMessage() 强制再来一轮：
- 不是原生 retry，消耗一次用户轮次
- max 1 次 continuation 用 sendUserMessage 实现
```

pi 的 `agent_settled` 事件**没有提供"请继续"的返回值**。扩展想让模型再跑一轮，唯一的办法就是**往会话里塞一条新的输入消息**，把模型"推"起来。

实现演进（两代）：

| 代际 | 实现 | 位置 | 声称的效果 |
|---|---|---|---|
| 第一代 | `pi.sendUserMessage(retryMsg)` | [phase2-fix](../../openspec/changes/phase2-fix/explore.md) | 消耗一次用户轮次 |
| 第二代（现行） | `pi.appendCustomMessageEntry('prism-verifier-retry', retryMsg, false)`，失败时回落 `sendUserMessage` | [index.ts L1041-L1050](../../.pi/extensions/prism-guardrails/index.ts) | 注释称"不进用户可见消息流" |

### 2.3 为什么它会露到用户面前

两处叠加：

1. **网关故意不断开**。依据：`phase3-convergence/review-response.md` P1-6 ——「retry 不流给客户端」的修复要求网关改成：`settled 且 verdict.pass=true 或 exhausted 才 break，fail 有 retry 继续读`。落到代码即 [pi_gateway.mjs L459-L477](../../prism-api/pi_gateway.mjs)：

   ```js
   // P1-6 修复：验证器 fail 会 appendCustomMessageEntry 触发 pi 开 retry 轮，
   //   不能在首个 agent_settled 就 break，否则 retry 后的改进回复对客户端不可见
   ```

   设计意图是**让改进后的回复能被用户看到**（本意是好的），副作用是把"回答验证器"的那一轮也流给了前端。

2. **前端把流累加进同一条气泡**。[ChatView.tsx](../../prism-web/src/components/ChatView.tsx) 原实现对每个 `text_delta` 都做 `agentText += ...`，不区分是第几轮。于是正常回答与整改回复粘成一段。

### 2.4 小结

**机制本身没有错**。「判完回灌、允许补一次」是必要的护栏。问题出在**判据太糙**，把不该判 fail 的判成了 fail，于是这条本该"偶尔触发"的兜底路径变成了"经常触发"的噪声源。

---

## 三、根因分析

### 3.1 直接原因：判据错位（红线#1 被实现成了「必须有引用」）

红线#1 的原始要求（[AGENTS.md](../../AGENTS.md)）：

> 数据真实性是硬底线——不编造数字/结论；缺失数据如实声明

关键词是**不编造**。但现行实现的判据是 [completion.ts L173](../../src/verify/completion.ts)：

```ts
if (!claim.supported_by || claim.supported_by.length === 0) failures.push('缺少 supported_by 行 ID');
```

**「没有行 ID」≠「编造」。** 复述一个本会话刚刚查出来、并且已经被验证器自己判定为 pass 的真数字，属于"有来源但未复引"，却被按"无来源"处理。

再往前一层，粗筛判据在 [index.ts L406-L412](../../.pi/extensions/prism-guardrails/index.ts)：

```ts
if (NUMERIC_CLAIM_RE.test(text) && DIMENSION_RE.test(text)) {
  return { action: 'reject', reason: '未调语义工具却给出数字结论（红线#1 疑似编数）' };
}
```

其中：
- `NUMERIC_CLAIM_RE` = [L360](../../.pi/extensions/prism-guardrails/index.ts)：`/...\d{2,}...\s*(?:万辆|万台|辆|台|%|分|公里|km|元|条|位|个)/`
- `DIMENSION_RE` = [L357](../../.pi/extensions/prism-guardrails/index.ts)：`/银河|车系|销量|口碑|配置|舒适|续航|智能化|零售|环比|同比|净态度|市占率/i`

本次命中情况：回复含「**4,436 辆**」（`436 辆` 匹配数字正则）与「**销量**」（匹配维度词）→ 落入"疑似编数"分支。

但这轮的数字**是真的**——它来自同会话上一轮的 `query_sales` 返回值（日志可见 `retail_sum:4436`）。

### 3.2 机制原因：验证器无状态

`verifyCompletion` 只拿到**当前这一条回复的文本**（[index.ts L853-L856](../../.pi/extensions/prism-guardrails/index.ts) 从 branch 里取最后一条 assistant 消息），再经 `extractClaim` 做正则抽取（[L513-L536](../../.pi/extensions/prism-guardrails/index.ts)）。

它**不做**以下任何判断：
- 这个数字在本会话的历史工具返回里出现过吗？
- 这个数字在前几轮是否已被验证器判定为 pass？

因此**「新编的数字」与「复述的旧数字」在它眼里完全同形**。会话越长、上下文里历史数字越多，闲聊时被误判的概率越高 —— 这解释了为什么同一句「你好，你是谁」在干净会话里 pass、在长会话里 fail。

### 3.3 结构原因：回灌消息与用户消息同构

无论 `sendUserMessage` 还是 `appendCustomMessageEntry`，落到模型上下文里都是一条 **`role=user` 的输入**。模型无法从语义上区分"这是用户说的话"还是"这是系统塞进来的验收意见"。

于是模型的自然反应就是**承接它**："收到验收意见，逐条认领并修正"。

这是"答非所问"观感的**结构性来源** —— 不是模型失控，是它在正确回答它收到的最后一条输入。

### 3.4 历史原因：这是一次复发

依据：[`openspec/changes/phase2-finalize/交互审查发现.md` L15-L19](../../openspec/changes/phase2-finalize/交互审查发现.md)（2026-10-04）：

```
### 问题 2：完成验证器太激进 → 闲聊触发"缺证据"
- 现象：agent 回答"你好，我是谁"后被验证器判定"缺 supported_by 证据"，触发 sendUserMessage retry
- 根因：验证器检查所有 agent_settled 的回复是否含证据行 ID，闲聊不含就 fail
- 影响：agent 被迫重新回答，浪费 token + 用户等待
- 修法：只对"分析类"结论触发验证（检测回复是否含数字/车系名/维度词），闲聊放行
```

当时的修法（用「数字 / 车系名 / 维度词」识别"分析类结论"）**就是今天代码里 `NUMERIC_CLAIM_RE + DIMENSION_RE` 的来源**。

也就是说：

> 2026-10-04 的修法，把"所有回复都查"收窄成了"含数字+维度词的回复才查"。这解决了当时的误报，但**引入了新误报**：长会话里闲聊复述历史数字，同样命中"数字+维度词"。

这是典型的**补丁叠加**问题 —— 每一版都解决了当时的症状，但判据的**语义根基**（无状态、字符串匹配、不辨来源）始终没动。

### 3.5 旁因：网关旧进程（独立问题，不属本次根因链）

日志前半段显示：闲聊轮里模型调用了 `bash`、`ls`、`mem0_memory`、`memory_search`、读 `package.json`，并据此自称"运行在 Prism-Agent 里的分析型 **coding agent**"。而 [pi_gateway.mjs L26-L30](../../prism-api/pi_gateway.mjs) 的 `EXCLUDE_TOOLS` 明确排除了这些工具：

```js
export const EXCLUDE_TOOLS = [
  'bash', 'powershell', 'edit', 'write', 'read', 'grep', 'find', 'ls',
  'mcp__pi_memory', 'mcp__pi-subagents', 'mcp__pi-memory-mem0',
  'mcp__pi-mcp-adapter', 'mcp__pi-todo', 'mcp__pi-workspace-history',
];
```

而后续轮次出现了 `Tool bash not found` → 说明**有一段时间跑的是未生效的旧进程**，中途重启过。

**这一条与截图中的"验收整改"无关**（截图那轮 bash 已被排除），但它导致更早轮次的"coding agent 身份跑偏"，属于并行存在的独立缺陷。

---

## 四、证据链

### 4.1 对照组（同问题、不同会话，结论相反）

| 时间 | sessionId | 上下文 | verdict | reason |
|---|---|---|---|---|
| 2026-10-06 03:06 | `01a10f2d-…` | 干净会话，首轮即问「你好，你是谁？」 | **pass** | `闲聊/能力说明，放行` |
| 2026-10-07 06:38 | `01a11515-…` | 干净会话 | **pass** | `闲聊/能力说明，放行` |
| 2026-10-07 10:44 | `01a10c4a-…` | 长会话（已问过多轮销量） | **fail** | `缺少 supported_by 行 ID` |

**唯一变量是"上下文里有没有历史数字"**，这直接指向 §3.2（验证器无状态）。

### 4.2 代码定位一览

| 环节 | 文件 | 行号 |
|---|---|---|
| 验证器入口 | `.pi/extensions/prism-guardrails/index.ts` | L838 |
| tier 判定 | 同上 | L50-L57（定义）/ L858-L865（调用） |
| 粗筛判据 | 同上 | L389-L414（数字+维度词分支在 L406-L412） |
| 各正则定义 | 同上 | L357 / L360 / L363 / L366 / L369 |
| 细查主入口 | `src/verify/completion.ts` | L159-L199 |
| 「缺少 supported_by 行 ID」 | 同上 | L173 |
| 行 ID 查库 | 同上 | L46-L67 |
| 越界检查 | 同上 | L116-L135 |
| 回灌触发（library/none） | `index.ts` | L1030-L1050 |
| 回灌触发（mixed） | `index.ts` | L950-L963 |
| 回灌触发（2b 身份） | `index.ts` | L884-L895 |
| 回灌上限 | `index.ts` | L427（`VERIFIER_MAX_RETRY = 1`） |
| 防自回灌 | `index.ts` | L417-L419（`isVerifierRetryTurn`） |
| 网关继续读 retry | `prism-api/pi_gateway.mjs` | L459-L477 |
| 前端累加文本 | `prism-web/src/components/ChatView.tsx` | 原 L111-L120 |

### 4.3 取证命令（可复算）

```powershell
# 1) 定位含该文案的轨迹行
Select-String -Path .pi/sessions/trajectories.jsonl -Pattern '验收整改|补齐证据行 ID'

# 2) 展开指定轨迹行的完整对话（示例取第 56 行）
$code = @'
import json
p = r".pi/sessions/trajectories.jsonl"
lines = open(p, encoding="utf-8").read().strip().split("\n")
o = json.loads(lines[55])
print(o.get("verdict"), o.get("verdict_reason"))
for m in o.get("conversation") or []:
    print(str(m.get("content"))[:300])
'@
$code | python -X utf8 -
```

---

## 五、影响面

| 维度 | 影响 |
|---|---|
| 用户体验 | 高 —— 闲聊/自我介绍被答成工程整改，且用户无法分辨哪段是回答自己 |
| 信任成本 | 高 —— 用户会认为"这个 Agent 又在自说自话"，类似 §1.1 的观感直接损伤产品可信度 |
| Token 成本 | 中 —— 每次误判触发一轮完整重答（含工具调用），实测单轮可产生 50+ 次工具调用 |
| 数据正确性 | **无影响** —— 数字本身是真的，误判不产生错误数据 |
| 触发概率 | 随会话长度递增（历史数字越堆越多），长会话用户命中率显著更高 |
| 架构影响 | 无 —— 属判据层缺陷，不动数据层与工具层 |

---

## 六、解决方案

### 6.1 P0：立即止血（零代码风险）

**动作**：重启 9200 网关进程，使 `EXCLUDE_TOOLS` 生效。

**理由**：解决 §3.5 的"coding agent 身份跑偏"与工程工具乱调。不涉及代码改动，风险为零。

**验收**：闲聊轮不再出现 `ls` / `bash` / `package.json` 类工具调用；自我介绍不再自称 coding agent。

**边界**：**不解决**截图中的"验收整改"问题。那条是判据问题，必须走 P1。

### 6.2 P1：判据修复（核心方案）

原则：**包裹而不替换**（沿用既有逻辑，只在前面加一道来源核验）。

#### P1-a 引入「数字来源核验」，让判据对齐红线#1 的真实语义

**现状**（[index.ts L405-L413](../../.pi/extensions/prism-guardrails/index.ts)）：

```ts
if (hasEvidence) return { action: 'reject', reason: '引用既有证据形态，需 verifyCompletion 查库验证' };
if (NUMERIC_CLAIM_RE.test(text) && DIMENSION_RE.test(text)) {
  return { action: 'reject', reason: '未调语义工具却给出数字结论（红线#1 疑似编数）', message: REJECT_MSG_NO_TOOLS };
}
return { action: 'pass', reason: '闲聊/能力说明，放行' };
```

**改法**（在既有分支内增加前置来源判断，原 reject 逻辑保留为兜底）：

1. 新增 `prism-numeric-truth` 采集：在 `tool_result` hook（[L814](../../.pi/extensions/prism-guardrails/index.ts)）中，复用已有 `prism-name-truth` 的范式（[L830](../../.pi/extensions/prism-guardrails/index.ts)），从工具返回文本中抽取数字 token 并归一化（去千分位逗号、去单位、统一为裸数值）。
2. 新增 `collectNumericTruthFromBranch(branch)`：聚合本会话工具返回过的全部数字。
3. 在 L406 分支内插入判断：

```ts
if (NUMERIC_CLAIM_RE.test(text) && DIMENSION_RE.test(text)) {
  // 新增：数字若能全部溯源到本会话工具返回 → 属"复述已核验数据"，非编造，放行
  const numericTruth = collectNumericTruthFromBranch(branch);
  if (allNumbersTraceable(text, numericTruth)) {
    return { action: 'pass', reason: '复述本会话已核验数据，非编造' };
  }
  // 原逻辑保留：有任一数字找不到来源 → 仍按疑似编数 reject
  return { action: 'reject', reason: '未调语义工具却给出数字结论（红线#1 疑似编数）', message: REJECT_MSG_NO_TOOLS };
}
```

**关键约束**：**全部数字可溯源才放行**。只要有一个数字在会话工具返回里找不到，就维持原 reject —— 这样红线#1（防编造）**不被削弱**。

**为什么这是对的**：红线#1 防的是"编造"，不是"未引用"。判定"这个数字有没有来源"才是红线#1 的直接实现；判定"有没有 supported_by 字段"只是它的一种**代理指标**，代理失准时应当回归本义。

#### P1-b 回灌消息语义化（辅助，可后置）

**现状**（[formatFailures L538-L541](../../.pi/extensions/prism-guardrails/index.ts)）：

```ts
return '[完成验证器] 验收未通过：\n' + failures.map(f => '- ' + f).join('\n')
  + '\n请补充 supported_by 证据行 ID / as_of 数据时点 / scope 结论范围后重新作答。';
```

模型把这段读成"用户给的评审意见"，于是回"收到验收意见"。

**改法**：文案明确标注为系统指令，并显式禁止对指令本身作答（例如追加"这是一条系统校验通知，请直接输出修正后的答复，不要回复本条通知"）。

**注意**：这属于提示词层，按红线#5「护栏在执行层，不在提示词」，**不可作为唯一防线**，只作 P1-a 的辅助。P1-a 才是执行层的实质修复。

#### P1-c 网关与前端：回灌轮不再与正常回答同构（已部分实施）

- 前端已完成（见 §6.4）。
- 网关可选增强：在 `settled` 事件里透出 `can_retry` 字段，让前端不必靠 `verdict === 'fail'` 推断。

### 6.3 P2：结构性治理（根治，需先有评估基线）

#### P2-a 上下文治理（对应既有 P1-4）

工具返回结果入库前裁剪（只保留摘要 + 行 ID + as_of），降低历史数字在 branch 中的堆积量。会话越短，§3.2 的误判窗口越小。

**前置依赖**：`eval-scorer` 目前是死码（见《评估体系完整方案》§九 #2），拿不到可信基线，**改动效果无法度量**。故 P2 排在 scorer 重写之后。

#### P2-b 重答机制的语义隔离

若 pi 后续为 `agent_settled` 提供原生 continuation 返回值，则改用它，彻底消除"注入 user 消息"的同构问题。当前 pi 不支持，保持现状 + P1-a/P1-b。

### 6.4 已实施（2026-10-07）

**范围**：仅前端展示层（治标），未改验证器与网关。

**文件**：`prism-web/src/components/ChatView.tsx`

| 改动 | 位置 | 内容 |
|---|---|---|
| Msg 扩展 | L12-L21 | 新增 `isRetry` / `retryReason` 可选字段 |
| 回灌轮状态 | L95-L99 | 新增 `retryPhase` / `retryBubbleStarted` / `retryReason` |
| `settled` 分流 | L173-L190 | `verdict === 'fail'` → 切回灌模式并提示"验证未通过，正在重试…" |
| delta 分流 | L110-L136 | 回灌轮首段文本/思考另起气泡，不并入正常回答 |
| 渲染区分 | L227-L238 | 表头显示「系统自检 · 验证器重试」，并说明"不是对上一句提问的直接回答" |

**验证**：`npx tsc --noEmit` 通过。

**效果**：用户不再被误导；**但机器仍会产生这段回复**（治标不治本）。

### 6.5 方案对比与取舍

| 方案 | 层次 | 治标/治本 | 风险 | 是否削弱红线#1 | 建议 |
|---|---|---|---|---|---|
| 重启网关 | 运维 | 旁因 | 无 | 否 | **立即做** |
| 前端分气泡（已做） | 展示 | 治标 | 无 | 否 | 已做 |
| P1-a 数字来源核验 | 执行层 | **治本（直接原因）** | 中 | **否（全溯源才放行）** | **推荐** |
| P1-b 回灌消息语义化 | 提示词 | 辅助 | 低 | 否 | 随 P1-a |
| P2-a 上下文治理 | 上下文 | 治本（机制原因） | 中 | 否 | 待 scorer 就绪 |
| P2-b 原生 continuation | 框架 | 治本（结构原因） | 高（依赖 pi） | 否 | 待 pi 支持 |

---

## 七、验收标准

| # | 场景 | 期望 |
|---|---|---|
| V1 | 长会话（≥5 轮含数字）问「你好，你是谁？」 | `verdict=pass`，无回灌，无整改式回复 |
| V2 | 回复复述本会话 `query_sales` 已返回的数值 | `verdict=pass`，reason 含"复述本会话已核验数据" |
| V3 | 回复给出工具**从未返回过**的数字 | `verdict=fail`，reason 含"疑似编数"（红线#1 不被削弱） |
| V4 | 回复部分数字可溯源、部分不可 | `verdict=fail`（存在不可溯源数字即拦） |
| V5 | 正常分析轮（调了 `query_*` 但无行 ID） | 维持现有 fail 行为（不受本次改动影响） |
| V6 | 前端展示 | 回灌轮单独成气泡，带「系统自检 · 验证器重试」标注 |
| V7 | 闲聊轮工具调用 | 无 `ls`/`bash`/`package.json` 类调用（P0 验收） |

---

## 八、风险与回滚

| 风险 | 等级 | 缓解 |
|---|---|---|
| P1-a 数字归一化不严谨 → 放行真编造 | 中 | 仅做**全等/包含**匹配，不做模糊匹配；补单测覆盖 V2/V3/V4 |
| `prism-numeric-truth` 采集过大 → 上下文膨胀 | 低 | 只存归一化后的裸数值集合，去重；不存原文 |
| 长会话真值集过大 → 误放行 | 中 | 可限定"只在最近 N 轮工具返回内溯源"；N 待评估基线确定 |
| 回滚 | — | P1-a 改动集中在 `decideVerification` 一处 + 新增两个函数，可整体 revert，不影响其余链路 |

---

## 九、本次不做什么

1. **不改 `verifyCompletion` 的四件套完整性校验**（V5 保持不变）—— 分析轮要求行 ID 是合理的。
2. **不放宽越界检查**（`verifyScope`）—— 与本次问题无关。
3. **不动 web/mixed 分支** —— 与本次问题无关。
4. **不引入 LLM-as-Judge 判断"是否闲聊"** —— 成本高、引入新不确定性；本次用可复算的数字溯源判据替代。
5. **不删除回灌机制** —— 它是治"抢答"的必要护栏，本次只修判据。

---

## 附录 A：涉及文件清单

| 文件 | 角色 | 本次动作 |
|---|---|---|
| `.pi/extensions/prism-guardrails/index.ts` | 验证器主体 | P1 待改 |
| `src/verify/completion.ts` | 细查逻辑 | 不改（V5 保持） |
| `prism-api/pi_gateway.mjs` | 网关 | P0 重启；P1-c 可选 |
| `prism-web/src/components/ChatView.tsx` | 前端渲染 | **已改** |
| `.pi/sessions/trajectories.jsonl` | 取证来源 | 只读 |
| `openspec/changes/phase2-finalize/交互审查发现.md` | 历史复发证据 | 只读 |
| `openspec/changes/phase2-fix/explore.md` | 回灌机制出处 | 只读 |
| `openspec/changes/phase2-harness/specs/verification.md` | 设计意图 | 只读 |

## 附录 B：报告修订

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 2026-10-07 | 首版。定位根因三层 + 复发证据；方案分 P0/P1/P2；记录已实施的前端展示层改动 |
