# 身份强制移除 · Step8 Receiving Code Review

## 已修
- P1 2b reject 路径无重试门禁 → 加 isVerifierRetryTurn 门禁 + canRetry 条件回灌

## 留下一轮
- P1 verdict.json 不写 can_continue（既有，非本轮引入）
- P2 verifySupportedBy finally 二次抛错
- P2 mixed tier 2b 覆盖（设计选择）
- P2 PRODUCT_RE 维度词不全
- P2 2a 写入早于 canonical 归一
- simplify 4 项（抽 rejectTurn / extractClaim 复用 / findCurrentTurnStart / identity-coverage helper）
