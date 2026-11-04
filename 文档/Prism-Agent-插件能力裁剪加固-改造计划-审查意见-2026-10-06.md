# Prism-Agent · 插件能力裁剪加固改造计划 · 审查意见 · 2026-10-06

> 审查对象：[Prism-Agent-插件能力裁剪加固-改造计划](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-插件能力裁剪加固-改造计划.md)
> 审查日期：2026-10-06
> 性质：**只读审查**（未改动任何代码 / 配置）
> 方法：逐条对照源码实测（`prism-guardrails/index.ts`、`pi_gateway.mjs`、两份 `settings.json`、`package.json`、pi `docs/settings.md`）
> 结论：**计划方向正确，但有 1 处必改（A 与现有常量重复）、2 处需补（B 观测链路、D 无数据通道）、若干需收敛** → 修订后即可施工

---

## 0. 摘要（一页）

| 级别 | 编号 | 问题 | 位置 |
|---|---|---|---|
| 高 | **F1** | A.1 "顶部加 `ALLOWED_TOOLS`"——**该常量已存在**（名为 `KNOWN_BUSINESS_TOOLS`，24 项），会重复定义、双源漂移 | [index.ts L24-33](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L24-L33) |
| 高 | **F3** | B 的观测前提未证实：`mapEvent` **未映射** `extension_ui_request`，该事件走另一条 `_handleLine` 通路；`/chat/stream` 走 `mapEvent` → 实测可能"看不到事件"而误判 | [pi_gateway.mjs L43](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L43)、[L155-165](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L155-L165)、[L385-388](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L385-L388) |
| 中高 | **F5** | D 缺可行机制：扩展在 pi 子进程内，`/health` 无从获得 `activeTools`；`console.error` 也进不了前端 | 计划 §D |
| 中 | **F2** | A 把 `agent` 模式收窄到业务白名单，会**顺带关掉**未被 `--exclude-tools` 排除的非业务工具（如 rpiv-ask-user-question 的提问能力）——需显式决策 | 计划 §A.2 |
| 中 | **F4** | C 结论**正确**（已由官方文档证实），但需补两条前置说明 | [settings.md L281](file:///c:/Users/<you>/Desktop/Prism-Agent/pi-windows-x64/docs/settings.md#L281) |
| 中 | **F8** | 施工顺序建议 B 前置（permission 若在 RPC 下阻塞，会影响 A 的验证路径） | 计划 §施工顺序 |
| 低 | **F6** | 计数口径不一致：注释 "23 工具" vs 常量 24 项 vs 计划 "24 业务工具" | [index.ts L584](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L584) |
| 低 | **F7** | 验收 3 "装一个测试插件" 偏重，宜改用静态/单测断言 | 计划 §验收 3 |

---

## 1. 计划正确处（先确认，避免误伤）

| 计划条目 | 核实结论 |
|---|---|
| R1 诊断（denylist 脆弱） | ✅ 成立：[pi_gateway.mjs L272](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L272) 为排除清单 |
| R3 诊断（agent 模式靠注释） | ✅ 成立：[index.ts L584](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L584) `// agent 模式不动（全 23 工具）`，`setActiveTools` 仅在 `bi_*` 分支调用 |
| A.2 `series_key` 空 → `setActiveTools([])` 已实现 | ✅ 成立：[index.ts L593-595](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L593-L595) |
| C（R6）两处 `extensions` 为死路径 | ✅ **官方文档证实**：[settings.md L281](file:///c:/Users/<you>/Desktop/Prism-Agent/pi-windows-x64/docs/settings.md#L281) "Paths in `.pi/settings.json` resolve relative to `.pi`" → `.pi/settings.json` 的 `.pi/extensions/…` = `.pi/.pi/extensions/…` 不存在；`agent-minimal/settings.json` 的 `.pi/extensions/…` 相对 `.pi/agent-minimal` 解析，同样不存在 |
| 验收 7 `smoke:all` 存在 | ✅ 成立：[package.json L14](file:///c:/Users/<you>/Desktop/Prism-Agent/package.json#L14) |
| R2/R5 处置（保留不删 / 轻量自检） | ✅ 合理，与审查结论一致 |

---

## 2. 必改项

### F1【高】A.1 会重复定义常量——应复用 `KNOWN_BUSINESS_TOOLS`

[index.ts L24-33](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L24-L33) **已经存在**一个 24 项的业务工具常量：

```
export const KNOWN_BUSINESS_TOOLS = new Set([
  'query_reviews','query_sales','query_config',
  'sentiment_overview','sentiment_trend','sentiment_dimension',
  'sentiment_posts','sentiment_competitive','sentiment_events',
  'search_cars','get_model_detail','get_model_generations','get_similar_models',
  'get_trims','get_config_detail','get_review_analysis','search_reviews',
  'get_dimension_reviews','get_energy_analysis','search_news',
  'get_dealer_price','get_sales_detail','score_models',
  'resolve_series',
]);
```

它正是 3 query + 6 sentiment + 14 Atuohome + resolve_series = **24 项**，且已被 `decideToolCall` 的 fail-closed 逻辑使用（[L65-67](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L65-L67)）。

**若按 A.1 再新增 `ALLOWED_TOOLS`，会得到两个同义常量**，后果：
- 两处需同步维护 → 漂移；
- 更糟：若新工具加进 `KNOWN_BUSINESS_TOOLS`（放行 `tool_call`）却漏加 `ALLOWED_TOOLS`（不激活），则**逻辑自相矛盾**——工具被放行但不可达，反向亦然。

**改法**：把 `ALLOWED_TOOLS` 改为**复用/重命名**现有 `KNOWN_BUSINESS_TOOLS`（`setActiveTools([...KNOWN_BUSINESS_TOOLS])`）。**单一来源**正是 A 的目标，重复定义会自我否定。

### F3【高】B 的观测链路未证实——先确认 `extension_ui_request` 投放路径

实测步骤 2 说"观察 pi_gateway 是否产出 `extension_ui_request` 事件"。但实测代码显示**存在两条不同通路**：

- `mapEvent`（[L43](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L43)）**没有** `extension_ui_request` 分支；而 `/chat/stream` 的循环用的是 `rpc.nextEvent()` + `mapEvent`（[L385-388](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L385-L388)）。
- `extension_ui_request` 实际由**另一条** `_handleLine` 处理（[L155-165](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L155-L165)）：非 AUTO_APPROVE 时 `uiRequests.set()` + `eventQueue.push()`，再由 `POST /ui-response`（[L466](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L466)）回填。

**风险**：若 `/chat/stream` 走的是 `mapEvent` 那条，而 `_handleLine` 那条**未与实际会话接线**，那么即便 permission 正常弹确认，前端也**收不到**——实测会得出"permission 没触发"的**错误结论**（把网关映射缺口误判为插件行为）。

**改法**：B 增加前置步骤 **B0**——先确认 `/chat/stream` 与 `_handleLine` 哪条是活动路径；若 `extension_ui_request` 不进 `/chat/stream`，则**先补 `mapEvent` 映射**（这本身也是一处既有缺口），再做 B 的实测。否则 B 的验收 4 无法成立。

### F5【中高】D 无数据通道——"启动自检"需先定义机制

计划 D 两条改动**当前都无落地路径**：

- "`index.ts` 扩展加载时 `console.error` 打印" —— 输出进的是 **pi 子进程的 stderr**，网关未捕获转发，**运营/前端都看不到**；
- "`pi_gateway /health` 增返回 `activeTools`" —— 扩展运行在 pi 子进程内，网关**无从获知** `setActiveTools` 的结果，**没有数据来源**（除非新建通道）。

**改法**：三选一——
1. 扩展在 `before_agent_start` 后**写状态文件**（如 `.pi/agent-minimal/state/active-tools.json`），网关 `/health` 读该文件；
2. 扩展经 pi 的**自定义事件/日志**上报，网关在事件流中捕获并缓存；
3. **退化为静态自检**（更轻）：单测断言"`KNOWN_BUSINESS_TOOLS` ⊆ 已注册工具"且"`--exclude-tools` 列表 ∩ `KNOWN_BUSINESS_TOOLS` = ∅"，不需要运行期通道。

推荐 3（成本最低、覆盖最关键的不变量），必要时再做 1。

---

## 3. 应改项

### F2【中】A 的"agent 模式收窄"有副作用，需显式决策

现状 `agent` 模式**不动**工具集 → 除 `--exclude-tools` 外，**未被排除的非业务工具仍然可达**（典型：`@juicesharp/rpiv-ask-user-question`，其工具名不在排除列表中）。改为 `setActiveTools(KNOWN_BUSINESS_TOOLS)` 后，这些工具**一并被关**。

- 若这是**有意**（业务对话只允许业务工具）→ 正确，但请在计划中**明写**"agent 模式将不再暴露 ask-user-question 等工具"，并同步 §验收。
- 若希望保留"向用户澄清提问"能力 → 白名单应为 `KNOWN_BUSINESS_TOOLS ∪ {ask_user_question 的实际工具名}`。
- **不要默认**：这是产品能力取舍，需拍板（当前计划未提，属隐藏行为变更）。

### F4【中】C 结论正确，但补两条前置说明

C 的方向与理由**已核实正确**（见 §1）。补：

1. **无回归**：项目 `.pi/settings.json` 的 `extensions` 本就失效，删除后**手动（非网关）运行 pi 也不会加载 guardrails**——与删除前一致，无功能回归（guardrails 一直只靠网关 `-e` 加载）。
2. **防双重注册**：删之前确认 `-e` 与 settings 声明**没有同时生效**（若同时生效会重复注册工具）。当前既然运行正常，说明仅一条生效，删除安全；但此点应写进施工检查项。

### F8【中】施工顺序：B 应前置

现顺序为 A → B。但 `AUTO_APPROVE` 关闭时 permission 确认**转发前端等待回填**（[L162-165](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L162-L165)）——若前端不回填，写操作会**挂起**。而 A 收窄工具集会改变触发路径。**先跑 B（实测 permission 行为 + 确认事件通路），再据结果决定 A 是否需调整**，避免在未知前提下先改 A。

---

## 4. 小问题

- **F6【低】计数口径**：注释 "全 23 工具"（[L584](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L584)）与常量 **24 项**、计划 "24 业务工具" 不一致。统一为 24，并说明 `resolve_series` 计入。
- **F7【低】验收 3 测试偏重**："装一个测试插件验证不可达" 需联网装包 + 改 settings，收益/风险不匹配。建议改为**静态/单测断言**（扩展 `smoke:guard`，[package.json L11](file:///c:/Users/<you>/Desktop/Prism-Agent/package.json#L11)）：断言 `KNOWN_BUSINESS_TOOLS` 覆盖全部已注册业务工具、且不含任何插件工具。

---

## 5. 收敛判定

- **已核验**：A/B/C/D 四节 + 验收 1–7 + 施工顺序，逐条对照 `index.ts` / `pi_gateway.mjs` / 两份 `settings.json` / `package.json` / pi `docs/settings.md`；常量清单、scope 分支、`setActiveTools` 调用点、`extension_ui_request` 两条通路、`AUTO_APPROVE` 闸、`smoke:all` 脚本——**均已人工确认**。
- **结论**：**计划方向正确、主体可用**；但 **F1（重复常量）会自我否定 A 的目标**、**F3（B 观测前提）会导致误判**、**F5（D 无通道）不可实施**——三者需修订后方可施工；F2/F4/F8 需收敛，F6/F7 微调。
- **无新的未核项 → 收敛。**

## 6. 修订后建议施工顺序

| 序 | 事项 | 变更 |
|---|---|---|
| 0 | **B0**：确认 `extension_ui_request` 投放路径（必要时补 `mapEvent` 映射） | 新增，B 的前置 |
| 1 | **B**（R4）：实测 permission RPC 确认通路 | 前置 |
| 2 | **A**（R1+R3）：复用 `KNOWN_BUSINESS_TOOLS` 作白名单 + `agent` 模式显式 `setActiveTools`（含 F2 决策） | 修正 A.1 |
| 3 | **C**（R6）：删两处死配置 + 双重注册检查 | 补说明 |
| 4 | **D**（R5）：启动自检——采用"静态断言"方案 3（或状态文件方案 1） | 修正机制 |
| 5 | 验证：`smoke:all` + tsc + 端到端（银河E5 分析 + 空系列阻断） | — |

---

# 附：v2 复审（第 2 轮）· 2026-10-06

> 复审对象：[改造计划 v2](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-插件能力裁剪加固-改造计划.md)
> 方法：逐条对照 v2 修订项 + 源码实测（`prism-guardrails/index.ts`、`pi_gateway.mjs`）
> 结论：**F1–F8 全部吸收、并补 E（版本 pin）**，质量明显提升；但发现 **1 处高风险反噬（N1）+ 1 处重点错位（N2，自我更正）**，需先处置再施工

## 0. 修订项核实（F1–F8 + E）

| 审查项 | v2 处置 | 核实 |
|---|---|---|
| F1 重复常量 | A.1 改为复用 `KNOWN_BUSINESS_TOOLS` | ✅ 到位（[index.ts L24-33](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L24-L33)） |
| F3 观测前提 | 加 B0 前置 | ✅ 到位（但重点需修正，见 N2） |
| F5 无数据通道 | D 改静态单测（方案 3） | ✅ 到位（但断言缺来源，见 N4） |
| F2 隐藏行为变更 | 白名单 ∪ `ask_user_question` | ⚠️ 方向对，但引入未验证工具名（见 N1） |
| F8 施工顺序 | B 前置 | ✅ 到位 |
| F6 计数口径 | 统一 24 | ✅ 到位 |
| F7 测试偏重 | 改静态单测 | ✅ 到位 |
| A-1 版本 pin | 新增 E | ✅ 到位（但取版本命令不适用 Windows，见 N5） |

## 1. 必改

### N1【高】A 的隐性反噬——可能把 agent 模式锁死成单工具

A.2 计划写 `pi.setActiveTools([...KNOWN_BUSINESS_TOOLS, 'ask_user_question'])`，而该调用**包在 try/catch 内，catch 是 fail-closed 到 `['resolve_series']`**（[index.ts L580-588](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L580-L588)）：

```
try {
  if (scope === 'bi_reviews') pi.setActiveTools([...]);
  ...
} catch (e) {
  // setActiveTools 失败 → fail-closed：只给 resolve_series
  try { pi.setActiveTools(['resolve_series']); } catch {}
}
```

**风险链**：若 `'ask_user_question'` 不是**真实注册的**工具名（或该插件在 prism 里未注册工具），而 pi 的 `setActiveTools` 对未知名**抛错** → 进入 catch → **agent 模式只剩 `resolve_series`，全线业务分析瘫痪**。

v2 自己已标注"工具名需 B0 实测确认"，**但在确认前就把未验证的名字写进 A，风险不对称**。

**处置**：施工前必须先确认两件事——
1. `rpiv-ask-user-question` 在 prism 中注册的**真实工具名**；
2. `setActiveTools` 对**未知名**的行为（抛错 / 静默忽略）。
在两者确认前，A **不得引入未验证的工具名**。

### N2【高，对第 1 轮 F3 的自我更正】B 的重点放错了

第 1 轮 F3 判断"`mapEvent` 无 `extension_ui_request` 分支 → 可能误判"。**复审后更正**：通路**其实存在**——

- [_handleLine L155-167](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L155-L167)：把 `extension_ui_request` 转成 `{type:'ui_request'}` 推入 `eventQueue`（非 AUTO_APPROVE 时另存 `uiRequests`）；
- `/chat/stream` 用 `nextEvent()` 消费队列（[L213-218](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L213-L218)、[L385-388](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L385-L388)），`mapEvent` 有 [`case 'ui_request': return event`](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L81-L82) 直通。

→ **B0 更可能是"确认存在"，而非"排雷"**。B 的真正风险点应改为：**前端收到 `ui_request` 后是否 `POST /ui-response` 回填、permission 是否在等待中挂起**（`AUTO_APPROVE` 关时走转发分支，[L162-165](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L162-L165)）。
**处置**：把 B 的重点从"事件能否到达"移到"**回填闭环 + 挂起行为**"。

## 2. 应改

- **N4【中】D 的断言缺来源**：要断言"`--exclude-tools` ∩ 白名单 = ∅"，但该列表是**内联在 spawn 参数里的字面量**（[pi_gateway.mjs L272](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L272)）→ 测试要么正则解析源码、要么复制一份（**又一双源**）。应先**把 exclude 列表提为可导出常量**。
- **N5【中】E 用了 `ls`**（`ls .pi/agent-minimal/npm/node_modules/<pkg>/package.json`）——**Windows 不可用**。改用 PowerShell（`Get-Content`）或直接 Read `package.json` 的 `version`。
- **N12【中】"pin 后升级需过 D 自检"落空**：D 只断言**工具集合关系**，与版本无关 → 防不住版本漂移。应给 D 补一条"**已安装版本 == settings 声明版本**"。
- **N6【中】范围膨胀**：**B 是"实测/调查"，A/C/D/E 是"改造"**，混在"一个 change"里会让"done"定义模糊。建议 B（含 B0）**拆为独立调查**，改造部分单独成一个 change。

## 3. 小问题

- **N3【低】两种"允许"概念并存**：allowlist = `KNOWN_BUSINESS_TOOLS ∪ {ask_user_question}`，但 `decideToolCall` 的 block 检查只用 `KNOWN_BUSINESS_TOOLS`（[L65-67](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L65-L67)）。建议让 **allowlist 成唯一 allow 源**，block 检查亦由其派生。
- **N9【低】验收 3 依赖未确认事实**（`ask_user_question` 真实工具名），应标注"待 B0 后确定"。
- **N10【低】§不做 中"pi 能力限制（`before_agent_start` 只能改 systemPrompt，无结构化 metadata 通道）"是未经证实的断言**——与本计划其他处的"实测"标准不一致，建议核实或降级措辞（否则 B2"留 v2"的理由可能不成立）。

## 4. 收敛判定（第 2 轮）

- **已核验**：v2 的 F1–F8 修订项 + 新增 E + 验收 1–8 + 施工顺序，逐条对照 `index.ts`（`KNOWN_BUSINESS_TOOLS`、`setActiveTools` 及其 try/catch、`decideToolCall`）与 `pi_gateway.mjs`（`mapEvent`、`_handleLine`、`nextEvent`、`AUTO_APPROVE` 分支）。
- **结论**：**v2 主体可用**；但施工前必做三件事——① 确认 `ask_user_question` 真实工具名 + `setActiveTools` 未知名行为（**N1**）；② 把 B 重点重定位到"回填闭环"（**N2**）；③ 提 exclude 列表为常量 + 修 `ls`（N4/N5）。
- **N1 一处不改，就可能让整个变更把 agent 打成"只能查身份"。**
- **无新的未核项 → 收敛。**

---

# 附：v3 复审（第 3 轮）· 2026-10-06

> 复审对象：[改造计划 v3](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-插件能力裁剪加固-改造计划.md)
> 方法：逐条对照 v3 修订项 + 源码实测（`prism-guardrails/index.ts`、`pi_gateway.mjs`）
> 结论：**N1–N5/N12 的实质问题已修好**，但 v3 引入 1 处规范歧义（P2，照字面实现会误伤）+ 1 处可行性拦路（P4）+ 4 处小切口 → **未收敛，需出 v4**

## 0. 修订项核实（N1–N12）

| 审查项 | v3 处置 | 核实 |
|---|---|---|
| N1 setActiveTools 反噬 | A 施工前验证 + 两路分支 + catch 修正 | ✅ 到位（A.3/A.5） |
| N2 B 重点错位 | B 改"回填闭环 + 挂起行为" | ✅ 到位（B0/B） |
| N4 exclude 双源 | 提 `EXCLUDE_TOOLS` 常量 | ✅ 到位 |
| N5 `ls` 不兼容 | 改 Read package.json | ✅ 到位 |
| N12 版本断言落空 | D 补版本一致性断言 | ✅ 到位 |
| N3 两种允许概念 | allowlist 唯一源，decideToolCall 派生 | ⚠️ 措辞有歧义（见 P2） |
| N6 范围膨胀 | 拒拆，理由"A 依赖 B" | ❌ 理由不成立（见 P1） |
| N9 验收 3 依赖未确认 | 验收 2 + 验收 9 覆盖 | ✅ 到位 |
| N10 pi 能力限制未证实 | 降级"待核实" | ✅ 到位 |

## 1. 本轮新增

### P2【高】A.4「block 检查改用 ALLOWED_TOOLS」会扩大拦截语义，可能误伤内置/交互工具

现有判定是**前缀门控**（[index.ts L63-67](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L63-L67)）：

```
const tn = toolName || '';
if (BUSINESS_PREFIXES.some(p => tn.startsWith(p)) && !KNOWN_BUSINESS_TOOLS.has(tn)) {
  return { block: true, reason: `fail-closed: 未知业务工具 ${tn}` };
}
```

它**只审"业务前缀工具"**；注释（[L44](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L44)）明说"pi 内置工具（read/glob/grep/bash 等）不在校验范围，归 `--exclude-tools` 管"。
若按字面实现成"**不在 ALLOWED_TOOLS 就 block**"，拦截范围会从"未知业务工具"**扩大到"一切非白名单工具"**——read/glob/交互工具全被拦。

**处置**：明确**仍是前缀门控**，仅把 `KNOWN_BUSINESS_TOOLS` 换成 `ALLOWED_TOOLS`（这才是"N3 单一来源"的正确形态）。

### P4【中】D 的静态单测加载方式未定——可能根本跑不起来

断言要"`KNOWN_BUSINESS_TOOLS` ⊆ 已注册业务工具"，就得拿到集合。但 [index.ts L17-18](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L17-L18) 是 `import ... from '../../../src/verify/completion.ts'`——**显式 `.ts` 后缀 + TS 语法**，普通 `node --test` 加载会失败（pi 用自己的 loader）。正则解析源码又脆。

**处置**：先定"测试如何拿到这两个集合"（pi 同款 loader / tsx / 还是解析源码），再写 D。

### P1【中】拒绝 N6 的理由不成立

v3（[L21](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-插件能力裁剪加固-改造计划.md#L21)）称"B 留本轮（**A 依赖 B 结果**）"。但 A 依赖的是 **N1 验证**（`setActiveTools` 行为），**不是 B**（permission 回填闭环）——两者独立。理由不成立 →"范围膨胀"顾虑**仍有效**，B 可拆为独立调查。

### P5【中】B 的修复选项含"自动批准策略"——方向反了

[B L81](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-插件能力裁剪加固-改造计划.md#L81) 把"前端弹框**或自动批准策略**"并列为挂起修复。**自动批准写操作 = 绕过 permission，与本计划的加固目标相反**，不能作等价选项。
**处置**：改为——超时后**拒绝**并提示，而非自动批准。

### P7【低】"query_*.ts 已退役"是未证实断言

§不做 [L123](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-插件能力裁剪加固-改造计划.md#L123) 用它给"D1 留 v2"作理由——与 N10 同一类问题（想当然）。需核实，否则 D1 的"留 v2"依据不成立。

### P3【低】A.5 的 catch 修正对 `agent` scope 定义模糊

"失败时保留 **scope 子集**"——但 `agent` scope 的集合**就是** ALLOWED_TOOLS 本身，失败后"子集"是什么？
**处置**：明确为**降级到 `[...KNOWN_BUSINESS_TOOLS]`**（去掉未验证的 `ask_user_question`）。

## 2. 收敛判定（第 3 轮）

- **已核验**：v3 的 N1–N12 修订项、A/B/C/D/E 五节改动、验收 1–9、施工顺序，逐条对照 `index.ts`（`KNOWN_BUSINESS_TOOLS`、`decideToolCall` 前缀门控、`setActiveTools` try/catch）与 `pi_gateway.mjs`（`EXCLUDE_TOOLS`、`mapEvent`、`_handleLine`）。
- **结论**：**未收敛**。N1–N5/N12 实质已修；但 **P2 是规范歧义（照字面实现会误伤）、P4 是可行性拦路（测试可能跑不起来）**，须先写清；P1/P5/P7/P3 各改一两句即可。
- **无未核项 → 但需出 v4**（预计改动很小：P2 措辞、P4 定 loader、P1 撤理由、P5 撤"自动批准"、P7 标待核实、P3 写清降级集）。

---

# 附：v4 复审（第 4 轮）· 2026-10-06

> 复审对象：[改造计划 v4](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-插件能力裁剪加固-改造计划.md)
> 方法：逐条对照 v4 修订项 + 源码/配置实测（`index.ts`、`pi_gateway.mjs`、`.pi/settings.json`、根 `package.json`）
> 结论：**P1–P7 全部吸收（P4 修法已实证成立）**，但新增 2 中（Q1 实证矛盾 / Q2 pin 被架空）+ 2 低 → **未收敛，需出 v5**

## 0. 修订项核实（P1–P7）

| 审查项 | v4 处置 | 核实 |
|---|---|---|
| P2 block 扩大化 | A.4 明确"仍是前缀门控" | ✅ 到位（L63） |
| P4 loader 拦路 | D 定 `node --test --import tsx` | ✅ **已实证成立**：`tsx@^4.19.0` 已装，且 [smoke:verify](file:///c:/Users/<you>/Desktop/Prism-Agent/package.json#L12) 已有先例（同用 `--import tsx` 加载 guardrails 的 test） |
| P1 拒拆理由 | 改"实测结果可能影响工具策略" | ⚠️ 理由仍牵强（见 Q4） |
| P5 自动批准 | 改"超时拒绝 + 提示" | ✅ 到位（L77） |
| P3 catch 降级 | 明确 `[...KNOWN_BUSINESS_TOOLS]` | ✅ 到位（L64） |
| P7 query_*.ts 退役 | 标"已核实" | ✅ 接受（作者核实） |

## 1. 本轮新增

### Q2【中，已实证】E 的 pin 会被项目级重复声明架空

[.pi/settings.json L2-6](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/settings.json#L2-L6) **无版本**地重复声明了 3 个包：

```
"packages": [
  "npm:pi-web-access",
  "npm:pi-mcp-adapter",
  "npm:pi-subagents"
]
```

这 3 个与 agent-minimal 的 12 包**完全重叠**。settings 合并语义为**项目级覆盖全局**（按包名去重、项目胜）→ 合并后这 3 个包的版本取**项目级（无版本）**，**agent-minimal 里 pin 的版本被覆盖掉**。

**处置**：E 必须同步处理 `.pi/settings.json`——**也 pin，或直接删这 3 条重复声明**；否则"12 包全 pin"实际只有 9 包生效。

### Q1【中】D 的断言与 A 的 N1 分支自相矛盾

D 断言（[v4 L97](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-插件能力裁剪加固-改造计划.md#L97)）`ALLOWED_TOOLS ⊆ 已注册业务工具`。但当 N1 走**"不抛错"分支**时，`ALLOWED_TOOLS` 含 `ask_user_question`——**它不是业务工具**（无业务前缀）→ **该断言必然失败**。

**处置**：拆为两条——
- `KNOWN_BUSINESS_TOOLS ⊆ 已注册业务工具`
- `ALLOWED_TOOLS = KNOWN_BUSINESS_TOOLS ∪ {可选 ask_user_question}`

### Q3【低】C 的前提需由 C 的第 1 步反向确认

"两处 extensions 均为死路径"是 C 的立论基础。注意 [.pi/settings.json L8](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/settings.json#L8) 的路径是 `.pi/extensions/...`——**若相对项目根解析则"活"，相对 `.pi/` 解析才"死"**。
C 的"移除 -e"测试须覆盖两种结果：若移除后 guardrails **仍加载** → 该路径是活的 → C 从"删死配置"升级为"**删活配置 + 顺带修当前的双重注册**"，结论要改。

### Q4【低】B 留本轮的（新）理由仍牵强

v4 改理由为"实测结果可能影响工具策略"（[L17](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-插件能力裁剪加固-改造计划.md#L17)）。但 B 测的是 **permission 写操作批准**，与**工具白名单策略**无关 → N6 "范围膨胀"顾虑**仍未真正消解**（可不改，但理由站不住）。

## 2. 收敛判定（第 4 轮）

- **已核验**：v4 的 P1–P7 修订项、A/B/C/D/E 五节、验收 1–9、施工顺序；并实证了 P4（tsx 已装 + smoke:verify 已有同款先例）与 Q2（`.pi/settings.json` 3 包无版本重复声明）。
- **结论**：**未收敛（差一步）**。P1–P7 已消；但 **Q1、Q2 是逻辑矛盾**（D 断言会失败 / E 的 pin 失效），须改；Q3、Q4 是表述。预计 **v5 只改 4 处、不动骨架**。
- **无未核项 → 需出 v5。**