# Prism-Agent 项目参考资源清单

> 检索时间：2026-09-13 ｜ 来源：GitHub API 实时搜索（gh CLI，账号 Trastio）
> 筛选口径：与 Prism-Agent（汽车 PM 竞品分析 data agent，底座 pi，三角交叉验证 + 评估体系）直接相关

---

## 一、Agent 评估（你点名最关心，排最前）

| 优先级 | 项目 | Star | 为什么对你有用 |
|--------|------|------|---------------|
| ★★★ | **ByteDance-Seed/DAComp** | 441 | ICLR 2026，Data Agent 全生命周期 benchmark（数据工程 + 开放分析 + 中文分割），带基线 agent 和评估套件。你的项目本质就是 data agent，它的任务设计/指标口径可直接搬进 Prism §8 评估体系。论文 arxiv 2512.04324，数据集在 HF。 |
| ★★★ | **Asaf-Yehudai/LLM-Agent-Evaluation-Survey** | 112 | IBM+耶鲁《Survey on Evaluation of LLM-based Agents》(arxiv 2503.16416) 配套仓库。按规划/工具/自反思/记忆 + 应用域 + 框架组织，是评估的"地图"。你书第7章 Pass@k/Pass^k、失败归因的横向展开。 |
| ★★ | **ZJU-REAL/ageval** | 69 | 在同一个 running base 上评估 agent，用插件换被测对象。轻量，适合你做 A/B 对比。 |
| ★★ | **Margin-Lab/evals** | 150 | 快速、鲁棒、可配置的 agent evals。 |
| ★★ | **microsoft/ai-agent-evals** | 105 | GitHub Action 形式，model-as-judge 评估 agent 应用。 |
| ★ | **reworkd/bananalyzer** | 330 | Web 任务 agent 评估框架（AgentEval 系）。 |
| ★ | **rogue-security/rogue** | 1064 | Agent 红队 + 评估平台（你护栏/安全边界的参考）。 |

## 二、Data Agent（你项目核心场景）

| 优先级 | 项目 | Star | 为什么对你有用 |
|--------|------|------|---------------|
| ★★★ | **HKUSTDial/awesome-data-agents** | 754 | 港科大 data agents 论文清单 + SIGMOD'26 教程。配套综述《Data Agents: Emerging Paradigm or Overstated Hype》(2510.23587)。含清华《Data Agents: Levels, State of the Art, and Open Problems》(2602.04261)——给 data agent 分层，帮你把"data agent vs chatbi"定位讲硬。 |
| ★★ | **spring-ai-alibaba/DataAgent** | 2678 | 阿里 DataAgent，架构可借鉴。 |
| ★★ | **hitsz-ids/airda** | 1788 | 面向数据分析的多智能体（Air Data Agent），中文场景。 |
| ★★ | **Canner/WrenAI** | 17715 | GenBI、受治理 text-to-SQL，你口碑 ChatBI 模块的 dry-plan + 只读守卫参考。 |
| ★ | **agno-agi/dash** | 2268 | 自学习 data agent（系统工程原则）。 |
| ★ | **databendlabs/databend** | 9450 | "Data Agent Ready Warehouse"，云数仓路线参考。 |

## 三、Harness 工程（你底座 pi 的对照与深化）

| 优先级 | 项目 | Star | 为什么对你有用 |
|--------|------|------|---------------|
| ★★★ | **Picrew/awesome-agent-harness** | 1787 | **372 个条目**的 harness 工程资源清单，含 Anthropic/OpenAI 的 harness 工程博客（managed agents、harness engineering、有效工具设计）。是李博杰书内容的"工业界对照版"，书里抽象原则在这里有生产案例。 |
| ★★★ | **langchain-ai/deepagents** | 29639 | "batteries-included agent harness"，开箱即用的 opinionated harness。看它怎么组织规划/记忆/工具，对照你自己的 harness 设计。 |
| ★★ | **HKUDS/OpenHarness** | 15830 | 轻量 agent 基础设施（工具/skills/记忆/多 agent 协调），43+ 工具，MIT。中文友好（README 有简中）。 |
| ★★ | **HKUDS/DeepCode** | 16613 | Agentic Coding（harness + loop engineering），港科大团队。 |
| ★ | **Picrew/awesome-agent-harness 里的博客** | — | 尤其推荐 Anthropic《Effective harnesses for long-running agents》+ LangChain《Evaluating Deep Agents: Our Learnings》——正好覆盖你"长程 agent + 评估"两个痛点。 |

