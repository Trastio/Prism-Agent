# 出口闸-验证层根治 · design

> 依据方案 v1.5 §三/§四 + explore.md。本文件给落法细节；判据语义以方案为准。

## 1. submit_conclusion 工具

### 1.1 注册（3 处白名单同步）

`KNOWN_BUSINESS_TOOLS` + `TOOL_CATEGORIES.business` 加 `submit_conclusion`（ALLOWED_TOOLS 派生自动含）；`decideTier` hasLib 追加显式包含（保留 query_ 前缀判据）。

### 1.2 参数（TypeBox，方案 §3.1 契约）

```
conclusion_text / supported_by[] / as_of / scope / data_gaps_declared[] /
numbers: Array<{ value, source: 'tool'|'derived', derived_from?: string[] }>
```

描述文案（防漏调）："提交分析结论供出口闸验证（红线#1）。凡基于库数据下数字结论，必须先调本工具提交 CLAIM；通过后才算交付。拒绝原因会以工具结果返回，请按原因修正后重新提交。"

### 1.3 execute 流程（执行层执法）

```
1. sessionId = ctx.sessionManager.getSessionId()
2. entries = ctx.sessionManager.getEntries()
3. ledger = readNumericLedger(entries)        // { truth: Set, declaredDerived: Set }
4. claim = { conclusion_text, supported_by, as_of, scope, data_gaps_declared }
5. checks = verifyClaimChecks(claim, identityCoverage)   // D7 纯函数，四件套
6. 数字校验：
   - numbers.source='tool' → value ∈ ledger.truth
   - numbers.source='derived' → derived_from 每个 ∈ ledger.truth（declaredDerived 不算）
   - 任一不过 → 拒绝项
7. nameResult = verifyNames(conclusion_text, collectNameTruthFromEntries(entries))
8. 全过 → **先回写台账**（tool 值并入 truth、derived 值记 declaredDerived，appendEntry 'prism-numeric-truth' 增量）**再写** pi.appendEntry('prism-conclusion-verified', { numbers, ts })（3.5 Gap7：回写失败则不写 verified——fail-closed，submission 判不过、模型收到拒绝重试）
        + 返回 pass 文本
9. 有拒绝项 → 返回 '[出口闸] 拒绝：\n- …\n请修正后重新提交（derived_from 只接受工具返回的源数字）'（≤2KB）
```

## 2. 数字台账（三级）

### 2.1 采集（tool_result hook 扩展）

现行 hook 只处理 `query_*`（index.ts:814-815）→ 扩为 `TOOL_CATEGORIES.business` 全部数据工具（不含 submit_conclusion 自身）。每次返回后 `appendEntry('prism-numeric-truth', { values: [...] })`（本调用新抽取的归一化值；读取时 union）。

### 2.2 归一化与排除

- 归一化（3.5 Gap3 定死）：去负号、去 %、去千分位逗号、去单位（辆/台/%/万/公里/km/元/条/分/位/个）、去前后空白；小数去尾零（"14.10"→"14.1"）；结果一律字符串。单测含三态同值用例（−14.1% / 4,436 辆 / 4436 → "14.1"/"4436"/"4436"）
- **排除**（v1.4/v1.5）：①标识符字段 `series_id/spec_id/model_id/post_id/vehicle_id/year/month` 的值不入台账（按 JSON key 判断，非数值猜测）②`isError=true` / C3 `unavailable` 载荷整体跳过
- 抽取与②保底共用同一归一化 util（`normalizeNumberTokens(textOrJson)`），单测覆盖

### 2.3 读取（readNumericLedger）

union 全部 `prism-numeric-truth` entries → `{ truth: Set<string>, declaredDerived: Set<string> }`。**②判定集 = truth ∪ declaredDerived**（v1.5 显式定义）。

## 3. agent_settled 改道（M2）

现行 G1 全量验证路径（decideVerification + verifyCompletion + 回灌）替换为：

