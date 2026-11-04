# Step7 隔离审查任务书 · 舆情工具层跟进（2026-10-20）

你是独立审查者。审查一个刚施工完的 change，**不预设任何设计结论**——施工者可能错了，你的价值是实证复现问题，不是背书。

## 第 0 步（守卫，必做）

自报你的工具清单（有没有 Read/Grep/Bash/Glob）。**无文件读取工具则立即退出，报 NO-TOOLS**，不要用 web 工具绕路，不要虚构行号报告。

## 背景（只给事实，不给设计对错）

Prism-Agent（pi harness + FastAPI 网关的汽车数据 agent）。本 change 给舆情工具层做跟进：
- extension（TS，跑在 pi 子进程内）新增第 7 个舆情工具 sentiment_defects（调舆情 dashboard 端点 /defect-themes/{id}）
- resolveVehicleId 改为两级解析（fleet-overview 只回 active 车 → fallback Prism 侧新端点拿全量含 paused）
- paused 车响应注入 _prism_frozen_note 字段；inactive/未收录 unavailable 文案区分
- 出口闸（/verify/claim）登记新引用表 sentiment_defects
- 配套测试与 smoke 挂载

## 审查文件（全部从磁盘直读，绝对路径）

1. `C:\Users\<you>\Desktop\Prism-Agent\.pi\extensions\prism-guardrails\index.ts`
   - 本 change 涉及段：resolveVehicleId（≈:331-373）、makeSentimentTool（≈:375-450，含 execute）、registerSentimentTools 尾部（sentiment_defects 注册）、KNOWN_BUSINESS_TOOLS（≈:49）、TRUNCATABLE_TOOLS（≈:173）、submit_conclusion 描述（≈:619）与拒绝提示（≈:763）
2. `C:\Users\<you>\Desktop\Prism-Agent\prism-api\main.py`
   - _SENTIMENT_TABLES（≈:1041）；新端点 /sentiment/vehicles-all（≈:605-628）
3. `C:\Users\<you>\Desktop\Prism-Agent\tests\sentiment_tools.test.ts`（新文件）
4. `C:\Users\<you>\Desktop\Prism-Agent\tests\verify_claim_api.test.ts`（尾部新增 case 6/7）
5. `C:\Users\<you>\Desktop\Prism-Agent\.pi\extensions\prism-guardrails\tool_call.test.ts`（"23 个业务工具"断言段）
6. `C:\Users\<you>\Desktop\Prism-Agent\package.json`（scripts.smoke:verify）
7. `C:\Users\<you>\Desktop\Prism-Agent\openspec\changes\舆情工具层跟进\e2e_check.py`

## 审查维度（逐一实证，不设预期答案）

A. **resolveVehicleId 返回形态变化的所有调用方**：旧返回 string|null，新返回 {id,status}|null。grep 该函数全部使用点，确认没有漏改的调用方仍在当 string 用。
B. **paused 注入的下游污染**：_prism_frozen_note 进入 tool_result 后，逐一核实三个消费方是否受影响——真值信封 harvestTruth（src/shared/truth-envelope.ts，按 rows/cells/cols/trims/diff 结构收割）、名称真值 collectNameTruth（src/verify/grounding.ts:86 起，按顶层 NAME_FIELDS 收）、截断层 truncateToolResult（src/shared/truncate.ts）。注入字段会不会被误收为数字/名称真值？
C. **sentiment_defects 登记完整性**：grep 全 extension + main.py，找所有逐工具枚举的集合/分支/正则（KNOWN/TRUNCATABLE/TOOL_CATEGORIES/truthEmitters/注册漂移/前缀判断），有没有第五处漏登记（例如某处仍写死 6 个 sentiment 工具的循环或描述）。
D. **/sentiment/vehicles-all**：与 FastAPI auth 中间件的交互（服务令牌 X-Prism-Service 能否过闸？该端点是否被 /sentiment-board/{path:path} 反代路由吞掉？路由注册顺序）；sqlite 连接异常/空库时的行为；会不会被 SSRF/路径白名单逻辑拦。
E. **两级解析的边界**：空串/undefined 入参；fuzzy contains 误命中（"风云"会不会命中"风云T7"之外的车；"T7"单串命中什么）；fallback 网络失败时 active 快路径 catch fallthrough 的行为。
F. **测试质量**：sentiment_tools.test.ts 的动态 import + env 注入顺序是否有竞态/副作用（模块级 monkey-patch fetch 对测试进程的影响）；skip 语义是否合理。
G. **E2E 脚本**：verdict 竞态兜底逻辑（traj_pass 读末 N 行）在多用户并发对话时的误配对风险。

## 输出要求

写全文到 `C:\Users\<you>\Desktop\Prism-Agent\openspec\changes\舆情工具层跟进\step7-review.md`：
- 每个发现：P0（必须修/阻断）/P1（应修）/P2（建议）+ 文件:行号 + 复现证据或推理链；不确定标"疑"
- 末尾"无问题确认清单"：查过且确认没问题的维度（逐条列）
- 返回文本：发现计数摘要（P0/P1/P2 各几条，一句话/条）
