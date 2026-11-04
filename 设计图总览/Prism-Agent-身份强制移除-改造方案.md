# Prism-Agent · 身份强制移除 + 架构影响全面审查（基于代码实测）

> 2026-10-07
> 起因：用户"打开 Prism 就能发消息，像豆包一样交互，不需要先选车系"
> 性质：**改造方案**（待审阅，审阅通过施工）
> 审查方法：逐行读代码（非记忆/设计稿），核验每处实际逻辑
> **本版为第 2 轮审查修订**：校正行号、补执行层替代护栏（红线#5/#7）、声明与 v8 计划的交叉

---

## 零、与既有计划的交叉 + 代码现状（第 2 轮新增 · 必读）

**本方案是《Prism-Agent-能力扩展与验证层重构-改造计划 v8》的「增补 change」**，不重复 v8 内容。逐行核代码后发现 **v8 多个块已落地**，故本方案范围须相应收缩：

| v8 块 | 现状（代码实测） | 对本方案的影响 |
|---|---|---|
| 块1.1 跨维度越界 | **已实现**（[completion.ts L108-L135](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/completion.ts#L108-L135)） | 本方案问题 G **属该块范围**，不另立 |
| 块1.2 验证入口短路 | **已实现**（[index.ts L385-L399](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L385-L399)） | 问题 F 的"不改"结论成立 |
| 块2 tier 路由 | **已实现**（[index.ts L48-L60](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L48-L60)、[L458-L464](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L458-L464)、[L853-L912](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L853-L912)） | 问题 F 的 tier=web 分流成立 |
| 块3 TOOL_CATEGORIES | **已实现**（[index.ts L39-L46](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L39-L46)） | — |
| 块4 上下文对象化 | **已实现**（[pi_gateway L398-L406](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L398-L406) 写 ctx.json、`// 不再拼前缀`） | 问题 H **现役且真实**（但修复对象是 ctx.json，已非 prompt 前缀） |
| 块4 memory.json | **已实现**（[index.ts L777+](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L777)） | — |

**结论**：本方案应聚焦"身份强制移除"这一**独立增量**；其余问题要么属 v8 已落地块（F/G），要么是 v8 未覆盖的网关/提示词对齐（A/B/C/D/E/H/I）。**不得与 v8 已落地实现冲突。**

---

## 一、身份强制移除（核心）

### 代码实测（行号已校正）

**ChatView.tsx L82**（实际代码）：
```ts
if (!series) { setStatus('请先选择车系'); return; }
```
series 为空字符串时禁止发送。App.tsx L24 `useState('')` 默认空 → 用户打开就被拦。

**extension index.ts L724-L729**（实际代码）：
```ts
// T-2.5 Gap 4：强制前置核验 series_key（红线#7）
// D/W2：series_key 为空时真阻断（setActiveTools([])，非拼提示词，符合红线#5）
if (!seriesKey) {
  try { pi.setActiveTools([]); } catch {}
  return { systemPrompt: '对象未确认，请先选择车系（红线#7 fail-closed）。不要进行分析，告知用户需先选择车系。' };
}
```
注意 [index.ts L718](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L718) 已在 agent 模式设 `setActiveTools([...ALLOWED_TOOLS])`，故删掉 L724-L729 后**全量工具自然生效**（无需另设）；`setActiveTools([])` 会把 web_search / ask_user_question 一并关掉。

### 改造（删 2 处）+ **必配执行层替代护栏（本轮新增 · 关键）**

原方案只删 2 处、以提示词引导兜（问题 D 的 `{warnings}`）。**这违反红线#5**——[AGENTS.md](file:///c:/Users/<you>/Desktop/Prism-Agent/AGENTS.md) 明写"护栏在执行层（hooks/tools），不在提示词；in-context agent 不可靠自检"，且 [index.ts L724-L725](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L724-L725) 注释明志：该硬阻断正是为满足红线#5 而加（D/W2）。**只删不补 = 破红线#5/#7。**

故本方案**必须**补一条执行层替代护栏：

1. **删**：`if (!seriesKey) { setActiveTools([]); return {systemPrompt:…} }`（行 L724-L729）
2. **2a 前置 · series_key 持久化（新增 · 必做）**：`before_agent_start` 读出 `seriesKey`（[L703](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L703)）后**无条件** `pi.appendEntry('prism-session-series-key', { series_key: seriesKey })`——**含空字符串**，**不得**套用 `prism-identity-coverage` 的 `if (identityCoverage)` 守卫（[L754](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L754)）。
   - **为什么必需**：`seriesKey` 是 `before_agent_start` 的**局部变量**，`agent_settled` 属另一 hook、另一作用域，**取不到**；且 ctx.json 已在 [L706](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L706) 被 `unlinkSyncSafe` 删除 → **不持久化则 2b 判据根本执行不了**。
3. **2b 替代（执行层，必做 · 依赖 2a）**：`agent_settled` 时从 `entries` 取**最新一条** `prism-session-series-key` 的 `series_key`（与读 `prism-identity-coverage` 同 pattern，[L871-L876](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L871-L876)；**取最新而非首个**，避免读到上一轮残留）。**若 `tier==='library'` 且该值为空 且 calledTools 不含 `resolve_series` → reject**（回灌文案：`[完成验证器] 未先核验对象身份：本轮在做库数据分析，但未调用 resolve_series 确认对象（红线#7）。请先核验车系，再下结论。`）。把红线#7 从"全关工具"迁移到"库 tier 的身份前置判据"，**不误伤**闲聊（tier=none）/ web（tier=web）。
   - **已裁定**：身份证据**仅认 `resolve_series`**——`search_cars` 等其他工具**不作**身份证据。理由：与 [AGENTS.md](file:///c:/Users/<you>/Desktop/Prism-Agent/AGENTS.md) 红线#7 原文"先 `resolve_series` 确认对象"完全一致，执行层判据与提示词**同一口径**，不设第二套标准。
4. **保留全量工具**：series 空时**仍 `setActiveTools([...ALLOWED_TOOLS])`**（**不做工具收窄**）。
5. **提示词层（best-effort，非主防线）**：问题 D 的 `{warnings}` 引导 + AGENTS.md 红线#7 保持。

> **为什么不做"收窄工具集"（曾考虑的方案 A）**：series 空时若禁用 query_*，则 agent 即使 `resolve_series` 成功，也无法在**同轮** `query_sales`（series_key 由前端经 ctx.json 提供，resolve 结果不回写 ctx）→ "银河E5销量"一轮查数体验被破坏，与起因相悖。故**弃 A**，采"全开工具 + 执行层判据"。

---

## 二、全面审查：基于代码实际发现的其他架构问题

### 问题 A：SYSTEM.md 角色与 AGENTS.md 不一致（行号校正）

- SYSTEM.md **L8**（非 L6）：`你是 **Prism-Agent**，一个面向用户的汽车数据分析助手。`
- AGENTS.md **L7**：`你是 **Prism-Agent**，一个面向汽车产品经理的助手。`
- SYSTEM.md **L10**（非 L8）限定"用户问的是业务问题…不是工程问题"——但用户现在也问通用问题（"帮我搜行业政策"）。

**改造**：SYSTEM.md **L8** 改"面向汽车产品经理的助手"；**L10** 补"或通用问题"。

### 问题 B：SYSTEM.md 纪律 4 未提 web（行号校正 + 与红线#9 去重）

- SYSTEM.md **L17**（非 L14）纪律 4：`只用语义工具查数据：query_reviews / …`

**注意（本轮新增）**：[AGENTS.md](file:///c:/Users/<you>/Desktop/Prism-Agent/AGENTS.md) **红线#9** 已规定"库数据优先…web_search 仅用于库内无此数据时补充查询（竞品动态/行业新闻/政策法规），最多 3 轮"。故只需**与红线#9 对齐措辞**，**不新造规则**。

**改造**：SYSTEM.md L17 补"库内无此数据时可用 web_search 补充（见红线#9，最多 3 轮）"。

### 问题 C：SYSTEM.md 纪律 3 与 EXCLUDE_TOOLS 重复（行号校正）

- SYSTEM.md **L16**（非 L13）纪律 3：`禁止动用工程工具：…`
- [pi_gateway.mjs L26-L30](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L26-L30) `EXCLUDE_TOOLS=[...]` ✓

提示词层禁 + 工具层 exclude 双保险。提示词是 best-effort（红线#5），工具层是硬拦。**不矛盾但冗余**。

**改造**：SYSTEM.md L16 简化为"工程工具已被系统禁用（闸1/闸2），无需关注"；**保留**提示词引导。

### 问题 D：SYSTEM.md 对象块 series 为空时显示"未指定"（行号校正）

- [index.ts L765](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L765)（非 L772）：`const warningsText = identityWarning || '无';`
- [index.ts L766-L771](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L766-L771)：fill `{series_key}`='未指定' / `{series_id}`='(待核验)' / `{warnings}`=warningsText

删身份强制后 series 空 → 显示"对象: 未指定（series_id=(待核验)）"+"数据缺口: 无" → **矛盾**（对象未指定却无缺口？）。

**改造**：series 空时 `{warnings}` 填"未选择车系，查汽车数据时请先确认对象"，而非"无"。**属提示词层（best-effort）**，须配一节的**执行层判据**（见 一、改造第 2 条）。

### 问题 E：identity 核验只在 seriesKey 非空时应有意义（行号校正）

- 实际 [index.ts L735](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L735)（L733 是注释"#4 死分支删除"）：`const res = await fetch(...series_key=${encodeURIComponent(seriesKey)})`

删身份强制后 seriesKey 为空 → fetch 发空 series_key → /identity/resolve fail-closed。非致命（agent 会提示），但浪费一次 fetch。

**改造**：加 `if (seriesKey)` 守卫，空则跳过 fetch。

### 问题 F：decideVerification REJECT_MSG_NO_TOOLS 假设用户必查汽车数据（行号校正 · 结论确认）

- [index.ts L376-L377](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L376-L377)（非 L374）

用户"帮我搜行业政策…规模约 5000 亿"→ agent 调 web_search、有数字、无 query_*。**tier=web → 走 verifyWeb**（[index.ts L853+](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L853)）→ 不经 decideVerification。**已实测确认不冲突。**

**不改** —— tier 路由正确处理。

### 问题 G：NEG_RE 窗口（**与 v8 块1 规格漂移 · 本轮修正定性**）

- [completion.ts L124-L128](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/completion.ts#L124-L128)（实际实现）：
```ts
for (const m of text.matchAll(new RegExp(ATTRIB_RE.source, 'g'))) {
  const i = m.index ?? 0;
  const before = text.slice(Math.max(0, i - 14), i);
  if (NEG_RE.test(before)) { hasNegativeContext = true; break; }   // 任一有否定 → 整条放行
}
if (!hasNegativeContext) { failures.push('…互为归因（越界）'); }
```
- **v8 块1 规格**：`if (!NEG_RE.test(before)) return { pass:false }` —— **任一**归因词**无**否定即 fail。

**这是规格—实现漂移（非"新发现的遗漏"）**：实际实现**弱于**规格——多个归因词时，只要**一个**有否定语境就整条放行，漏判"部分归因词未否定"的情形。

**改造（已裁定：① 对齐规格）**：逐词判定，**任一归因词"无否定"即 fail**；去掉原 `hasNegativeContext=true; break`（"一否全放"）逻辑。改法：

```ts
// ① 对齐规格（严）：任一归因词无否定语境 → 即判越界
const hits = [...text.matchAll(new RegExp(ATTRIB_RE.source, 'g'))];
const hasViolation = hits.some(m => {
  const i = m.index ?? 0;
  const before = text.slice(Math.max(0, i - 14), i);
  return !NEG_RE.test(before);   // 该归因词前无否定 → 真归因
});
if (hasViolation) {
  failures.push('市场侧与产品力互为归因（越界：市场侧数据不归因产品力）');
}
```

（修掉"多归因词时任一有否定就整条放行"的漏判；v8 块1 的"已知局限"同步移除该条。）

### 问题 H：ctx.json 写在 inflightLock 之前（✓ 属实 · 现役）

- [pi_gateway.mjs L399-L405](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L399-L405) 写 ctx.json
- [pi_gateway.mjs L409](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L409) 锁检查

同用户第二请求**先覆盖 ctx.json 再被锁拒绝** → 第一请求的 before_agent_start 读到第二请求的 series_key。

**改造**：ctx.json 写入移到 inflightLock 之后。**应做。**

**补充（本轮新增）**：ctx.json 为 **per-user 单文件**，前提是"每用户单并发"。移到锁后 → 被拒绝的请求不再覆盖 ctx ✓。但同用户多标签页并发的**进程级**问题与 v8 块5 C（进程池/排队/超时）同源，须在该块一并处理（本方案不越界）。

### 问题 I：scope bi_* 分支是死代码（行号校正）

- [index.ts L715-L717](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L715-L717)
- [chat.ts L22](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/lib/chat.ts#L22)（非 L23）：`const scope = opts?.scope ?? 'agent'` —— 前端只发 'agent'，bi_* 从未触发。

**改造**：不删（看板模式预留），标注"看板模式预留，当前 agent 场景不触发"。

---

## 三、改造清单（校正后）

| # | 文件:行号 | 改动 | 优先级 |
|---|---|---|---|
| 1 | ChatView.tsx L82 | 删 `if (!series)` 拦截 | 必做 |
| 2 | index.ts L724-L729 | 删 `if (!seriesKey) setActiveTools([]) 阻断`（删后 L718 全量工具自然生效） | 必做 |
| 2a | index.ts before_agent_start（L703 后） | **新增**：无条件 `appendEntry('prism-session-series-key', { series_key: seriesKey })`（含空值） | **必做（2b 依赖）** |
| 2b | index.ts agent_settled（L853 后） | **新增执行层判据**：读**最新一条** `prism-session-series-key` → tier=library 且值空 且 未调 `resolve_series` → reject（**身份证据仅认 `resolve_series`**） | **必做（红线#5/#7 替代护栏）** |
| 3 | SYSTEM.md L8 | 角色改"面向汽车产品经理的助手" | 应做 |
| 4 | SYSTEM.md L10 | 补"或通用问题" | 应做 |
| 5 | SYSTEM.md L17 纪律 4 | 补 web_search（与红线#9 对齐） | 应做 |
| 6 | SYSTEM.md L16 纪律 3 | 简化（工程工具已系统禁用） | 应做 |
| 7 | index.ts L766-L771 | series 空时 `{warnings}` 改引导非"无" | 应做 |
| 8 | index.ts L735 | seriesKey 空时跳过 fetch（加 `if (seriesKey)`） | 应做 |
| 9 | pi_gateway.mjs L399 | ctx.json 写入移到 inflightLock 后 | 应做 |
| 10 | index.ts L715-L717 | bi_* 标注"看板模式预留" | 低 |
| 11 | completion.ts L124-L128 | 与 v8 块1 规格对齐（逐词判定，任一归因词无否定即 fail） | 中（**已裁定 ①**） |

**共 13 项**（2 删 + 2 新增（2a 持久化 + 2b 判据）+ 9 改）。

---

## 四、删后行为（基于代码实测 + 执行层判据）

| 用户消息 | series_key | before_agent_start | agent 行为 | tier | 验证层 |
|---|---|---|---|---|---|
| "你好" | 无 | 全量工具 + SYSTEM.md 填"未指定"+ {warnings} 引导 | 闲聊 | none | 放行 |
| "帮我搜行业政策" | 无 | 同上 | web_search | web | verifyWeb（URL 真值集） |
| "银河E5销量" | 无 | 同上 | **先 resolve_series → 再 query_sales**（同轮） | library | verifyCompletion；**若未调 resolve_series → reject（判据 2b）** |
| "银河E5销量" | 有 | 自动核验 + 填"银河E5" | query_sales | library | verifyCompletion |
| "销量怎么样" | 无 | 同上 | 反问"你要查哪个车系？"（不查数） | none | 放行 |

---

## 五、验收

1. 不选车系能发消息
2. "你好" → 闲聊（tier=none 放行）
3. "帮我搜行业政策" → web_search（tier=web，verifyWeb）
4. "银河E5销量" → resolve_series + query_sales（tier=library）
5. **"银河E5销量" 但 agent 跳过 resolve_series → 被执行层判据 2b reject（红线#7）**
5b. **series_key 可被 agent_settled 读到**：`prism-session-series-key` 每轮无条件写入；**series_key 为空时也能读到空值**（不因空而丢失）；多轮时不读到上一轮残留（取最新）
6. 选了车系 → 自动核验（不变）
7. SYSTEM.md L8 角色对齐 AGENTS.md
8. SYSTEM.md L17 纪律 4 含 web_search（与红线#9 一致）
9. series 空时 SYSTEM.md {warnings} 引导非阻断
10. SYSTEM.md L16 纪律 3 已简化；EXCLUDE_TOOLS 仍硬拦（闸1）
11. ctx.json 写在 inflightLock 后（同用户第二请求不污染第一请求）
12. 问题 G 已按裁定 ① 落地：多归因词中任一"无否定"即判越界（不再"一否全放"）
13. smoke:all 全过

---

## 六、施工

13 项改动（2 删 + 2 新增 + 9 改）。**注意**：项 **2a（无条件持久化 series_key）与 2b（执行层判据）配套，不得省略**——2b 依赖 2a 提供的数据，缺 2a 则 2b 拿不到 series_key、判据空转；项 11 已裁定 ①。

---

## 七、收敛判定（第 2 轮）

**已收敛**：
- 全部行号校正（SYSTEM.md −2~3 行、index.ts L772→L765 / L733→L735 / L374→L376、chat.ts L23→L22、completion.ts L122-129→L124-L128）
- 问题 F/G 定性修正：F 结论成立（tier 路由已落地）；G 定为**规格—实现漂移**（属 v8 块1）
- 声明与 v8 计划的交叉（零节）：本方案为增补 change，不与已落地块冲突
- 问题 B 与红线#9 去重；问题 H 补进程池同源说明

**曾阻断收敛、已修复**：
- 原方案"只删不补"（删 L724-L729 后仅靠提示词引导）**违反红线#5/#7** → 已补 **2b 执行层判据**（tier=library 且 series_key 空 且 未调 resolve_series → reject）
- **2b 数据链缺口（用户 2026-10-07 指出）**：`seriesKey` 是 before_agent_start 局部变量、`agent_settled` 取不到，且 ctx.json 已被删 → 判据空转。**已补 2a**：无条件 `appendEntry('prism-session-series-key')` + agent_settled 取**最新一条**读取（含空值场景）
- 排除"收窄工具集"方案 A（会破坏一轮查数），采"全开工具 + 执行层判据"

**已裁定（用户 2026-10-07 拍板 · 零待裁定）**：
1. **问题 G → ① 对齐规格**：`verifyScope` 逐词判定，任一归因词"无否定"即 fail（见 二、问题 G 代码）。
2. **2b → 身份证据仅认 `resolve_series`**：`search_cars` 等不作身份证据；对齐 AGENTS.md 红线#7 原文，执行层与提示词同一口径。

**范围外（明确不做）**：v8 块1/2/3/4 已落地内容一律不重复；进程池/排队（属 v8 块5）。