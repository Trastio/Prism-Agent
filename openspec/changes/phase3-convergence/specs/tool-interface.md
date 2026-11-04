# Spec 2.2 · 工具接口层

> Step 1 接线 + Step 2 身份 + Step 4 护栏。前置 [design.md](./design.md)。

## 待办
- 1.1 职责定夺（permission-system 工具级 + guardrail 行为级 + fail-closed）
- 1.2 tool_call fail-closed 未知工具
- 1.3 agent_settled 移植 completion.ts 替换内联 regex
- 1.4 退役 src/tools/query_*.ts（保留到 Step10）
- 2.5 extension 注册 resolve_series 工具
- 2.6 FastAPI /identity/resolve 端点
- 4.2 tool_result grounding 名称维度扩展（import verifyNames）
- 4.4 8 名称测试集搬 extension

## 设计细节

**1.1 职责定夺**：
- 删 extension L397-398 旧注释
- permission-system（settings.json L3 已运行）：工具级批准，弹确认框
- guardrail（extension tool_call）：行为级拦截（裸SQL/敏感文件/数据库直连）+ fail-closed 未知工具
- 不重叠，叠加

**1.2 fail-closed**：
- 23 注册工具白名单：query_reviews/sales/config + sentiment_*6 + Atuohome 14 + resolve_series
- tool_call hook 末尾：toolName 不在白名单→`{block:true, reason:'未知工具 '+toolName, terminate:false}`
- 这是"工具存在性"校验，非"权限"校验

**1.3 移植 completion.ts**：
- 删 extension decideVerification（287-313）+ 正则常量（257-278）+ calledSemanticToolsThisTurn（330-351，保留改用）
- import `{ verifyCompletion, type Claim } from '../../../src/verify/completion.ts'`（Gap 6 修正：三级相对路径）
- agent_settled 调 verifyCompletion(sessionId, claim, identity_coverage)
- VerifyResult.pass→放行；retry→appendCustomMessageEntry max1；fail→终止
- 行ID查库走 completion.ts 的 verifySupportedBy（prism_views.db，依赖 better-sqlite3）

**2.5 resolve_series 工具 + 强制前置核验（Gap 4 修正）**：
- registerTool resolve_series，参数 {series_key: string}，execute fetch `${FASTAPI}/identity/resolve?series_key=xxx`，返回 IdentityResult（供 agent 查询详情用）
- **强制前置核验**：before_agent_start hook 内，extension 直接 fetch `/identity/resolve?series_key=<前缀解析的 series_key>`，未命中→fail-closed 阻断本轮（systemPrompt 返回阻断提示）。不依赖 agent 主动调 resolve_series 工具。

**2.6 /identity/resolve**：
- main.py 新增 GET /identity/resolve
- 读 series_alias（精确 raw_name + LIKE）→ series_summaries（series_id）→ sales_trim/owner_reviews/config_snapshots（覆盖率）
- 移植 src/identity/resolve.ts:147-214 逻辑到 Python

**4.2 grounding 名称扩展**：
- extension tool_result（416-445）当前只收集 prism-name-truth
- import `{ verifyNames, collectNameTruth } from '../../src/verify/grounding.ts'`
- tool_result 调 verifyNames 校验返回的名称 vs 真值集
- 不匹配→改写 tool_result 标注 + fail-closed 提示

**4.4 8 测试集（Gap 7 修正：不搬代码，import 引用）**：
- extension 直接 import `../../../src/verify/grounding.ts` 的 verifyNames/collectNameTruth
- 8 测试集留原位置 src/verify/smoke.ts:43-53，smoke:grounding 跑原位置
- extension 的 grounding 校验调 grounding.ts 函数，不搬代码到 extension 目录

## 验收
- 未知工具（如 read_file）→block
- 裸SQL `DROP TABLE`→block
- 报告①越界 fail / 报告③无 supported_by fail
- 8 名称错误 100% 拦截
- resolve_series 银河E5 命中/铂智7X needs_online_verify/虚构 fail-closed
- /identity/resolve 返回正确 IdentityResult

## 依赖
- completion.ts 移植需 better-sqlite3（prism_views.db 查库）—— Gap 1：extension import 第三方包验证（better-sqlite3 + langfuse，Step6.1 前置）
- extension 目录无 package.json/tsconfig，pi 子进程模块解析需验证能 resolve 项目 node_modules
