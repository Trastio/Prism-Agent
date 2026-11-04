# Prism-Agent × pi 生态案例研究

> 调研来源：GitHub 一手来源（2026-09-16，gh CLI v2.93.0 已登录 + GitHub REST API），星数均为当日数据，会随时间漂移。
> 本文档：应"看看基于 pi-agent 底座做的项目"的调研产出，回答两个问题——二次开发有没有成功先例？他们的做法对我们有什么用？
> 地位：**标杆案例研究，与《Prism-Agent-读书映射.md》同级**，同属方案设计的输入。底座选型已拍板（pi-agent），本文档不是方案对比，不改变七步执行序列（任务清单见 `Prism-Agent-任务清单.md`）。

---

## 0. 一页结论

1. **pi 不是小众底座**：主仓库已迁移为 earendil-works/pi，≈**10.6 万星 / 1.3 万 fork**，pi 已成为主流 harness，常与 Claude Code / Codex / Cursor 并列出现在生态工具中。→ 选 pi 的决策拿到了外部证据。
2. **基于 pi 的成功二开存在且成体系**，三条路线各有代表作：
   - **fork 做深**：oh-my-pi（⭐31.3k，fork 后 IDE 集成+Rust 核心，商用站 omp.sh）
   - **壳产品化**：PI-Desktop（⭐3.9k，桌面壳产品）、pi-web（⭐6.4k，Web UI）
   - **SDK 嵌入做领域 agent**：BreachWeave（⭐649，渗透测试多角色 agent，腾讯云黑客松一等奖 1/613）
3. **Prism-Agent 的架构 = 壳产品化（双模式网站）+ SDK 嵌入（领域 agent）的组合，两条路线都有星数和竞赛成绩背书的先例。**
4. 最值得精读的两个：**BreachWeave**（领域 agent 实战，与本项目同构）+ **pi-book**（中文《pi 的设计艺术》，讲底座设计决策）。已列入第②步教材包（§5）。

---

## 1. pi 底座现状（2026-09-16 核实）

| 事项 | 事实 | 对我们 |
|---|---|---|
| 主仓库 | badlogic/pi-mono → **earendil-works/pi**（≈105.9k 星） | 旧链接会重定向；查文档认准新组织 |
| npm 作用域 | `@mariozechner/*` → **`@earendil-works/*`** | 新装 SDK 包用新作用域；0.65 时代的项目（如 BreachWeave）仍用旧名 |
| 组织实体 | earendil-works（exe.dev），有 Discord 社区、吉祥物 | 生态入口 = 官方 README + Discord + npm |
| 官方姊妹/扩展仓库 | pi-review（⭐558 代码评审扩展）、pi-review-loop（⭐158）、pi-chat（⭐397，Slack 编排）、gondolin（⭐2157，Linux micro-VM 沙箱 + TS 控制平面）、pi-transcribe（⭐239）、pi-tutorial（⭐171） | 官方自演示"扩展插槽"的各种用法，做护栏/扩展时对照 |
| 生态索引 | awesome-pi-agent（⭐1098）**已退役**（自述"被更专业的项目取代"），无正式继任 | 找生态项目用 gh search，别依赖精选清单 |
| 多 harness 工具带 pi | wshobson/agents（⭐39.7k 插件市场）、omnigent（⭐10k）、gentle-ai（⭐6.9k）等均把 pi 列为支持对象 | 印证主流地位 |

---

## 2. 三类路线的案例详表

### 路线 A：SDK 嵌入做领域 agent ← Prism-Agent 核心路线

#### 2.A.1 BreachWeave（⭐649）—— 最同构的先例，优先精读 ★★★

**一句话**：中文团队基于 pi SDK 做的智能渗透测试多角色 agent。

