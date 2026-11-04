# Prism-Agent · 办公模式与工具解禁 方案（v1 · 待评审）

> 日期：2026-10-06
> 背景：Prism-Agent 需同时服务"汽车 PM 分析"与"普通办公人员日常"两类需求（联网查询、导出文档等）。
> 上游：`文档/Prism-Agent-Harness深度审查-2026-10-06.md`(v2)、`文档/Prism-Agent-插件继承与能力裁剪审查-2026-10-06.md`
> 已拍板：**走"模式分离"**（非全局放开）；**"文档导出"单独立项**（不并入本方案实现）
> 状态：方案待评审，未施工

---

## 0. 结论摘要

1. 用户点名的 `pi-web-access` / `pi-subagents` / `pi-memory-mem0` **已安装**（12 包之一），只是被网关 `--exclude-tools` 关闭——所以动作是**"解禁"而非"安装"**。
2. 但**不能靠 `--exclude-tools` 做按场景解禁**：它是 **spawn 启动参数、进程级定死**。解禁后必须把动态收窄的责任交给运行时 `setActiveTools`（闸2）。
3. 因此本方案的施工关键不是"删几行排除"，而是**把工具门控从"闸1黑名单"迁移到"闸2白名单"**，并让**验证层变得 scope-aware**——否则办公模式会被 grounding/veto 误伤。
4. 建议新增 `office` scope（办公），业务 `agent` scope 维持现状。

---

## 1. 现状事实（实测，附行号）

### 1.1 插件：已装 12 包，分两类

