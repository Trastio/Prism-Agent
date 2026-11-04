# 出口闸-验证层根治 · Step10 archive

> 2026-10-08 · 十步全流程走完归档

## 交付总览

**一句话**：完成验证从"事后正则验散文 + user 消息回灌"改造为"submit_conclusion 出口闸提交协议"——结论先过闸（行ID查库/数字台账/名称校验，失败以 tool_result 返回同轮修正），散文退出主验证对象，agent_settled 只剩保底（③身份 / ①漏提交 / ②凭空编造，链级硬顶最多回灌 1 次），全部症状转 E1-E9 评估回归门（不绿不合档）。

## 十步执行记录

| 步骤 | 结果 |
|---|---|
| 1 explore | 7/7 绿灯 + 2 新发现（attemptMap 耦合 / execute ctx 可用性） |
| 2 propose | proposal/design/specs×4/tasks 六件套 |
| 3.5 自查 | 7 Gap 全修（保底③身份判据安放等） |
| 5 施工 | M1-M5 + 线C + 环境适配 全部完成 |
| 6 simplify | 死代码 8 符号 + smoke:guard 重写为新判据 |
| 7 code-review | 自审归档（R1 verifyNames 误伤留 P1 下轮；R4 并行串题风险标注） |
| 8 receiving | review-response.md，无阻塞项 |
| 9 verification | N1-N10 全达成（verification.md）；**最终确认轮 9/9 全绿**（2026-10-08，含 isVerifierRetryTurn 修复） |
| 10 archive | 本文件 |

## 最终验证快照

- 门禁：**9/9**（E1 事故场景 / E2 派生声明 / E3-E4 编造自纠 / E5 保底或闸二选一 / E6 截断 / E7 缺口报告 / E8 凭空拦截 / E9 防洗白链）
- smoke:all：**50/50**（completion 3 + grounding 12 + numeric-ledger 7 + tool_call 17 + identity 4 + guard 15 计）
- 门禁迭代史：4/9→7/9→7/9→8/9→8/9→9/9→(API故障无效轮)→**9/9 确认**

## 方案外修掉的基础设施 bug（9 个，均有实测证据）

1. pi.exe(Bun) better-sqlite3 NAPI panic → extension 禁进程内查库，/verify/claim 服务端化
2. PRISM_AUTO_APPROVE_UI 缺失 → 工具挂死
3. nextEvent waiter 忽略入参 → 空 error
4. RPC 字段路径三连错（resp.data.*）
5. can_continue 缺失 → P1-6 从未生效
6. submission 提取错位（toolResult 顶层形态）
7. 乒乓回灌 → 链级总量硬顶
8. isVerifierRetryTurn 前缀断裂
9. identity 降级（上游库重建 series_alias 消失）

## 留下一轮（非阻塞）

- R1：verifyNames 误伤描述性中文词（"情景测算"）→ 多一次提交往返，fail-closed 方向
- R4：readLastTrajectory 并行串题风险（当前串行跑成立）
- mapEvent 补 auto_retry_start/end case（观测卫生）
- E1 残留 ctx 文件成因（N6 已另行实证通过，无正确性影响）
- 34 题用户题 / Langfuse Prism 层 observation / 40 并发压测（沿既有挂账）