## 四、pi 底座生态（你已选定 pi，这些是它的周边）

| 优先级 | 项目 | Star | 为什么对你有用 |
|--------|------|------|---------------|
| ★★★ | **SaladDay/pi-from-scratch** | 1228 | **600 行 TypeScript 写迷你 pi**，从 0 理解 pi 内部结构的最佳教材。你要在 pi 上做护栏/评估/工具，先吃透这个。 |
| ★★★ | **disler/pi-agent-observability** | 144 | pi 的本地观测栈（Pi Extension + Dashboard + 产品 agent demo），性能/速度/成本三元权衡。直接解决你 §8 埋点/观测需求。 |
| ★★ | **qualisero/awesome-pi-agent** | 1098 | pi 的 add-ons/hooks/tools/skills 生态清单。 |
| ★★ | **disler/pi-vs-claude-code** | 1692 | pi 与 Claude Code 对照，帮你理解 pi 的强弱项。 |
| ★ | **Dicklesworthstone/pi_agent_rust** | 1767 | pi 的 Rust 实现，性能路线参考。 |

## 五、学习资料（接续李博杰的书）

| 优先级 | 项目 | Star | 为什么对你有用 |
|--------|------|------|---------------|
| ★★★ | **bojieli/ai-agent-book** | ~46000 | 你读的那本书的开源仓库：109 实验 + 思考题参考答案 + EXPERIMENT_LEDGER.md。读书对照实验跑，比只看 PDF 深。 |
| ★★★ | **h9-tec/llm-systems-engineering-roadmap** | 197 | 12 层系统化路线图（基础→训练→后训练→推理→KV Cache→量化→RAG→Agent→**评估**→生产）。与李博杰书互补：书讲 Agent 原则，这个讲全栈 LLM 系统。你有 ML 基础，当索引用，缺哪补哪。 |
| ★★ | **nibzard/awesome-agentic-patterns** | 4982 | 可复用的 agentic patterns 目录（真实生产里验证过的 trick/workflow）。官网 agentic-patterns.com。 |
| ★★ | **WenyuChiou/awesome-agentic-ai-zh** | 7137 | 三语 agentic AI 学习路线图（有简中），系统补 agentic 知识。 |
| ★ | **luo-junyu/Awesome-Agent-Papers** | 2859 | LLM Agent 综述论文清单。 |
| ★ | **WangRongsheng/awesome-LLM-resources** | 8975 | 中文 LLM 全领域资料汇总。 |

## 六、RAG 评估（你第三个 RAG 项目相关）

| 项目 | Star | 说明 |
|------|------|------|
| **vectara/open-rag-eval** | 410 | 无需 golden answer 的 RAG 评估。 |
| **YHPeter/Awesome-RAG-Evaluation** | 200 | RAG 评估综述论文清单。 |
| **qdrant/qdrant-rag-eval** | 91 | RAG 评估中心仓库。 |
| **BytePioneer-AI/RAGEval** | 111 | 中文开箱即用 RAG 评测系统。 |

## 七、LLM-as-judge（评估体系的技术组件）

| 项目 | Star | 说明 |
|------|------|------|
| **CSHaitao/Awesome-LLMs-as-Judges** | 614 | LLM-as-judge 全面综述论文清单。 |
| **1norqaq/audit-the-judge** | 141 | 用配对合成数据审计 LLM-judge 系统（你护栏里"judge 也会被骗"的证据）。 |
| **microsoft/llm-as-judge** | 38 | 微软 LLM 评估。 |

---

## 我的建议（排序，不是堆清单）

1. **先啃 DAComp**——唯一同时命中"data agent + 中文 + 评估"三个关键词的基准，读它的任务设计和指标，直接补你 §8 评估体系。增量最大。
2. **再看清华 Data Agents Levels 论文**（在 awesome-data-agents 里）——把"我的项目是什么层级"讲清楚，面试和定位都用得上。
3. **pi 底座吃透 pi-from-scratch**（600 行）+ **pi-agent-observability**（观测栈）——一个解决"理解底座"，一个解决"埋点观测"。
4. **awesome-agent-harness 里的博客**——Anthropic/OpenAI 的 harness 工程实战文章，是书里原则的生产级印证。
5. 评估要补系统知识时，查 **Survey on Evaluation of LLM-based Agents (2503.16416)**。
