# Prism-Agent · Harness 实测盘点与审查（v2 · 全仓勘误版）· 2026-10-06

> **本版方法**：不预设"应该有哪些 harness"，而是用 Glob/Grep 扫全仓 → 逐个实读 → 判定 alive/dead。
> **v1 勘误**：v1 的探索路径被设计稿与历史记忆牵引，存在 5 处硬伤（见 §0）。本版以**代码/运行日志为唯一事实源**。
> 审查方式：只读。所有结论附文件 + 行号，可复算。

---

## 0. 勘误声明（v1 → v2 纠正的硬伤）

| # | v1（错误） | v2（实测） | 证据 |
|---|---|---|---|
| 1 | 称 `.pi/settings.json` 声明 3 个包并 pin | **项目 `.pi/settings.json` 实为 `packages: []`**；12 个包声明在 **`.pi/agent-minimal/settings.json`** | [.pi/settings.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/settings.json) / [agent-minimal/settings.json L2-L15](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json#L2-L15) |
| 2 | **完全漏掉** `pi-permission-system` 这一层权限 harness | 它是**已安装且真实运行**的闸（工具级批准），有运行日志 | [agent-minimal/settings.json L3](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json#L3) / [permission-review.jsonl](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/extensions/pi-permission-system/logs/pi-permission-system-permission-review.jsonl) |
| 3 | 称"埋点未实现、DAU/时长不可测"（沿袭记忆） | **前端埋点已实现**：`tracker.ts`（page_view/active_tick/feedback/settled + VIN 脱敏）→ `/events` | [tracker.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/lib/tracker.ts) |
| 4 | 未提及存在**第二套 tool_call 护栏** `src/tools/guardrail.ts` | 它**存在但是死码**，且白名单已过期（含不存在的工具） | [guardrail.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/tools/guardrail.ts) |
| 5 | 称 langfuse"未接" | 区分两件事：**pi observability 插件已配 key**（agent-minimal/langfuse.json）+ 有 trace；**仅 eval 写回函数是桩** | [langfuse.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/langfuse.json) vs [langfuse_writer.ts L36-L44](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/langfuse_writer.ts#L36-L44) |

> 教训：v1 把"设计稿说有的"当成了"实际有的"，又把"记忆说没有的"当成了"实际没有的"。二者都翻过车。

---

## 1. 实际存在的 Harness 全景（实测）

### 1.1 执行层护栏——本项目实际有 6 道"闸"（非 1 道）

| 闸 | 机制 | 载体 | 状态 | 证据 |
|---|---|---|---|---|
| **闸0** | **工具级权限批准**（弹确认框）| `@gotgenes/pi-permission-system@39.0.3`（npm 包，装在 agent-minimal）| ✅ 运行（有落盘日志） | [settings L3](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json#L3) / [permission-review.jsonl L91](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/extensions/pi-permission-system/logs/pi-permission-system-permission-review.jsonl) |
| **闸0b** | GitHub 读写安全网 | `cc-safety-net@2.4.15` | ✅ 已装 | [settings L4](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json#L4) |
| **闸1** | `--exclude-tools` 黑名单（剔 bash/写/读/web/mcp/记忆/子代理） | 网关 spawn 参数 | ✅ 运行 | [pi_gateway.mjs L26-L30 / L279-L281](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L26-L30) |
| **闸2** | `setActiveTools` 白名单（按 scope 收窄；空车系=真阻断） | extension `before_agent_start` | ✅ 运行 | [index.ts L587-L602](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L587-L602) |
| **闸3** | `decideToolCall` 行为拦截（裸SQL/DB直连/敏感文件/未知业务工具） | extension `tool_call` | ✅ 运行 | [index.ts L50-L73 / L659-L664](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L50-L73) |
| **闸4** | 输出验证（口径 as_of / 名称真值 / 完成验证器 + 回灌一次） | extension `tool_result` + `agent_settled` | ✅ 运行 | [index.ts L667-L784](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L667-L784) |
| **闸4b(UI)** | UI 请求自动批准 shim（开发期 options[0]/confirm=true） | 前端 `chat.ts` + 网关 `PRISM_AUTO_APPROVE_UI` | ✅ 运行（开发期；生产默认关） | [chat.ts L55-L58](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/lib/chat.ts#L55-L58) / [pi_gateway L44-L45](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L44-L45) |

> 关键认知：**工具级批准（闸0）与行为级拦截（闸3）是两层，叠加使用**——index.ts L655-658 的注释已明确此分工。v1 只看到闸3。

### 1.2 执行层其余 harness

| 层 | 载体 | 状态 | 证据 |
|---|---|---|---|
| 提示词 | `AGENTS.md` + `SYSTEM.md`（变量填充注入） | ✅ | [index.ts L631-L651](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L631-L651) |
| 上下文 | compaction（30k/16k）+ `session_before_compact`（仅观测） | 🟡 | [settings](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json#L16-L20) / [index.ts L787-L790](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L787-L790) |
| 工具接口 | 24 业务工具注册 + `ALLOWED_TOOLS` 白名单 | ✅ | [index.ts L23-L39](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L23-L39) |
| 输出验证 | completion.ts + grounding.ts + reference.ts（+ koubei_claims 仅 smoke） | ✅ | [completion.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/completion.ts) |
| 编排 | `pi_gateway.mjs`（RPC/池/超时/mapEvent/ui 通路） | ✅ 通 | [pi_gateway.mjs](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs) |
| **前端埋点** | `tracker.ts`（page_view/active_tick 30s/feedback/chat_settled + sendBeacon + VIN/车牌脱敏 + 5min 空闲不计） | ✅ **已实现** | [tracker.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/lib/tracker.ts) |
| 数据源守卫 | `registry/datasource.ts`（3 源注册 + 覆盖率守卫 + 健康降级） | 🟡 **仅 smoke 用，非运行时** | [datasource.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/registry/datasource.ts) |
| 数据访问层 | `tools/_shared.ts`（只读开库 + `_meta` 读取） | ✅ **alive**（被验证器 import） | [reference.ts L10](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/reference.ts#L10) / [completion.ts L15](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/completion.ts#L15) |

### 1.3 评估层 harness

| 组件 | 状态 | 证据 |
|---|---|---|
| `eval/runner.mjs`（批跑器） | ✅ 跑过（内联正则评分，非调 scorer） | [runner.mjs L66-L118](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/runner.mjs#L66-L118) |
| `eval/scorer.ts`（六分制） | ❌ **死码**（无外部 import） | [scorer.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/scorer.ts) |
| `eval/tasks_v1.ts`（16 题） | ✅ | [runner.mjs L19-L38](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/runner.mjs#L19-L38) |
| `eval/stats.py`（McNemar/Wilcoxon/Cliff/bootstrap） | ✅ 存在（未接入批跑） | — |
| `eval/ci.sh`（**门禁 CI 骨架**） | ✅ 存在：smoke:all + runner + veto==0 且 passRate≥70% | [ci.sh](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/ci.sh) |
| `eval/langfuse_writer.ts`（评估写回） | ❌ 桩（console.log） | [L36-L44](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/langfuse_writer.ts#L36-L44) |
| `eval/EVAL_STATUS.md` | ⚠️ 写"待首次批跑" | [EVAL_STATUS.md](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/EVAL_STATUS.md) |
| `eval/eval-report.json` | ⚠️ 实有结果（跑过 16 题：avg 3.0625/pass 9/trap 3） | [eval-report.json L2/L308-L312](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/eval-report.json#L308-L312) |

---

## 2. 死码 / 半成品清单（v2 新增，均为实测）

| 文件 | 判定 | 依据 |
|---|---|---|
| `src/tools/guardrail.ts`（116 行） | ❌ **死码（第二套护栏）** | 全仓无 import（grep 仅命中存档）；其白名单 `ALLOWED_READONLY_TOOLS` 含**不存在的**工具（`query_energy/query_score/query_events/query_defects/discover_tools`），且缺全部 14 个 Atuohome 工具（[L33-L49](file:///c:/Users/<you>/Desktop/Prism-Agent/src/tools/guardrail.ts#L33-L49)） |
| `prism-api/pi_bridge.py` | ❌ **占位**（`create_session` 直接 `raise NotImplementedError`） | [L79](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_bridge.py#L79) |
| `eval/scorer.ts` | ❌ 死码 | 无外部 import（§1.3） |
| `eval/langfuse_writer.ts` | ❌ 桩 | L36-L44 |
| `src/registry/datasource.ts` | 🟡 仅 `smoke:datasource` 用，运行时（extension）走 FastAPI fetch，不直接用它 | [package.json L8](file:///c:/Users/<you>/Desktop/Prism-Agent/package.json#L8) |
| `eval/tasks_v1.ts` vs runner 内联 `TASKS` | 🟡 双份（易漂移） | [runner.mjs L19-L38](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/runner.mjs#L19-L38) |

> `guardrail.ts` + `pi_bridge.py` 是**同一套被废弃的设计期实现**（pi_bridge 注释 L101 说"供 pi_bridge 调用注册 hook"）。现状运行时是 extension + `pi_gateway.mjs`。这解释了 v1 为何没看到——它不在主路径上。

---

## 3. 与记忆/设计稿不符的纠错表

| 记忆/设计稿说法 | 实测 | 证据 |
|---|---|---|
| `.pi/settings.json` 声明 3 包并 pin 版本 | 项目 settings = `packages:[]`；12 包在 agent-minimal | §0#1 |
| "埋点未实现 → DAU/在线时长不可测" | `tracker.ts` 已实现并上报 `/events` | §0#3 / [tracker.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/lib/tracker.ts) |
| 评估"待首次批跑" | 已跑 16 题（eval-report.json） | §1.3 |
| extension "23 工具" | 现 24（含 resolve_series） | [index.ts L23-L32](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L23-L32) |
| 护栏 = extension 的 decideToolCall | 实为 6 道闸（permission-system/cc-safety-net/exclude-tools/setActiveTools/decideToolCall/输出验证） | §1.1 |
| grounding/reference "未加载" | 已被 extension 真实 import 调用 | [index.ts L17-L18](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L17-L18) |
| `{series_key}` 硬编码银河E5 | 已动态解析 + fail-closed | [index.ts L566-L602](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L566-L602) |

---

## 4. 真实问题清单（按严重度，均实测）

| # | 问题 | 严重度 | 证据 |
|---|---|---|---|
| R1 | `src/tools/guardrail.ts` 死码 + 白名单过期——若日后被误接线，会 fail-closed 拦死全部 Atuohome 工具 | 高 | guardrail.ts L33-L49 |
| R2 | 评估层双评分器：`scorer.ts` 死码，runner 用内联正则 | 高 | scorer.ts / runner.mjs L66 |
| R3 | 评估跑批与台账脱钩（跑过但不记） | 高 | eval-report.json / EVAL_STATUS.md |
| R4 | 正则评分无否定语义 → 合规回答可能误判"越界" | 高 | runner.mjs L107 |
| R5 | 每用户一 pi.exe，无池上限/排队 | 高 | pi_gateway.mjs L262-L309 |
| R6 | 身份/scope 走 prompt 文本前缀（非结构化通道） | 中 | pi_gateway.mjs L352-L360 |
| R7 | 评估层名称核验传空真值集 | 中 | scorer.ts L44 |
| R8 | 无 8 态状态机 / 无架构同构 dimension 标签 | 中 | scorer.ts L22-L26 |
| R9 | eval langfuse 写回是桩（虽插件已配 key） | 中 | langfuse_writer.ts L36-L44 |
| R10 | `datasource.ts` 覆盖率守卫仅 smoke 用，运行时身份核验走 FastAPI（两套） | 中 | datasource.ts / main.py |
| R11 | 开发期 UI 请求自动批准（chat.ts options[0]）—— 生产需弹框 | 中 | chat.ts L55-L58 |
| R12 | `mapEvent` 事件映射为子集 | 低 | pi_gateway.mjs L92 |

---

## 5. 收敛判定（修订）

| 维度 | 判定 | 说明 |
|---|---|---|
| 执行层·护栏（6 闸） | 🟡 **基本收敛** | 6 道闸真实在跑；但闸3 仍前缀门控、存在死码 guardrail.ts |
| 执行层·提示词 | ✅ 收敛 | — |
| 执行层·上下文 | ❌ 未收敛 | 文本前缀通道 + compaction 仅观测 |
| 执行层·工具接口 | 🟡 基本收敛 | allowlist 已落地；按需加载未做 |
| 执行层·输出验证 | ✅ 收敛 | completion+grounding 真实接入 |
| 执行层·编排 | 🟡 通但未契约化 | 事件子集、进程无治理、写回未接 |
| 执行层·前端埋点 | ✅ **已实现**（纠 v1） | tracker.ts |
| 评估层 | ❌ 未收敛 | R2/R3/R4/R7/R8/R9 |

**总判定：执行层"多闸齐备、基本收敛"；评估层"有壳未收敛"。**

---

## 6. 验证方式分层

| 层级 | 可否离线 | 手段 | 例子 |
|---|---|---|---|
| 组件机制（纯函数） | ✅ | `smoke:verify`（4 测试文件）/ `smoke:guard` | decideToolCall、verifyNames、identity API |
| 装配契约（半集成） | 🟡 | mock / 直调 | setActiveTools、EXCLUDE_TOOLS、mapEvent |
| 组合体行为（模型+harness） | ❌ 必须跑 agent | `node eval/runner.mjs` | 越界回流、幻觉 veto、trap 拦截 |

金句：**组件机制可离线单测；组合体行为必须跑 agent；二者不可互替。**

---

## 7. 待实测 / 待复算

| # | 待办 | 缺什么能坐实 |
|---|---|---|
| V1 | 复核 R4 是否真误判 | 补全回复全文留档（现只存 `slice(0,100)`），重跑逐题复核 |
| V2 | 核实闸0 与 `--approve`/`PRISM_AUTO_APPROVE_UI` 的交互（是否仍弹框） | 抓一次网关运行日志（permission_request 是否被自动 resolve） |
| V3 | 判定 `datasource.ts` 覆盖率守卫是否应在运行时启用 | 确认身份核验是否只走 FastAPI |
| V4 | 40 并发承载 | 压测（进程模型无上限） |
| V5 | eval langfuse 闭环 | 接 SDK + 本地 langfuse（key 已配 localhost:3000） |

---

## 附录 · 全仓 harness 文件索引（实测）

**扩展与配置**
- [.pi/extensions/prism-guardrails/index.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts)、[tool_call.test.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/tool_call.test.ts)、[smoke.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/smoke.ts)
- [.pi/settings.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/settings.json)（packages:[]）、[.pi/agent-minimal/settings.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json)（12 包）、[langfuse.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/langfuse.json)
- 运行日志：[pi-permission-system logs](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/extensions/pi-permission-system/logs/pi-permission-system-permission-review.jsonl)、[trajectories.jsonl](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/sessions/trajectories.jsonl)

**验证器与工具层**
- [src/verify/completion.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/completion.ts)、[grounding.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/grounding.ts)、[reference.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/reference.ts)、[koubei_claims.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/koubei_claims.ts)
- [src/tools/_shared.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/tools/_shared.ts)（alive）、[src/tools/guardrail.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/tools/guardrail.ts)（死码）
- [src/registry/datasource.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/registry/datasource.ts)（smoke 用）

**网关与前端**
- [prism-api/pi_gateway.mjs](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs)、[main.py](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py)、[pi_bridge.py](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_bridge.py)（占位）
- [prism-web/src/lib/tracker.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/lib/tracker.ts)、[chat.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/lib/chat.ts)

**评估层**
- [eval/runner.mjs](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/runner.mjs)、[scorer.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/scorer.ts)、[tasks_v1.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/tasks_v1.ts)、[stats.py](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/stats.py)、[ci.sh](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/ci.sh)、[langfuse_writer.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/langfuse_writer.ts)、[EVAL_STATUS.md](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/EVAL_STATUS.md)、[eval-report.json](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/eval-report.json)