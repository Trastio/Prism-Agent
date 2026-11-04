# 能力扩展与验证层重构 · Step 1 Explore

> 2026-10-07
> change: 能力扩展与验证层重构
> 对象：[改造计划 v8](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-能力扩展与验证层重构-改造计划.md)
> 性质：探查代码现状（亲自核验，非依赖审查报告）

---

## 1. 探查方法

主会话亲自 grep + Read + Bash 核验 v8 全部关键断言。

---

## 2. 核验结果（逐条）

### 块0.5 D-1 脱敏双实现
- tracker.ts:20 `sanitize()` JS VIN `[A-HJ-NPR-Z0-9]{17}` + 车牌正则 ✅
- main.py:86 `_VIN_RE` / `_PLATE_RE` Python，与 JS 逐字同正则 ✅
- 两处独立实现，改一处忘另一处 → 漂移风险 ✅

### 块0.5 D-2 演示数据硬编码
- MarketBoard.tsx:77-91 版型结构（530 探索版 2047）+ 竞品对比（理想 L6 3379→9878）硬编码 ✅
- ReviewsBoard.tsx:103 舒适样本（k_5789427 颠簸）硬编码 ✅
- DemoCard 默认折叠已缓解视觉分区，但数据仍内联生产组件 ✅

### 块1.1 cross 越界根因
- completion.ts:113-125 verifyScope 只查 `scope==='口碑内'` 和 `'市场侧不归因'` ✅
- index.ts:422-425 extractClaim scope 推断：跨维度回复两条互斥条件不成立 → 落 `'跨维度'` ✅
- verifyScope 对 `'跨维度'` 无检查 → 整段跳过 ✅

### 块1.2 trap-05 验证入口短路
- index.ts:713-721 decideVerification pass 即 return，verifyCompletion 从不执行 ✅
- index.ts:348 EVIDENCE_RE `/review_tags|sales_trim|config_snapshots|mv_|supported_by/i` 子串匹配 ✅
- 假行 ID 也过 hasEvidence → pass → verifySupportedBy 没机会跑 ✅
- completion.ts:59-61 verifySupportedBy 已对"库中无"判 fail（它没问题，问题是没被调用）✅

### 块1.3 trap-06 同 1.2
- verifyDataGaps 只在 reject 路径执行（被 1.2 短路了）✅
- identity_coverage entry 链路本身正常（P2-8 已修）✅

### 块2 tier 路由
- tier 基于工具调用（非回复内容）✅ 避免时序死锁
- tier 路由包裹既有链路非替换（library/none 回落 decideVerification）✅
- none tier 不无条件 pass（回落 decideVerification(text,false) 保留防编数）✅

### 块3 web 解禁
- pi-web-access 真实工具名：web_search / fetch_content / source_check / get_search_content ✅
- EXCLUDE 含 web_search（pi_gateway.mjs:28）✅
- web_fetch 是无效名（不匹配任何工具）✅
- web-search.json 不存在 → 默认 toolActivation=auto ✅
- M1-b pi-web-access before_agent_start 调 setActiveTools（tool-activation.ts:146-149）✅
- M1-b guardrails 后加载会覆盖 pi-web-access 的 loader ✅

### 块4 上下文对象化
- prompt 前缀 [ctx:...]（pi_gateway.mjs:357-359）✅
- pi RPC metadata 能力未确认（grep extensions.md/rpc.md 零命中）→ 需施工前核实 ✅

### 块5 网关治理
- 池无上限（pi_gateway.mjs:333 只有 poolSize 无 MAX_POOL）✅
- mapEvent default return null（pi_gateway.mjs:92）静默丢弃 turn_*/message_* ✅
- session_info 未实现（L102 注释意图但 mapEvent 无 case）✅

---

## 3. 待办清单（按 v8 块组织）

### 块0.5（须早于块4）
- 0.5.1 新建 src/shared/redaction.ts（纯 TS，禁 node/DOM）
- 0.5.2 extension + tracker.ts 改用共享模块
- 0.5.3 跨语言 spec（shared/redaction.json）+ parity 测试
- 0.5.4 演示数据外置 demoData.ts
- 0.5.5 实测 prism-web 能否 import 仓库根 src/shared

### 块1（修地基）
- 1.1 verifyScope 改内容组合（不读 claim.scope）+ NEG_RE 豁免
- 1.2 decideVerification hasEvidence 分支不再终判 → 路由 verifyCompletion
- 1.3 同 1.2（统一"有数据结论即走 verifyCompletion 全套"）
- 1.4 trap-04 待评估确认（runner 是否传 series_key）
- 1.5 runner L107 加 NEG_RE 豁免

### 块2（tier 路由）
- 2.1 TOOL_CATEGORIES 定义（business/web/utility）
- 2.2 decideTier 函数（基于工具调用）
- 2.3 tier 路由 switch（library/web/mixed/none，包裹既有链路）
- 2.4 verifyWeb + verifyMixed 新函数
- 2.5 M9 verifyNames 修正（只拦 truthNames 内名称，库外名须在 web 真值集）
- 2.6 collectWebUrlsThisTurn（branch 现算）
- 2.7 N3 降级告警（verdict.json web_downgrade）

### 块3（web 解禁）
- 3.1 M1 实测（web-search.json 设 eager + 验闸1/闸2）
- 3.2 EXCLUDE 删 web_search/web_fetch/mcp__pi-web-access
- 3.3 ALLOWED_TOOLS 加 web 工具
- 3.4 setActiveTools agent 含 web
- 3.5 AGENTS.md + SYSTEM.md 提示词（角色扩展 + 红线#1 分级 + injection 防护 + 库优先 + web 轮数）

### 块4（对齐，依赖块0.5）
- 4.1 回改加固计划 D 断言
- 4.2 上下文对象化（核实 pi RPC metadata → 显式通道或退化 ctx.json）
- 4.3 移除 prompt 前缀解析与 strip
- 4.4 memory.json（user_id 隔离 + 5 条上限 + 脱敏引用块0.5）
- 4.5 单测 + 评测

### 块5（网关治理，无依赖可并行）
- 5.1 B1 mapEvent 事件表补全 + session_info
- 5.2 C 池上限 MAX_POOL + LRU + 排队 + 40 并发压测

---

## 4. 下一步

进 Step2 propose：proposal.md + design.md + tasks.md。
