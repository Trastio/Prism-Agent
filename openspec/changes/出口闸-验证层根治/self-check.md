# 出口闸-验证层根治 · Step3.5 自查收敛

> 2026-10-07 · 对照方案 v1.5 + explore + 四件套逐项审查

## Gap 清单（7 项，全修）

### Gap 1【重要·设计遗漏】现行 2b 身份判据未安放

方案 §3.4 的 agent_settled 新职责没提现行 2b（`index.ts:874-896`：tier=library + series_key 空 + 未调 resolve_series → reject"未核验对象身份"）。若改道时顺手删掉，红线#7 执行层判据失守；若保留但没设计，与保底①的触发顺序不明。
**修正**：保底扩为三分支——①漏提交（library+数字形态+无通过提交）②凭空编造（none+数字形态+不在判定集）③身份未核验（**现行 2b 判据原样保留，优先级在①之前**：先验身份再验提交）。已同步 design.md §3 / specs/gate.md。

### Gap 2【运行时未证】execute 的 ctx.sessionManager 在 RPC extension 模式

explore 确认了**类型层**（types.d.ts:223），但现行 24 个工具都没用过 execute ctx——RPC 模式下是否实际注入无运行时证据。appendEntry 在 execute 闭包内调用同理。
**修正**：T-G4 前加 5 行微验证（临时在任一工具 execute 里 `console.error(typeof ctx?.sessionManager?.getEntries)` + pi.appendEntry 试写），不通过则降级方案（台账走 tool_result hook 单向写 + submit 校验改读 trajectories/自定义文件）。已同步 tasks.md。

### Gap 3 归一化细则不全

design 只写"去千分位/去单位"。散文 "−14.1%" 的负号与 % 、工具 JSON "retail_sum": 4436 的无单位形态、model 提交 value 的书写差异——三者必须归一到同一表示，否则 E2/E9 比对必假阴。
**修正**：归一化规则定死：去负号、去 %、去千分位、去单位、去前后空白；小数统一去尾零（"14.10"→"14.1"）；结果一律字符串。进 T-G2 单测（含 −14.1% / 4,436 辆 / 4436 三态同值用例）。

### Gap 4 E1-E9 跑批依赖 M5 提示词

E2/E3/E5 断言"模型会调 submit_conclusion"——这依赖 M5 提示词生效。tasks 原写 M3/M4/M5 可并行，若 M4 跑批先于 M5，全崩。
**修正**：T-E1~E4 可并行开发，**T-E5（全量跑）必须 after M5**。已同步 tasks.md 依赖行。

### Gap 5 C3 改变错误形态的统计联动

C3 把失败改为 isError=false + `{status:'unavailable'}` → runner 现行"接口错误"关键词统计（conversation 口径）与前端 tool_result 的 is_error 标记全部失效。
**修正**：T-C3 加联动项——runner 错误统计口径同步（匹配 status:'unavailable'）；E7 断言基于新形态。

### Gap 6 attemptMap 归属含糊

T-S4 写"attemptMap 同步迁移或保留"——含糊。事实：D7 后 verifyCompletion 仍被 **mixed 分支**（index.ts:912，维持现行不动 per D4）使用，其 attemptMap 不能删。
**定死**：attemptMap 保留服务 mixed 分支（进程内、现行行为）；library/none **保底**的 attempt 与同因签名走 `prism-verifier-state` entry（跨重启持久，N9 由它达成）。已同步 specs/state.md。

### Gap 7 台账回写顺序（fail-open 风险）

submit pass 时 appendEntry 两个（verified + numeric-truth 回写）。若先写 verified 再回写、回写 throw 被静默 catch → 复述保护缺失且无标记。
**修正**：顺序定死——**先回写台账、后写 verified**（verified 是"本轮通过"的判据 entry，回写失败则不写 verified，submission 判不通过、模型收到拒绝重试——fail-closed 方向）。

## 九宫格枚举（tier × 有无提交 × 数字形态，含 Gap1 修正后）

| tier | 通过提交 | 数字形态 | 结果 |
|---|---|---|---|
| library | 有 | 任意 | pass（保底③身份判据在前，身份未核验仍拦） |
| library | 无 | 有 | 保底①拦截（区分未提交/被拒未修正） |
| library | 无 | 无 | pass（过程叙述） |
| none | — | 有·在判定集 | pass（复述） |
| none | — | 有·不在 | 保底②拦截（任一数字不可溯源即拦） |
| none | — | 无 | pass |
| web | — | — | 现行 URL 真值集（不动） |
| mixed | — | — | 现行库+web 双验（不动） |
| （2b）library+无身份+无 resolve | — | — | 保底③拦截（现行判据原样） |

完备性：无漏格。

## 结论

7 Gap 全修（Gap2 留运行时微验证门，不通过则走降级方案）；九宫格完备；E/N 对应关系沿用方案 v1.5 §八。**可进 Step5 施工**。
