# Spec 2.3 · 验证层

> Step 1.3 验证器移植 + Step 6 verdict 事件。前置 [design.md](./design.md)。

## 待办
- 1.3 CLAIM/VERIFY 移植 completion.ts
- 6.4 verdict 事件进 mapEvent
- 4.3 越界检查完整化（verifyScope 替换正则）
- 5.10 鉴权（管理者 vs 只读，红线#3）

## 设计细节

**1.3 CLAIM/VERIFY**：
- completion.ts 已实现：verifySupportedBy（行ID查库 46-67）+ verifyScope（越界 109-128）+ verifyDataGaps（缺口 131-144）+ attemptMap max1（150）
- agent_settled hook 改调 verifyCompletion
- CLAIM 结构：conclusion_text + supported_by(行ID) + as_of + scope
- VERIFY：行ID存在 / as_of 一致 / 越界检查 / 缺口声明

**6.4 verdict 事件**：
- pi_gateway mapEvent（40-72）当前 agent_settled→settled（60-61）
- 改为：agent_settled 时验证器结果透传 `{type:'verdict', data:{verdict:'pass|retry|fail', evidence_ids, scope, reason}}`
- 前端 ChatView 收到 verdict→状态栏显示 + EvidenceDrawer 联动
- runner 读 verdict 评分（Step9）

**4.3 越界完整化**：
- 当前内联正则只查"市场侧印证/佐证/支撑"
- verifyScope（completion.ts:109-128）查完整模式：口碑结论越市场侧 / 市场侧归因产品力 / 跨维度越界
- 移植后自动生效

**5.10 鉴权**：
- env PRISM_MANAGER_PASSWORD 配置
- main.py 中间件：写端点（/autohome/{tool} POST + 采集触发 + /config/* POST）要求密码 header
- 前端管理者操作弹密码框→带 header 请求
- 普通查询（/dashboard /chat/stream /identity/resolve /events GET）只读不挡
- 与 permission-system（工具级）叠加：permission-system 管 pi 工具批准，此处管 FastAPI 业务端点

## 验收
- 报告①"市场侧印证舒适性"→越界 fail
- 报告③无 supported_by→fail
- 数据缺口未声明→fail
- 行ID不存在→fail
- verdict 事件前端可见
- 管理者操作无密码→401；有密码→通过；普通查询不挡

## 依赖
- Step 1.3 移植完成（verdict 才有内容）
- Step 6 mapEvent 改动
