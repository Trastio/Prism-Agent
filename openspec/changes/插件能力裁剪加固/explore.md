# 插件能力裁剪加固 · Step 1 Explore

> 2026-10-06
> change: 插件能力裁剪加固
> 对象：[改造计划 v5](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-插件能力裁剪加固-改造计划.md)
> 性质：探查代码现状（不写方案，方案在 Step2 propose）

---

## 1. 探查方法

主会话亲自 grep + Read + Bash 核验（不依赖审查报告，独立验证）

---

## 2. 现状清单（证据为文件:行号）

### 2.1 KNOWN_BUSINESS_TOOLS（已存在，24 项 Set）

- `index.ts:24` `export const KNOWN_BUSINESS_TOOLS = new Set([...])` 24 项
- `index.ts:34` `BUSINESS_PREFIXES = ['query_','sentiment_','search_','get_','score_','resolve_']`
- `index.ts:65` decideToolCall 前缀门控：`BUSINESS_PREFIXES.some(p => tn.startsWith(p)) && !KNOWN_BUSINESS_TOOLS.has(tn)` → block

### 2.2 setActiveTools 调用点

- `index.ts:581-583` bi_reviews/sales/config 三 scope 各自白名单
- `index.ts:584` 注释"agent 模式不动（全 23 工具）"——**R3：agent 模式不调 setActiveTools**
- `index.ts:586-588` catch fail-closed 到 `['resolve_series']`
- `index.ts:593-595` series_key 空 → `setActiveTools([])`（已实现）

### 2.3 --exclude-tools（denylist）

- `pi_gateway.mjs:272` 内联字面量（非可导出常量）
- 排除：bash/powershell/edit/write/read/grep/find/ls/web_search/web_fetch + mcp__pi_memory/mcp__pi-subagents/mcp__pi-web-access/mcp__pi-memory-mem0/mcp__pi-mcp-adapter/mcp__pi-todo/mcp__pi-workspace-history

### 2.4 两份 settings.json

**agent-minimal/settings.json**（12 包，仅 2 pin）：
- pin：cc-safety-net@2.4.15、@langfuse/pi-observability-plugin@0.1.2
- 未 pin：10 个浮动
- extensions: [".pi/extensions/prism-guardrails/index.ts"]（R6 死/活待 Q3 验证）

**.pi/settings.json**（3 包无版本重复声明）：
- pi-web-access / pi-mcp-adapter / pi-subagents（与 agent-minimal 重叠，Q2 架空 pin）
- extensions: [".pi/extensions/prism-guardrails/index.ts"]（同 R6）

### 2.5 ask_user_question 工具名

- `.pi/agent-minimal/npm/node_modules/@juicesharp/rpiv-ask-user-question/ask-user-question.ts:74` `ASK_USER_QUESTION_TOOL_NAME = "ask_user_question"`
- **N1 待验证**：setActiveTools(['ask_user_question']) 是否抛错（RPC 模式插件可能未注册工具）

### 2.6 mapEvent ui_request 通路（N2 已确认存在）

- `pi_gateway.mjs:81` `case 'ui_request': return event`（mapEvent 直通）
- `pi_gateway.mjs:155-167` _handleLine 把 extension_ui_request 转 {type:'ui_request'} 推 eventQueue
- `/chat/stream` nextEvent 消费 eventQueue → mapEvent → 前端
- **通路存在**，B 重点改"回填闭环 + 挂起行为"

### 2.7 12 包实际版本（E pin 用）

| 包 | 版本 |
|---|---|
| @gotgenes/pi-permission-system | 39.0.3 |
| cc-safety-net | 2.4.15 |
| @langfuse/pi-observability-plugin | 0.1.2 |
| pi-web-access | 0.35.0 |
| @juicesharp/rpiv-ask-user-question | 2.12.0 |
| @narumitw/pi-usage | 0.61.2 |
| pi-subagents | 0.75.0 |
| pi-memory | 0.4.2 |
| @amaster.ai/pi-memory-mem0 | 0.1.22 |
| @juicesharp/rpiv-todo | 2.12.0 |
| pi-mcp-adapter | 5.0.0 |
| pi-workspace-history | 0.4.8 |

---

## 3. v5 计划与现状对齐

| v5 项 | 现状核验 |
|---|---|
| A 复用 KNOWN_BUSINESS_TOOLS | ✅ L24 已存在 24 项 Set |
| A agent 模式显式 setActiveTools | ❌ 当前 L584 注释"不动"，需改 |
| A decideToolCall 前缀门控换常量 | ✅ L65 现用 KNOWN_BUSINESS_TOOLS.has，换 ALLOWED_TOOLS 需注意 Set vs 数组 |
| B ui_request 通路 | ✅ 已确认存在（N2） |
| C extensions 死/活 | 🟡 Q3 待移除 -e 测试 |
| D EXCLUDE_TOOLS 常量 | ❌ 当前 L272 内联字面量 |
| E 12 包版本 | ✅ 已实测（§2.7） |
| E .pi/settings.json 3 重复 | ✅ Q2 确认（web-access/mcp-adapter/subagents） |

---

## 4. 待办清单（按 v5 施工顺序）

### N1 验证（A 前置）
- N1.1 验证 setActiveTools(['ask_user_question']) 是否抛错（发真实 RPC 请求测）
- N1.2 验证 setActiveTools(['未知名']) 行为

### B（permission 实测）
- B.1 发触发 permission 批准的消息
- B.2 观察前端 ui_request 回填闭环
- B.3 观察 permission 挂起行为 + 加超时拒绝

### A（白名单 + 显式 setActiveTools）
- A.1 新增 ALLOWED_TOOLS = [...KNOWN_BUSINESS_TOOLS]（或含 ask_user_question，视 N1）
- A.2 before_agent_start agent 模式调 setActiveTools(ALLOWED_TOOLS)
- A.3 decideToolCall 前缀门控换 ALLOWED_TOOLS（注意 Set.has vs 数组.includes）
- A.4 catch 降级到 [...KNOWN_BUSINESS_TOOLS]（去 ask_user_question）
- A.5 删 L584 注释

### C（死配置 + Q3 测试）
- C.1 移除 -e 测试 guardrails 是否加载（覆盖活/死两种）
- C.2 据结论删两处 extensions 声明
- C.3 加注释

### D（静态自检）
- D.1 pi_gateway 提 EXCLUDE_TOOLS 常量
- D.2 tsx 单测：KNOWN_BUSINESS_TOOLS ⊆ 已注册 + ALLOWED_TOOLS 结构 + EXCLUDE_TOOLS ∩ ALLOWED_TOOLS = ∅ + 版本一致性

### E（版本 pin + Q2）
- E.1 agent-minimal settings.json 12 包加版本
- E.2 删 .pi/settings.json 3 条重复声明

---

## 5. 自查发现的 3 个施工细节（计划没写清）

1. **N1 验证方法**：需在真实 pi RPC 子进程发带 ask_user_question 的请求看是否报错
2. **Set vs 数组**：KNOWN_BUSINESS_TOOLS 是 Set（.has），ALLOWED_TOOLS 若是数组需改 .includes
3. **C 移除 -e 测试**：-e 可能是 pi 启动必需参数，移除可能报错而非"不加载 guardrails"。改用"临时改 extension 路径看是否报错"更安全

---

## 6. 下一步

进 Step2 propose：写 proposal.md + design.md + tasks.md 四件套。
