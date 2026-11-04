# spec · 出口闸与数字台账（M1-M2）

## 待办清单

1. `src/verify/completion.ts`：提取 `verifyClaimChecks(claim, identity_coverage?)` 纯函数（D7）；verifyCompletion 行为不变
2. `index.ts` 注册 `submit_conclusion`（三处白名单同步：KNOWN_BUSINESS_TOOLS / TOOL_CATEGORIES.business / decideTier hasLib）
3. execute 实现：读 entries → verifyClaimChecks → 数字校验（tool∈truth；derived_from 每个∈truth，declaredDerived 不算）→ verifyNames → pass 则 appendEntry('prism-conclusion-verified') + 台账回写（tool→truth / derived→declaredDerived）；拒则返回 ≤2KB 拒绝文本
4. tool_result hook 扩采：business 全部数据工具；归一化排除标识符 key（series_id/spec_id/model_id/post_id/vehicle_id/year/month）与错误载荷（isError / unavailable）
5. agent_settled 改道（3.5 后三分支保底）：**保底③身份未核验（现行 2b 原样平移，优先级最高）** → ①通过提交→pass → ②保底①漏提交（library+数字形态+无通过提交） → ③保底②凭空编造（none+数字形态+任一数字 ∉ truth∪declaredDerived） → ④web/mixed 不动；⑤回灌文案语义化（"系统校验通知，直接调 submit_conclusion，不要回复本通知"）
5b. 台账回写顺序：先 numeric-truth 回写、后 conclusion-verified（回写失败不写 verified，fail-closed）
6. decideVerification/REJECT_MSG 粗筛路径退役（被保底②取代），单测同步更新

## 设计细节

- 台账 entry：`prism-numeric-truth { values: string[], kind?: 'declared-derived' }`，读取 union
- 归一化 util 单一实现，②保底与采集共用；细则：去负号/%/千分位/单位/空白 + 小数去尾零，字符串输出（三态同值单测）
- T-G4 前置微验证（3.5 Gap2）：execute ctx.sessionManager 与 pi.appendEntry 在 RPC 模式实际注入验证（5 行 console.error 探针）；不通过走降级方案（台账单向写 + submit 读旁路文件）
- 回写发生在 submission pass 的 execute 内（同轮后续复述立即受保护）
- 保底①文案区分"未提交"与"提交被拒未修正"（本轮有 rejected submission entry 时用后者）

## 验收标准

- E2/E3/E4/E5/E8/E9 全绿；N1/N2/N3/N4 达成
- smoke:all 36 单测不回归；新增 verifyClaimChecks / 归一化排除 / 台账读写单测全过
- 闲聊"你是谁"在含历史数字长会话中 settled=1
