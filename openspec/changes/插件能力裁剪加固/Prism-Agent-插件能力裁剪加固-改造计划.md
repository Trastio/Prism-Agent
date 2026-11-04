# Prism-Agent · 插件能力裁剪加固改造计划 v6

> 2026-10-06 · 修订版（融合 v5 复审 Q5-Q6 修正 + 承接 v5 自主判断）
> 取代 v5（v5 有 Q5 `ALLOWED_TOOLS` 形态矛盾（数组却调 `.has()`）+ Q6 D 断言无独立来源（可能恒真））
> 判据来源：[插件裁剪审查 v4 复审](../../../文档/Prism-Agent-插件能力裁剪加固-改造计划-审查意见-2026-10-06.md#L288) + 源码实测
> 性质：**改造计划**（待审阅，审阅通过按十步流程推进）
> 范围：**一个 change 做完** A/B/C/D/E 五项

---

## v5 相对 v4 的修订摘要

| 审查项 | 修订 |
|---|---|
| **Q2** E 的 pin 被项目级重复声明架空 | E 同步删 .pi/settings.json 3 条重复声明（web-access/mcp-adapter/subagents），让 agent-minimal pin 生效 |
| **Q1** D 断言与 N1 分支矛盾 | D 拆两条断言：KNOWN_BUSINESS_TOOLS ⊆ 已注册业务工具 + ALLOWED_TOOLS = KNOWN_BUSINESS_TOOLS ∪ {可选 ask_user_question} |
| **Q3** C 立论风险（extensions 路径可能"活"） | C 第1步覆盖两种结果：若移除 -e 后 guardrails 仍加载 → 改"删活配置 + 修双重注册" |
| **Q4** B 留本轮理由牵强 | 改"实测 ui_request 通路状态影响 A 的 catch 逻辑设计"；接受可拆但不拆（同 change 效率高） |
| **Q5** `ALLOWED_TOOLS` 形态矛盾（数组却调 `.has()`） | A 明确 `ALLOWED_TOOLS` 为 **Set**；`setActiveTools` 调用处用 `[...ALLOWED_TOOLS]` 展开 |
| **Q6** D 断言无独立来源（可能恒真） | D 先定"已注册业务工具"来源：导出 `REGISTERED_TOOL_NAMES` 或 mock pi 捕获 `registerTool` |

---

## 我自己的判断（不只是吸收审查）

经过四轮审查，我意识到这个 change 的核心矛盾是：**"白名单"这个概念在三个地方各有一套逻辑，必须统一为单一来源**。

1. `KNOWN_BUSINESS_TOOLS`（index.ts:24）—— decideToolCall 前缀门控用，判断"业务工具是否已知"
2. `setActiveTools` 的 scope 白名单（index.ts:581-583）—— 判断"哪些工具可发放"
3. `--exclude-tools`（pi_gateway:272）—— 判断"哪些工具要排除"

v4 把 1 和 2 统一了（ALLOWED_TOOLS），但 3 还是独立的 denylist。**我的判断：3 应该退化为兜底，不作为主要防线，但必须与 1/2 不矛盾**（D 的断言 `EXCLUDE_TOOLS ∩ ALLOWED_TOOLS = ∅` 就是保证这个）。

另外，**Q2 暴露了一个更深的问题**：.pi/settings.json 3 条重复声明本身就是 R2"装而不用"的残留——这 3 个包（web-access/mcp-adapter/subagents）在 agent-minimal 已声明，项目级又声明一次无版本，既架空 pin 又说明配置漂移。**删这 3 条不仅是 Q2 的修法，也是 R2 的部分清理**——虽然不删包，但删重复声明让配置单一来源。

---

## 问题诊断（七项风险）

| 风险 | 级别 | v5 处置 |
|---|---|---|
| R1 黑名单兜底脆弱 | 高 | A 改 allowlist（复用 KNOWN_BUSINESS_TOOLS） |
| R3 关键不变量靠注释 | 中 | A agent 模式显式 setActiveTools |
| R4 permission RPC 未验证 | 低 | B 实测（回填闭环 + 挂起行为） |
| R6 死配置 | 低 | C 删两处 extensions 声明（Q3 覆盖活/死两种） |
| R5 无启动自检 | 低 | D 静态单测断言（tsx loader，拆两条断言 Q1） |
| R2 装而不用 | 中 | 保留不删包，但删 .pi/settings.json 重复声明（Q2 部分） |
| A-1 版本未 pin | 中 | E pin 12 包 + 删项目级重复声明（Q2） |

---

## 改造范围（5 项）

### A. R1+R3：单一白名单 + agent 模式显式 setActiveTools

> F1：复用 KNOWN_BUSINESS_TOOLS
> N1：ask_user_question 能否加白名单需施工前验证
> P2：仍是前缀门控，只换常量名
> P3：catch 降级集明确

**N1 施工前验证（必做）**：
1. 确认 `ask_user_question` 真实工具名（已实测：`"ask_user_question"`）
2. 验证 `pi.setActiveTools(['ask_user_question'])` 是否抛错
3. 验证 `pi.setActiveTools(['未知名'])` 行为（抛错/静默忽略）

**根据验证结果分两路**：
- **若不抛错** → `ALLOWED_TOOLS = new Set([...KNOWN_BUSINESS_TOOLS, 'ask_user_question'])`
- **若抛错** → `ALLOWED_TOOLS = new Set([...KNOWN_BUSINESS_TOOLS])`（歧义澄清走 hook）

**改动**：
1. **Q5**：`index.ts` 顶部新增 **Set 形态**的 `ALLOWED_TOOLS = new Set([...KNOWN_BUSINESS_TOOLS, ...(N1 通过 ? ['ask_user_question'] : [])])`（`decideToolCall` 用 `.has()` 故须 Set；`setActiveTools` 处展开为数组）
2. `before_agent_start` 所有 scope 显式调 setActiveTools：
   - `agent` → `pi.setActiveTools([...ALLOWED_TOOLS])`
   - `bi_reviews/sales/config` → 各自子集
   - `series_key` 空 → `pi.setActiveTools([])`（已实现）
3. **P2**：`decideToolCall` 仍是前缀门控（`BUSINESS_PREFIXES.some(...) && !ALLOWED_TOOLS.has(tn)`），`ALLOWED_TOOLS` 为 Set 故 `.has()` 成立；只换常量名，前缀门控逻辑不变
4. **P3**：catch 降级——agent scope 失败 → `pi.setActiveTools([...KNOWN_BUSINESS_TOOLS])`（去 ask_user_question）；bi_* 失败 → 保留各自子集
5. 删 index.ts:584 注释"agent 模式不动"

### B. R4：permission-system RPC 实测

> N2：通路已确认存在，重点改"回填闭环 + 挂起行为"
> P5：修复改"超时拒绝"（删自动批准）
> Q4：留本轮（ui_request 通路状态影响 A 的 catch 逻辑设计）

**B 实测重点**：
1. 发触发 permission 批准的消息（管理者写操作）
2. 观察前端收到 ui_request 后是否 POST /ui-response 回填
3. 观察 permission 等待回填时是否挂起
4. 若挂起无超时 → 加 uiRequests 超时清理 + **超时拒绝并提示**（P5）

### C. R6：死配置清理（Q3 覆盖活/死两种）

> Q3：extensions 路径可能"活"（相对项目根）而非"死"（相对 .pi/）。C 第1步须覆盖两种结果。

**改动**：
1. **Q3 第1步**：临时移除 pi_gateway 的 `-e` 参数，启动 pi，确认 guardrails 是否加载：
   - 若**不加载**（死路径）→ 按"删死配置"处理
   - 若**仍加载**（活路径）→ 按"删活配置 + 修双重注册"处理（-e 与 settings 同时生效）
2. 据第1步结论删 `agent-minimal/settings.json` extensions 字段
3. 据第1步结论删 `.pi/settings.json` extensions 字段
4. 加注释"extension 通过 pi_gateway -e 显式加载"

### D. R5：静态自检（tsx loader + 拆断言 Q1 + 版本断言 N12）

> P4：tsx loader（已实证：tsx@^4.19.0 已装，smoke:verify 已有先例）
> Q1：拆两条断言（ALLOWED_TOOLS 含 ask_user_question 时不是业务工具，不能断言 ⊆ 已注册业务工具）
> N4：exclude 列表提常量
> N12：补版本断言

**改动**：
- `pi_gateway.mjs` 顶部提 `EXCLUDE_TOOLS` 可导出常量
- 单测用 `node --test --import tsx`
- **Q6 先定"独立来源"**：`KNOWN_BUSINESS_TOOLS ⊆ "已注册业务工具"` 里的"已注册业务工具"必须有**独立来源**——
  - 方案 A（推荐）：index.ts 导出 `REGISTERED_TOOL_NAMES`（在 `registerPrismTools` 内 `registerTool` 时累积）
  - 方案 B：测试注入 mock `pi`，捕获 `registerTool` 收到的名字
  - **禁止**复用 `KNOWN_BUSINESS_TOOLS` 自身（否则断言退化为 `X ⊆ X` 恒真、无意义）
- **Q1 拆断言**：
  - `KNOWN_BUSINESS_TOOLS ⊆ REGISTERED_TOOL_NAMES`（业务工具全注册）
  - `ALLOWED_TOOLS ⊇ KNOWN_BUSINESS_TOOLS` 且 `ALLOWED_TOOLS \ KNOWN_BUSINESS_TOOLS ⊆ {ask_user_question}`（结构断言，非 ⊆ 业务工具）
  - `EXCLUDE_TOOLS ∩ [...ALLOWED_TOOLS] = ∅`（白名单工具没被 exclude）
  - **N12**：已安装版本 == settings.json 声明版本

### E. A-1：版本 pin + 删项目级重复声明（Q2）

> Q2：.pi/settings.json 3 包无版本重复声明，架空 agent-minimal pin。必须同步处理。

**改动**：
- Read `.pi/agent-minimal/npm/node_modules/<pkg>/package.json` 取 version（N5）
- `agent-minimal/settings.json` 12 包加精确版本号
- **Q2**：删 `.pi/settings.json` 的 3 条重复声明（web-access/mcp-adapter/subagents）——让 agent-minimal pin 生效 + 消除配置漂移
- 升级需过 D 静态自检（含 N12 版本断言）

---

## 不做（本轮边界）

- **R2 删插件包**：保留不删包（v2 灵活性），但删 .pi/settings.json 重复声明（Q2 部分）
- **B2 上下文对象化**：pi 能力限制（待核实，暂留 v2）
- **C 进程治理三件套**：开发期单用户不阻塞，留上线前 gate
- **D1 TS/HTTP 双实现收敛**：query_*.ts 已退役（已核实），verify/* 保留，留 v2
- **mem0/subagents/web-access 开放评估**：留 v2

---

## 验收

1. `ALLOWED_TOOLS` 单一来源（复用 KNOWN_BUSINESS_TOOLS，无重复常量）
2. N1 验证完成：setActiveTools 对 ask_user_question 行为已确认
3. agent 模式调 setActiveTools（非注释维持），catch 降级到 [...KNOWN_BUSINESS_TOOLS]（P3）
4. decideToolCall 仍是前缀门控（P2：只换常量名）
5. permission 回填闭环通 + 挂起超时拒绝（B，P5）
6. settings.json extensions 删除（C，Q3 覆盖活/死两种结论）
7. EXCLUDE_TOOLS 常量 + 静态单测通过（Q1 拆断言 + Q6 独立来源 + N12 版本断言）
8. 12 包版本全 pin + .pi/settings.json 3 条重复声明删（E，Q2）
9. smoke:all 全过 + tsc 零错 + 端到端（银河E5 + 空系列阻断 + 歧义澄清）

---

## 施工顺序

| 序 | 事项 | 说明 |
|---|---|---|
| **N1 验证** | setActiveTools 对 ask_user_question 行为 | A 前置 |
| **B** | permission 回填闭环 + 挂起超时拒绝实测 | R4 |
| **A** | ALLOWED_TOOLS + agent 显式 setActiveTools + 前缀门控换常量 + catch 降级 | R1+R3 |
| **C** | Q3 第1步（移除 -e 测试活/死）→ 据结论删配置 | R6 |
| **D** | EXCLUDE_TOOLS 常量 + tsx 单测（Q1 拆断言 + Q6 独立来源 + N12 版本） | R5 |
| **E** | pin 12 包 + 删 .pi/settings.json 3 条重复（Q2） | A-1 |
| **验证** | smoke:all + tsc + 端到端 | |

**按十步流程走**：explore（审查报告已是）→ propose（本文）→ 3.5 自查 → Step5 施工 → Step6-10。

**等审阅通过再施工。**