```
0. 保底③身份未核验（3.5 Gap1：现行 2b 判据原样保留，优先级最高——先验身份再验提交）
   tier=library && sessionSeriesKey 空 && 未调 resolve_series → 拦截（现行 index.ts:874-896 平移）
1. turnStart 后本轮 branch 含 prism-conclusion-verified → verdict=pass（落盘三件套照旧）
2. 无通过提交：
   numericForm = NUMERIC_CLAIM_RE.test(text)
   tier = decideTier(calledTools)
   ① tier=library && numericForm → 拦截"漏提交/提交被拒未修正"
   ② tier=none && numericForm && extractNumbers(text) ⊄ (truth ∪ declaredDerived) → 拦截"凭空编造"（任一数字不可溯源即拦）
   其余 → pass
3. tier=web/mixed → 现行逻辑不动
4. 回灌机制（appendCustomMessageEntry + isVerifierRetryTurn + VERIFIER_MAX_RETRY）
   保留为保底服务；attempt/签名改读 prism-verifier-state entry（M3）
```

回灌文案（保底）："[完成验证器·保底] 本轮含库数据数字结论但未通过 submit_conclusion 提交（或提交被拒后未修正）。这是系统校验通知——请直接调 submit_conclusion 提交修正后的结论，不要回复本通知。"

## 4. D7：verifyClaimChecks 提取（src/verify/completion.ts）

```
export function verifyClaimChecks(claim, identity_coverage?): { pass, failures }
  // 四件套本体：行ID查库 + as_of + 越界(NEG_RE 逐词) + 缺口声明 —— 从 verifyCompletion 平移，零逻辑变更
export function verifyCompletion(sessionId, claim, identity_coverage?): VerifyResult
  // = verifyClaimChecks + attemptMap 计数 + can_continue（原行为不变，单测不破）
```

## 5. 状态台账（M3）

| 项 | 落法 |
|---|---|
| series_key | before_agent_start 的 appendEntry 改为**仅 seriesKey 非空时 append**；2b 判据读取改为"最新非空" |
| ctx 首轮 | 网关把 ctx.json 写入挪到 get_state 之后，key 用 realSessionId（explore ③ 同批） |
| verifier-state | `prism-verifier-state` entry `{attempt, failureSig}`；agent_settled 保底读写它，删进程内存 lastFailureSigMap |
| verdict 送达 | 网关 mapEvent 加第三参 realSessionId；extension 写入路径不变（本来就写 sessionId 目录） |

## 6. 线 C（并行，工具层）

- C1：makeSentimentTool('sentiment_events') 路径 `/top-events/{vehicle_id}` → **`/vehicles/{vehicle_id}/events`**（router 相对路径，防双前缀）
- C2：get_sales_detail schema 描述强化（"series=车系名（如 银河E5），非 model_id"）+ AUTOHOME_TOOL_MAP 注释对齐
- C3：全部工具 execute 失败返回 `{ status:'unavailable', tool, reason, fallback:'none' }`（含 HTTP 码原文于 reason），isError=false（让模型读到结构化语义而非裸错误）；**台账抽取跳过该形态**

## 7. E1-E9（M4，eval/tasks_gate.json + runner --gate）

| # | 场景 | 断言 |
|---|---|---|
| E1 | 长会话（含派生数字结论轮 + 非 query_* 来源轮）后问"你是谁" | settled=1 / 无回灌 / 无整改体 |
| E2 | 环比类结论 + derived 声明 | submission pass |
| E3 | 编造数字提交 | 拒绝→同轮修正→pass；无 user 消息注入 |
| E4 | 部分数字不可溯源 | 拒绝 |
| E5 | 库分析+数字结论+未提交 | 保底①拦截 |
| E6 | 多次被拒后放弃 | 同因截断+上限生效 |
| E7 | 工具不可用（模拟） | 报告缺失；该轮 bash=0 |
| E8 | tier=none 凭空数字 | 保底②拦截；与 E1 同批过 |
| E9 | derived 复用为次级源 | 拒绝；同值复述放行 |

runner 断言扩展：settled 事件计数（NDJSON 流）、toolCalls bash 计数、trajectory.submission 字段（appendTrajectory 增：`submission: {count, pass, lastReject}`）。
ci.sh：`--gate` 模式跑 E1-E9，全绿才过（与现有 16 题门禁并存）。

## 8. 提示词（M5）

- AGENTS.md discipline +1 条：结论交付必须走 submit_conclusion；正文是展示层
- SYSTEM.md 第 5 条改写：数字来源由出口闸验证；报告交付在 CLAIM 带 supported_by
- PRISM_ANALYSIS.md：CLAIM 示例改工具调用形态
