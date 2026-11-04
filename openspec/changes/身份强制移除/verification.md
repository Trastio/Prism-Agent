# 身份强制移除 · Step9 Verification

## 验收
1. ✅ 不选车系能发消息（端到端验证"你好"→ agent 回复）
2. ✅ 身份强制删除（ChatView L82 + extension L724-729）
3. ✅ 2a series_key 持久化（无条件 appendEntry prism-session-series-key）
4. ✅ 2b 执行层判据（tier=library + series_key 空 + 未调 resolve_series → reject + 重试门禁）
5. ✅ SYSTEM.md 角色对齐（"汽车产品经理的助手"）
6. ✅ SYSTEM.md 纪律4 含 web_search
7. ✅ SYSTEM.md 纪律3 简化
8. ✅ series 空 {warnings} 引导非"无"
9. ✅ seriesKey 空跳过 fetch
10. ✅ ctx.json 写在 inflightLock 后
11. ✅ NEG_RE 逐词判定（对齐规格）
12. ✅ bi_* 标注预留
13. ✅ smoke:all 5+43 全过 + tsc 零错 + 端到端通过
