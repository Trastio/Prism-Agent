# 能力扩展与验证层重构 · Step8 Receiving Code Review

## 已修（P0 + P1 关键）
- P0-1 dispose 不设 manuallyDisposed → 加 this.manuallyDisposed = true
- P0-2 ctx.json 扫盘串读 → 改从 ctx session 目录精确读
- P0-3 mixed tier lib pass + web fail 硬死 → 降级告警（不阻断）
- P0-4 memory.json 路径不一致 → 统一用 userId
- P0-5 collectWebUrlsThisTurn toolResult 结构 → 检查两种结构（顶层+子条目）
- P1-1 calledTools 扫全 branch → 限制到本轮
- P1-3 URL 正则吞尾标点 → 加中文标点排除 + replace 修边

## 留下一轮（非阻塞）
- P1-2 NEG_RE 窗口只看前14字 + break（best-effort，层A提示词兜底）
- P1-4 verifyNamesWithWebExempt 完全跳过（简化实现，web tier 下可接受）
- P1-5 ctx.json 写在锁前（P0-2 精确路径已缓解）
- P1-6 attemptMap sessionId 碰撞（开发期单用户不触发）
- P2-1~P2-8 健壮性（留下一轮）
- Step6 simplify #1-#13（死代码清理/抽函数，留下一轮）