- **战绩**（其 README 竞赛表）：腾讯云黑客松智能渗透测试挑战赛第二期——线上初赛第 1（/613 队）、线下决赛一等奖；另上 TsecBench 公开评测。
- **技术底座**（`packages/core/package.json` 已核实）：`@mariozechner/pi-agent-core` / `pi-ai` / `pi-coding-agent` / `pi-tui` ^0.65.0 + **pi-mcp-adapter**（与我们装的是同一个桥接包——它也走了"MCP 工具接进 pi"的路）。
- **架构拆解**（来自其 README）：
  - **Manager** 全局编排：不亲自执行，管节奏、分配/回收 Solver、汇总状态——系统的控制平面；
  - **Solver** 执行主体：一个题目可同时存在多个，并行探索不同方向；
  - **Observer** 旁路监督：不替代 Solver 决策，持续看最近几轮轨迹，发现低效/偏移做轻量纠偏；
  - **状态分层**：Idea（当前值得推进的方向）与 Memory（可复用的事实/证据/约束）分开维护；
  - **结束条件外置**：任务是否结束不由模型主观判断，由系统结合任务状态统一约束；
  - **上下文压缩与降噪**：改写/压缩/摘要，让后续决策建立在"高信号、低噪音"之上。
- **与 Prism-Agent 的映射**：

  | BreachWeave | Prism-Agent 对应 | 出处 |
  |---|---|---|
  | 多 Solver 并行探索攻击面 | 棱镜三维度并行调查（pi-subagents 预留） | 读书映射 ⑧ |
  | 结束条件外置 | 完成验证器："模型可提出完成，不能批准自己的完成"（红线#1 机制化） | 读书映射 ②，提议者—审核者模式 |
  | Observer 轻量纠偏 | 护栏层（执行层 hooks，非提示词） | 约束红线 #5 |
  | Idea/Memory 状态分层 | 快照=事实层（只增不改），会话层提示词=方向层 | 读书映射 ③⑫ |
  | 上下文压缩降噪 | 《AI Agents in Depth》ch2 上下文工程 | 书 + Manus 同款 |
  | pi-mcp-adapter 桥 | 同款包（其护栏拦截测试同样待做，互相参照） | pi-harness 待办 |

- **多 agent 判据检验**：书 ch10 的判据是"是否引入新信息"。BreachWeave 的多 Solver 各自探索不同攻击路线、确实引入新信息，成立；Observer 只旁观不替代，没踩"多 agent 辩论"的坑。**我们的三维度并行（配置/口碑/销量三个独立数据源）同理成立，这个案例反过来验证了读书映射 ⑧ 的判断。**

- **源码级拆解（2026-09-16 用 gh 读 main 分支源码核实）——它如何基于 pi 改造**：
  - **总原则：一行内核代码没改**。pi 以 npm 包引入（^0.65.0），全部定制走官方插槽——pi 升级只需改版本号。自述四层：apps/cli（入口，路由 web/tui）→ ui-web（Bun REST+React）/ui-tui（Ink）→ @tch/core（配置中心+领域逻辑）→ pi SDK（纯第三方依赖）。
  - **六个插槽用法**（文件实证）：SDK 会话=`createAgentSession`（solver/session.ts，模型/工具/技能/提示词组装为 CreateAgentSessionOptions）；角色层=每角色一个 YAML+MD PromptFile（CHALLENGE_PLANNER/kimi-security，config/prompts/）；工具层=defineTool+typebox（nmap/成果提交/工作区读写）+ pi-mcp-adapter 接外部 MCP；知识层=内置技能包 ad-pentest 含 10 篇参考手册渐进披露（config/skills/builtin/）；模型层=自写 zhipuai provider（config/providers/）；**护栏层=5 个 pi 扩展**（solver/extension/）。
  - **护栏 5 扩展**（对 Prism-Agent 最有价值）：①`scope-guard.ts`——audit/enforce 双模式（先审计后强制的灰度上线策略）；共享状态文件所有权（findings.md 等只归 Manager，Solver 写入只能走专用提交工具，护栏拦其余写法）；Manager 直接跑扫描命令限 6 次逼其调度；写路径白名单+工具调用总数上限。②`subagent.ts`——多 agent 实现：每次派生**独立进程**跑全新 pi 会话（上下文彻底隔离），单/并行≤8/链式三模式，子 agent 结构化 JSON 回传。③`challenge-observer/`——Observer 是挂在 Solver 会话上的扩展，旁路看轨迹轻量纠偏。④`pentest-compaction.ts`+`large-tool-result.ts`——自定义压缩+超大工具结果截断改写（ch2 上下文降噪落地件）。⑤`rtk-rewrite.ts`——工具结果统一改写后进上下文。
  - **开发方法（意外发现）**：仓库内嵌 `.claude/skills/pi-mono-framework/`（pi 框架知识蒸馏成技能包喂给开发用的 Claude Code）+ `docs/pi-docs/`（pi 官方文档整个内嵌）——"用 agent 开发 agent"。我们本地已有 pi 文档，同款打法可用。