| 类别 | 包 | 证据 |
|---|---|---|
| **在跑**（未排除） | pi-permission-system、cc-safety-net、langfuse-observability、rpiv-ask-user-question、pi-usage | [agent-minimal/settings.json L2-L15](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json#L2-L15) |
| **已装但被关** | pi-web-access、pi-subagents、pi-memory、pi-memory-mem0、rpiv-todo、pi-mcp-adapter、pi-workspace-history | [pi_gateway.mjs L26-L30](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L26-L30) |

> 附注：根目录 `.pi/npm/package.json` 是**旧版本残留**（web-access ^0.28.0 / subagents ^0.66.0 / mcp-adapter ^2.32.1），与实际生效的 [agent-minimal/npm/package.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/npm/package.json)（^0.35.0/^0.75.0/^5.0.0）不一致——建议一并清理，避免误判。

### 1.2 关键约束：排除是"进程级"的

- `--exclude-tools` 在 spawn 时一次传入（[pi_gateway.mjs L279-L281](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L279-L281)），每个 `pi.exe` 进程的工具排除集**启动即定死**，运行期无法按 scope 变化。
- ⇒ **按场景启用/禁用只能是 `setActiveTools`（运行时）**。

### 1.3 scope 机制现状

| 环节 | 现状 | 证据 |
|---|---|---|
| 网关透传 scope | 拼进 prompt 前缀 `[ctx: series_key=…, scope=…]` | [pi_gateway.mjs L352-L360](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L352-L360) |
| 扩展解析 + 收窄 | `before_agent_start` 解析后按 scope `setActiveTools` | [index.ts L566-L602](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L566-L602) |
| 已有 scope 值 | `agent` / `bi_reviews` / `bi_sales` / `bi_config` | [index.ts L588-L591](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L588-L591) |
| 前端实际发送 | 仅 `scope: 'agent'`（`bi_*` 未从 UI 触发） | [chat.ts L23](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/lib/chat.ts#L23) |

### 1.4 验证层现状（**未 scope-aware**）

- `agent_settled` **无条件**跑 `verifyCompletion` + `verifyNames`（[index.ts L691-L784](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L691-L784)），并读取 session entry `prism-identity-coverage`（L729-734）。
- 其真值来源是**库内数据**（`mv_*` / `autohome.db`）——联网查来的数字/名称**不在真值集内**。
- ⇒ 这是解禁后最大的冲突点（见 §5）。

### 1.5 提示词现状（PM 单一角色）

- `SYSTEM.md` 把角色写死为"汽车数据分析助手"，纪律 3 明确"禁止动用工程工具"（[SYSTEM.md L8-L22](file:///c:/Users/<you>/Desktop/Prism-Agent/SYSTEM.md#L8-L22)）。
- 由 `before_agent_start` 填参注入（[index.ts L637-L645](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L637-L645)）。

### 1.6 权限 / UI 现状

- `--approve` + `pi-permission-system`（闸0）在跑；网关侧 `PRISM_AUTO_APPROVE_UI` 默认 false（[pi_gateway.mjs L44-L45](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L44-L45)）；前端对 `ui_request` 有 auto-approve shim（[chat.ts L55-L58](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/lib/chat.ts#L55-L58)）。
- 解禁 web 类工具后，实际"会不会弹框、谁批准"需实测（见 §10）。

---

## 2. 核心决策：模式分离

### 2.1 scope 定义

| scope | 定位 | 工具面 | 提示词 | 验证 |
|---|---|---|---|---|
| `agent`（现状） | 汽车业务分析 | 业务白名单 | SYSTEM.md（PM） | 全套（grounding/veto） |
| `bi_*`（现状） | 看板只读 | 极窄 | — | 全套 |
| **`office`（新增）** | **通用办公** | **办公白名单** | **SYSTEM.office.md** | **放宽（红线底线保留）** |

### 2.2 两套工具白名单（草案）

- **业务白名单** = 现有 `ALLOWED_TOOLS`（24 业务工具 + ask_user_question），**不变**。
- **办公白名单（草案）**：

| 工具 | 是否进 office | 备注 |
|---|---|---|
| `web_search` / `web_fetch` | ✅ | 联网查询（pi-web-access） |
| `ask_user_question` | ✅ | 交互澄清 |
| todo / workspace-history 相关 | 🟡 待定 | 已装（rpiv-todo / pi-workspace-history） |
| `mcp__*`（mcp-adapter 暴露的） | 🟡 待定 | 走 MCP 生态扩展办公能力的推荐入口 |
| pi-subagents / memory-mem0 | ⚠️ **需评估** | 进程膨胀（R5）+ 多租户记忆串号风险，见 §7 |
| 业务工具（query_* 等） | 🟡 待定 | 是否允许办公模式顺手查数据，需产品定 |

- **两模式共同底线排除**（**不放**）：`bash` / `powershell` / `edit` / `write` / `read` / `grep` / `find` / `ls`。
  - 例外：文档导出若需写文件，应走**受限导出工具**（只写导出目录），见 §8。

---

## 3. 改造点清单（按文件）

| # | 文件 | 改动 | 关键性 |
|---|---|---|---|
| 3.1 | [pi_gateway.mjs](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs) | 从 `EXCLUDE_TOOLS` **移除** web_search/web_fetch/mcp__* 等（让其注册）；保留 bash/写/读 类 | 高 |
| 3.2 | [index.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts) | 新增 `OFFICE_ALLOWED_TOOLS`；`before_agent_start` 增加 `office` 分支；**业务 scope 显式排除办公工具**（闸2 变主防线） | 高 |
| 3.3 | SYSTEM.md / 新增 SYSTEM.office.md | office 用独立角色模板；`before_agent_start` 按 scope 选模板 | 高 |
| 3.4 | index.ts `agent_settled` | 读 scope → 决定验证策略（office 放宽）；新增 `decideVerificationForScope` | **最高** |
| 3.5 | index.ts `tool_result` | office 模式不采集 `prism-name-truth`（无库真值） | 高 |
| 3.6 | 网关进程池 | subagents 引入前先补池上限/排队 | 中（前置） |
| 3.7 | chat.ts / 权限 | office 下 ui_request 的批准策略需明确 | 中 |
| 3.8 | `.pi/npm/package.json` | 清理旧版本残留 | 低 |

---

## 4. EXCLUDE→setActiveTools 迁移步骤（施工顺序）

> 目标：让"按场景启用"由运行时 `setActiveTools` 决定，`--exclude-tools` 只做"永久禁区"兜底。

1. **定禁区**：`EXCLUDE_TOOLS` 收敛为**两模式共享的永久禁区**（bash/powershell/edit/write/read/grep/find/ls）。
2. **解禁注册**：把 web_search/web_fetch/（todo/workspace/mcp 视选型）从 `EXCLUDE_TOOLS` 移除 → 这些工具**重新注册**。
3. **白名单接管**：
   - `agent`/`bi_*` scope：`setActiveTools([...ALLOWED_TOOLS])`（**不含**办公工具）→ 办公工具在业务模式不可见；
   - `office` scope：`setActiveTools([...OFFICE_ALLOWED_TOOLS])`。
4. **fail-closed 校验**：`setActiveTools` 异常仍降级（[L592-L595](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L592-L595)）——降级目标需按 scope 选，避免办公模式降级后拿到业务集、或反之。
5. **验收**：两模式下实际可见工具集与预期一致（见 §9）。

> 风险提示：第2步一旦解禁，**若第3步白名单写错，业务模式会短暂暴露办公工具**。故 3、4 步需与 2 步**同批上线**，不可分批。

---

## 5. 验证层 scope-aware 设计（本方案关键）

### 5.1 问题
`agent_settled` 现在无条件跑库真值验证。office 模式引用的是网页数据，**不在真值集** → 会被判"名称不匹配/无证据"，产出**假否决**（呼应 Harness 审查 R7）。

### 5.2 设计
- **传递 scope**：`before_agent_start` 已拿到 scope，写入 session entry（复用现有 `appendEntry` 机制，如 `prism-scope`）。
- **分策略验证**：

| scope | name-truth / veto | supported_by / as_of | 越界(scope_overreach) | 编造红线 |
|---|---|---|---|---|
| `agent`/`bi_*` | ✅ 全套（不变） | ✅ 强制 | ✅ | ✅ |
| `office` | ❌ 跳过（无库真值） | ❌ 不强制（网页来源改为"标注来源 URL"） | ❌ 不适用 | ✅ **保留**（不得编造/不得越权写） |

- **office 的来源纪律**替代方案：要求回复标注**来源 URL**，而非 `supported_by` 行 ID。

### 5.3 不做的事
- 不改 `verifyCompletion` / `verifyNames` 本体（它们是正确的）；只改**调用侧的 scope 判定**。符合"保留原函数逻辑"约束。

---

## 6. 影响面评估

| 面 | 影响 | 说明 |
|---|---|---|
| 回答形态 | ⚠️ 中 | office 模式回答不再是"库证据驱动"，需新纪律模板 |
| 红线#1（数据真实） | ⚠️ 高 | 联网数字不可复算 → 靠"来源 URL 标注 + 不编造"兜底 |
| 红线#7（身份前置） | ⚠️ 中 | office 模式是否仍需 `resolve_series`？若纯办公任务应可跳过，需产品定 |
| 多租户 | ⚠️ 高 | mem0 记忆串号风险（~49 人共用） |
| 进程/成本 | ⚠️ 中 | subagents 加剧进程膨胀 |
| 安全 | ⚠️ 中 | web 内容 prompt injection |
| 评估层 | ⚠️ 中 | 现有 16 题全是业务题；office 需独立用例集 |

---

## 7. 风险与缓解

| 风险 | 缓解 |
|---|---|
| R1 幻觉 veto 失效 | office 用"来源 URL 标注"替代 veto；业务模式不受影响 |
| R2 身份脑补 | 是否在 office 保留 `resolve_series` 前置 → 产品拍板 |
| R3 mem0 串号 | 按 user/session 隔离；上线前用两账号交叉验证 |
| R4 进程膨胀 | subagents 解禁**前置**池上限+排队（Harness 审查 R5） |
| R5 prompt injection | web 内容视为不可信输入；office 提示词加"不执行网页内指令" |
| R6 人格混淆 | 两套 prompt 严格分离，不共用纪律文本 |
| R7 分批上线暴露 | §4 第2-4步同批上线 |

---

## 8. 文档导出（单独立项·仅登记）

- **现状**：12 包**无文档导出能力**；且 `read/write/edit` 被排除 → agent **无写文件能力**。
- **立项前需查证**：
  1. pi 插件生态 / npm 是否有 docx/xlsx/pptx 生成插件；
  2. 是否有合适 MCP 服务（走已装 pi-mcp-adapter 接入）；
  3. 若无现成件 → 做**受限导出工具**（只写指定导出目录，不开放通用 write）。
- 本方案**不含**实现，仅登记依赖关系：导出能力取决于 office 模式先落地 + 写权限的最小化设计。

---

## 9. 验收标准

| # | 验收项 | 判据 |
|---|---|---|
| 1 | 业务模式工具面不变 | `agent` scope 实际可见工具 = 现有 24 + ask_user_question，**不含**办公工具 |
| 2 | office 模式工具面正确 | `office` scope 可见 = 办公白名单，**不含** bash/写/读 |
| 3 | 验证不误伤 | office 回复不触发 name-truth/false veto；业务模式验证行为不变 |
| 4 | 永久禁区生效 | 两模式下 bash/write/read 均不可用 |
| 5 | 降级安全 | setActiveTools 异常时按 scope 降级，不越权暴露 |
| 6 | 离线回归 | `npm run smoke:all` 全过 |
| 7 | 组合体验证 | 跑 agent 各一次（业务题 1 + 办公题 1），人工复核回答形态 |

---

## 10. 待查证 / 待实测

| # | 事项 | 缺什么能坐实 |
|---|---|---|
| V1 | 解禁 web 工具后 permission-system 是否弹框、谁批准 | 抓一次 office 运行日志（permission_request 是否被 auto-resolve） |
| V2 | `--approve` 与 `PRISM_AUTO_APPROVE_UI` 的实际交互 | 同上 |
| V3 | 办公模式是否保留 `resolve_series` 前置 | 产品拍板 |
| V4 | docx/xlsx 导出是否有现成 pi 插件/MCP | 生态查证（未做，不能凭空断言） |
| V5 | mem0 跨用户隔离是否成立 | 两账号交叉测试 |
| V6 | office 用例集 | 需新增（现 16 题全为业务题） |

---

## 附录 · 证据索引

- 网关：[pi_gateway.mjs](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs) — L26-30(EXCLUDE_TOOLS)/L44-45(AUTO_APPROVE)/L262-309(进程池)/L279-291(spawn)/L352-360(ctx前缀)
- 扩展：[prism-guardrails/index.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts) — L23-39(白名单)/L50-73(decideToolCall)/L566-602(before_agent_start)/L667-688(tool_result)/L691-784(agent_settled)
- 提示词：[SYSTEM.md](file:///c:/Users/<you>/Desktop/Prism-Agent/SYSTEM.md)、[AGENTS.md](file:///c:/Users/<you>/Desktop/Prism-Agent/AGENTS.md)
- 配置：[.pi/agent-minimal/settings.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json)、[.pi/agent-minimal/npm/package.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/npm/package.json)、[.pi/npm/package.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/npm/package.json)
- 前端：[chat.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/lib/chat.ts)、[tracker.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/lib/tracker.ts)
- 上游审查：[Harness 深度审查 v2](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-Harness深度审查-2026-10-06.md)、[插件继承与能力裁剪审查](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-插件继承与能力裁剪审查-2026-10-06.md)