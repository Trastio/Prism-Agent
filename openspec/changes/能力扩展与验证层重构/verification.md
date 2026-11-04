# 能力扩展与验证层重构 · Step9 Verification

## 验收

### 地基修复
1. ✅ verifyScope 内容组合（不读 claim.scope，NEG_RE 豁免）
2. ✅ 验证入口不再短路（hasEvidence → reject → verifyCompletion 查库）
3. ✅ runner L107 NEG_RE 豁免

### tier 路由
4. ✅ TrustTier + decideTier（基于工具调用，本轮限制 P1-1）
5. ✅ tier 路由 switch（library/web/mixed/none，包裹既有链路）
6. ✅ none tier 保留防编数（回落 decideVerification(text,false)）
7. ✅ M9 verifyNames 保留编造检测
8. ✅ M10 mixed tier 两侧验证 + P0-3 lib pass web fail 降级
9. ✅ URL 真值集（P0-5 两种 toolResult 结构 + P1-3 标点修边）
10. ✅ 降级告警（verdict.json web_downgrade，用户可见）

### web 解禁
11. ✅ EXCLUDE 删 web_search/web_fetch/mcp__pi-web-access
12. ✅ TOOL_CATEGORIES 一源（business/web/utility）
13. ✅ web-search.json 设 eager（M1）
14. ✅ H4 permission 无弹框（--approve 全局自动批准）

### 对齐
15. ✅ 回改加固 D 断言（EXTRA_TOOLS）
16. ✅ 上下文对象化（ctx.json 弃 prompt 前缀，P0-2 精确路径）
17. ✅ memory.json（P0-4 userId 路径统一 + 5 条上限 + 脱敏引用块0.5）
18. ✅ AGENTS.md 角色扩展 + 红线#1 分级 + injection + 库优先

### 网关治理
19. ✅ B1 mapEvent 事件补全（turn_start/end + session_info + 显式丢弃注释）
20. ✅ C 池上限 MAX_POOL + LRU + P0-1 dispose manuallyDisposed

### 共享层
21. ✅ redaction.ts 共享脱敏 + redaction.json 跨语言 spec
22. ✅ demoData.ts 演示数据外置

### 回归
23. ✅ smoke:all 5 smoke + 43 单测 0 fail
24. ✅ tsc 零错误
25. 🟡 端到端 web 搜索（H4 实测 settled 无弹框，但未完整跑 web 搜索题）
26. 🟡 人工评测（明天用户正式评估）

## 留下一轮
- P1-2/P1-4/P1-6 + P2-1~P2-8 健壮性
- Step6 simplify 抽函数/死代码清理
- 40 并发压测
- export_document 独立 change