- **注意**：main 分支=CTF 基础版，**pentest 分支才是增强版**（资产管理/自动 Planner/项目级 Memory/Attack Flow 回放）。精读看 pentest 分支。

#### 2.A.2 scientific-agent-skills（⭐45.1k）—— 领域技能包模式先例 ★

- **一句话**：165 个经验证的科学领域 Skills + 100+ 科学数据库，兼容 pi / Claude Code / Codex 等，自称 19 万+ 科学家在用。
- **对我们的意义**：证明"领域知识编码成技能包、渐进披露"这条路能到产品级规模——就是角色层插槽（棱镜理论 Skills）的先例。知悉模式即可，不必深读。

### 路线 B：壳产品化 ← Prism-Agent 网站路线

#### 2.B.1 PI-Desktop（⭐3.9k）—— 桌面壳产品 ★★

- **一句话**：Electron + Rust 宿主核心 + **pi Agent Harness** 的桌面工作台，插件系统，macOS/Windows/Linux。
- **产品主张**：本地优先、BYOM（用户自带模型 key）、无账号、无强制中继、项目与会话留在本机——"让 agent 干活，控制权在你"。
- **对我们的参照**：①壳的形态划分（项目/会话/插件三层）；②在产品层把"数据不出本机、控制权在用户"做成卖点——**与我们的数据真实性红线、只读权限模型是同一叙事家族**；③有简体中文文档（pi-docs.aiuo.net）和插件开发指南，可读性好。
- **差异提醒**：它是通用编码壳，不是领域 agent；我们学它的壳，不学它的定位。

#### 2.B.2 pi-web（⭐6.4k）—— pi 的 Web UI ★★★

- **一句话**：第三方为 pi 做的 Web UI（仓库描述核实；具体与 pi 的接线方式——SDK 还是 RPC——**待精读核实**）。
- **对我们的参照**：pi 官方没有 Web UI 模式，我们的双模式网站要自建前端 + pi 藏在 API 后——这个项目就是现成的补位方案代码级参照，网站壳设计时第一个看。

#### 2.B.3 oh-my-pi（⭐31.3k）—— fork 做深路线的天花板 ★

- **一句话**：明确自述"Fork of Pi"（README 核实），IDE 深度集成（14 个 LSP 操作 / 28 个 DAP 操作）、约 8 万行 Rust 核心、60+ 模型提供商、31 个内置工具，npm 包 `@oh-my-pi/pi-coding-agent`，商用站 omp.sh。
- **对我们的意义**：不是我们的路线（改内核工程量与其团队体量绑定），但它验证了 pi 内核可改造的上限。**两个第②步借鉴点**：①《The Harness Problem》博客（blog.can.ac，2026-02）用基准数据证明"工具接口设计决定模型表现"——同一模型仅改编辑格式 6.7%→68.3%，可作选型论证/复盘的论据；②"时光倒流流式规则"——规则平时不占上下文，模型输出正则命中违规时中途打断、注入规则、从原点重试（压缩后存活），是执行层护栏（红线#5）的成熟实现模式，做口径校验时可参考。

### 路线 C：改造 / 移植（知悉即可）

