# skill 静态检查（微 change 直修归档 · 2026-10-20）

## 起因

用户对照小红书博主《Skill评测-如何通过指标分析产品效果》（8 份大厂 skill 评测方法抽象：静态检查→动态评测→修改→上线→线上监测→坏案例回流）问"我们的 skill 是否还需要规范"。核对结论：SKILL.md 写法已超文章水平（意图+交付物触发信号/负面边界/状态门/导出前自查），**真缺口在静态检查**——prompt-gate 此前只做"变更闸"（指纹比对+冒烟），不做"内容闸"。人工跑一遍内容级静态检查，实锤 5 处漂移。

## 发现（静态检查实跑结果）

| # | 位置 | 文案值 | 实际值（实测出处） |
|---|---|---|---|
| F1 | car-reputation 铁律8+阶段一 | TikHub 每轮最多 8 次调用 | TIKHUB_LIMIT=20（tikhub.ts:26，10-14 拍板 8→15→20 文案没跟） |
| F2 | config-compare 标题/summary/纪律4/边界 | 61 项口径 | diff_pricing.json items=71+excluded 2 |
| F3 | config-compare 边界 | 现 244 系 | config_snapshots distinct series_id=353（新能源车池扩容后） |
| F4 | car-reputation frontmatter | version 2.0.0-prism | 内容已含 v2.2 六维卡+v2.3 两阶段协议 |
| F5 | config-compare frontmatter | version 1.1.0-prism | origin 自述"v2 扩范围"号没跟 |

根因：**文案复制了真值数字**——真值会动（护栏拍板/清单补项/车池扩容），文案不会自跟。静态检查只能抓不能防。

## 交付

1. **文案去数字改指针（治本）**：两个 SKILL.md 共 9 处编辑——配额"以系统护栏为准"、清单"按配置差价口径（项数以清单为准）"、覆盖"以库为准"、C2 增量"金额以差价清单为准"；version 对齐 2.3.0-prism / 2.0.0-prism。
2. **静态 lint 入 prompt_gate（防复发）**：`lintSkillFiles()` 三断言——A 双登记（磁盘 .pi/skills md ⊆ PROMPT_FILES，防新增 skill 漏登记=门禁失明）/ B frontmatter（name+summary+description 顶层必填+version 含嵌套+name=目录名）/ C 硬数字黑名单（SKILL.md 正文禁 `\d+ 项|\d+ 系|\d+ 次`——"文案不许写死会动的真值"是不变式，比逐项校验真值可靠）。check 违例即红（与指纹状态无关）；root/files 参数化供单测注入。
3. **单测 4 例新增**（真实仓库零违例不变量+三断言正反例），prompt_gate.test.mjs 5→8 例；**smoke:prompt 挂进 smoke:all**（此前该测试件未进套件）。
4. **trap-01 判分扩词（冒烟副产物）**：冒烟 9/10，trap-01=0 归因=判分假阴（agent 回复"库内的正式版型名为探索版"是正确纠错行为，verdict=pass+verifyNames 放行，但 WRONG_NAME_REJECT 词表不认该变体）——走红绿流程（红测先行）扩词 `正式版型名|正式名称`，判分器 28/28 绿，单题复跑 score=5。**防线本身有效，是测量工具滞后**（user-feedback #9 同款：先查测量再疑行为）。

## 验证

- prompt_gate 单测 8/8；trap_check 单测 28/28
- 门禁链路实测：改 SKILL.md → check 红（准确列 2 文件+冒烟指引）→ trap 冒烟（10 题 9/10，trap-01 假阴归因修复）→ 单题复跑 5 分 → mark-green → check 绿
- lint 真实仓库零违例（改后）

## 二段：动态测试（同日深夜，用户点名"接下来做一下动态测试"）

**交付**：skill 触发题资产化——tasks.json 60→63（skill-01 应触发/skill-02 不该触发/skill-03 两阶段流程断言，均 dev 集）+ trap_check 三新类型（skill_must_trigger=tools 含 load_skill / skill_must_not_trigger=不含 / skill_phase1_stop=回复呈候选人名单形态 PHASE1_LIST_RE），红绿流程先行（3 红→31/31 绿）。真跑两轮：3/3 全 5 分。

**动态测试抓出的三个真发现**：

1. **P1 已修——eval 跨题会话串味**：登录门（10-15）后 server 端身份=token（resolve_user_id 防冒用覆盖 body user_id），runner 的每题独立 user 机制（eval_<task.id>）静默失效 → 整批 continueRecent 共享一个会话。实锤：skill 三题同一 sessionId、skill-03 回复明说"上一轮社媒数据"（复用 skill-01 扫描结果）。修=runTask 每题首轮前 POST /session 显式开新会话（session_id 走既有 session_info 穿线通道，不动鉴权面；失败告警回落）。隔离复跑验证：3 个独立 sessionId、三题仍全 5。**影响面注记：10-15 之后的批跑（尾巴包 eval22 等）均在共享会话上跑，跨题上下文有串味；v1/v1.1 基线（10-14）不受影响；下一轮全量批跑起结果才完全可比。**
2. **设计缺口挂账——eval 模拟用户应答策略**：网关对 ask_user_question 自动应答（select→选第一项），"停下问用户"类流程被自动代答。隔离轮 skill-03 因此走完全程：扫描×8→问点名→自动应答=点名→状态门解锁→深挖+模板B 6-sheet 交付。判分 5 分是"被点名"一词在另一语境命中 PHASE1_LIST_RE（真通过但语义巧合）——**评测的"模拟用户怎么答"（=文章评测数据四件套的"前置状态"字段）需要设计**，归多轮题 change 一并做（否则"问询类"题全部被自动代答扭曲）。
3. **正向实证**：隔离轮完整走通两阶段协议全链路（load_skill→身份核验→基本盘→扫描+评论→问点名→解锁→深挖→模板B 导出），工作流状态门+解锁机制在真实 agent 上端到端有效；skill-01 独立会话下产出带 URL 溯源+水军剔除的 7-sheet 调研报告（出口闸 pass）。

**验证**：判分器 31/31；skill 题 2 轮 3/3（共享会话轮+隔离轮）；runner 语法+集成（隔离复跑即集成测试）；eval 实例已停。trap 全集隔离复跑留下一轮全量批跑顺带（trap 冒烟在共享会话上跑过，判定不受影响——trap 是对抗性提问，隔离只会更贴设计）。

## 留下轮

- ~~多轮题挂题时补 skill 专项题~~（二段已交付 3 题）；多轮题 change 需一并设计**模拟用户应答策略**（前置状态字段）+ skill-03 判分语义重审（名单形态 vs 模板B 全程二选一，取决于应答策略拍板）
- 线上 skill 级指标（load_skill 触发率/深挖完成率）排轮 2
- 下一轮全量批跑起用隔离会话，与 v1.1 基线的对比需注记口径变化

## 面试三讲

1. **解决什么**：skill 文档与系统真值漂移（护栏配额/清单项数/覆盖量三处实锤）——AI 产品里"提示词是无测试的代码"，我们把 skill 文件纳入与代码同等的版本管理+回归门禁，并补上内容级静态检查。
2. **关键裁决**：发现漂移后不建 lint 体系先行，而是先治本（文案去数字改指针——文档不锁真值锁指针），再用 20 行黑名单 lint 防复发；"不变式校验"优于"真值校验"。
3. **面试官会追问**：为什么黑名单比逐项校验真值可靠？——真值会动（每次拍板/补项/扩容都变），校验逻辑要跟着追；而"文案不许出现会动的数字"是静态不变式，一次定义永久有效。
