# 身份强制移除 · Step 1 Explore

> 2026-10-07
> change: 身份强制移除
> 对象：[改造方案](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-身份强制移除-改造方案.md)
> 审查方法：逐行读代码核验

## 核验结果

### 身份强制（必删 2 处）
- ChatView.tsx L82 `if (!series) { setStatus('请先选择车系'); return; }` ✅
- index.ts L724-729 `if (!seriesKey) { setActiveTools([]); return 阻断 }` ✅
- index.ts L718 agent 模式已 `setActiveTools([...ALLOWED_TOOLS])` → 删 L724 后全量工具自然生效 ✅

### 2a series_key 持久化（新增必做）
- seriesKey 是 before_agent_start 局部变量，agent_settled 取不到 ✅
- ctx.json L706 被 unlinkSyncSafe 删除 → 不持久化则 2b 空转 ✅

### 2b 执行层判据（新增必做）
- agent_settled 读 prism-session-series-key entry（取最新一条） ✅
- tier=library 且 series_key 空 且 未调 resolve_series → reject ✅

### SYSTEM.md 对齐（4 处）
- L8 "汽车数据分析助手" → "汽车产品经理的助手" ✅
- L10 "业务问题" → 补"或通用问题" ✅
- L17 纪律4 没提 web_search ✅
- L16 纪律3 与 EXCLUDE_TOOLS 重复 ✅

### 其他
- L765 warningsText series 空时填"无"矛盾 ✅
- L735 seriesKey 空时仍 fetch ✅
- pi_gateway L399 ctx.json 写在 inflightLock 前 ✅
- completion.ts L124-128 NEG_RE break 弱于规格 ✅

## 待办（13 项，同方案改造清单）

- [ ] 1. ChatView L82 删拦截
- [ ] 2. index.ts L724-729 删身份强制
- [ ] 2a. index.ts before_agent_start 新增 appendEntry prism-session-series-key
- [ ] 2b. index.ts agent_settled 新增执行层判据
- [ ] 3. SYSTEM.md L8 角色
- [ ] 4. SYSTEM.md L10 补通用问题
- [ ] 5. SYSTEM.md L17 纪律4 补 web_search
- [ ] 6. SYSTEM.md L16 纪律3 简化
- [ ] 7. index.ts L765 series 空 warnings 引导
- [ ] 8. index.ts L735 seriesKey 空跳过 fetch
- [ ] 9. pi_gateway L399 ctx.json 移到 inflightLock 后
- [ ] 10. index.ts L715-717 bi_* 标注预留
- [ ] 11. completion.ts L124-128 NEG_RE 对齐规格