| 项目 | 星数 | 一句话 |
|---|---|---|
| pi-rs | 539 | Rust 轻量化重写（中文描述） |
| senpi | 430 | opinionated fork，extension-first 取向 |
| pi-book | 323 | 中文设计艺术书，见 §3 |
| pi-session-manager | 183 | 会话浏览/搜索/恢复工具 |
| pi-mono-extensions | 100 | 第三方扩展合集 |
| pix-mono | 69 | pi 的"发行版" |
| pi-mono-python | 28 | Python 移植 |

---

## 3. 中文教材：pi-book《pi 的设计艺术》（⭐323）★★★

- **在线阅读**：zhanghandong.github.io/pi-book（mdbook，CC BY-NC-SA 4.0）
- **性质**：解剖 pi-mono 的关键设计决策，"不是源码导读，而是回答为什么这样设计——每个决策放弃了什么、得到了什么"。
- **章节地图**（自其 README）：序章=pi 是什么/分层架构/如何读源码；二篇=一个接口统一 20+ LLM 厂商；三篇=agent 循环引擎；四篇=通用 runtime 如何变成可用产品；五篇=哪些能力内建哪些外置；六篇=给 LLM 什么样的工具接口；七篇=同一内核跑终端/浏览器/RPC；**八篇（28-29）=Slack bot 和 GPU 编排的复用实证——两个二开案例**；九篇=设计哲学与适用边界。
- **与《AI Agents in Depth》的分工**：那本讲通用方法论（全 harness 通用），pi-book 讲我们这个底座的具体决策——**第②步教材包 = 书（方法论）+ pi-book（底座）+ BreachWeave 源码（实战）**，三层互补。
- **版本提醒**：基于 pi-mono v0.66.0（2026-04）分析，我们用 0.85.1——架构层适用，个别 API 核对。

---

## 4. 版本与兼容注意

1. BreachWeave 用 0.65、pi-book 基于 0.66、我们是 **0.85.1**——架构思想全部适用，具体 API 以本地 0.85.1 文档为准。
2. npm 作用域迁移：新装包认准 `@earendil-works/*`；阅读老项目代码时会看到 `@mariozechner/*`，是同物异名。
3. 本地 `pi-windows-x64\docs\` 若与新版 README 冲突，以官方仓库最新版为准，差异记入 pi-harness 备忘。

---

## 5. 与执行序列的挂接

| 序列位置 | 本文档的贡献 |
|---|---|
| 第①步 Agent 组装 | §2.B（pi-web / PI-Desktop）作为网站壳参照；开篇交付物**选型论证文档**可直接引用 §0 结论（为什么选 pi：主流地位 + 二开先例 + 扩展点齐全） |
| 第②步 Harness 补功课 | 教材包扩充：书 + **pi-book** + **BreachWeave（pentest 分支）**；BreachWeave 的结束条件外置/Observer 纠偏与读书映射 ②⑧ 对照着做 |
| 第⑦步 复盘 | 本文档 + 选型论证共同支撑"立项依据" |

**遗留待办**（随本调研新增/确认）：
- [ ] 选型论证文档（轻量，第①步开篇交付物）——未写
- [ ] BreachWeave pentest 分支精读（第②步）——未开始
- [ ] pi-web 与 pi 的接线方式核实（第①步网站壳设计前）——未开始
- [ ] pi-mcp-adapter 护栏拦截测试（原有待办；BreachWeave 同用此包，其用法可参照）

---

## 附：信息核实方式与时效

- **工具**：gh CLI v2.93.0（已登录账号 Trastio，token 在系统 keyring，repo 权限齐全）+ GitHub REST API。以后查 GitHub 一手信息优先用 gh。
- **核实级别**：星数/描述/README 均一手来源；BreachWeave（package.json）与 oh-my-pi（README 自述 fork）做到代码级/自述级核实。
- **未覆盖**：Discord 社区内容、X 讨论、各项目 star 增长趋势——如第⑦步复盘需要"生态热度曲线"再补。
- **时效**：2026-09-16。星数与仓库状态会漂移，引用时注明当日数据。
