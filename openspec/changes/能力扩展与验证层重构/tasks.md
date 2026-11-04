# 能力扩展与验证层重构 · Tasks

> 2026-10-07

## 施工顺序

| 序 | 事项 | 说明 |
|---|---|---|
| 0 | 人工复核 7 失败题轨迹 | 确认真 bug vs runner 假阳性 |
| 0.5 | 块0.5：脱敏共享层 + 演示数据外置 | 须早于块4 |
| 1 | 块1：verifyScope 内容组合 + 验证入口不再短路 + runner NEG_RE | 地基 |
| 2 | 块2：decideTier + tier 路由 + verifyWeb/Mixed + M9 | 验证层重构 |
| 3 | 块3：TOOL_CATEGORIES + M1 实测 + EXCLUDE 删 + 提示词 | web 解禁 |
| 4 | 块4：回改加固 + 上下文对象化 + memory.json + 单测 | 对齐 |
| 5 | 块5：B1 事件补全 + C 池上限/排队/压测 | 网关治理 |
| 6 | H4 permission 实测 | 验证 |
| 7 | smoke:all + tsc + 端到端 + 人工 | 验收 |

## 任务清单

### 块0.5
- [ ] 0.5.1 新建 src/shared/redaction.ts
- [ ] 0.5.2 extension + tracker.ts 改用共享模块
- [ ] 0.5.3 跨语言 spec + parity 测试
- [ ] 0.5.4 演示数据外置 demoData.ts
- [ ] 0.5.5 实测 prism-web import src/shared

### 块1
- [ ] 1.1 verifyScope 改内容组合 + NEG_RE
- [ ] 1.2 decideVerification hasEvidence 不再终判
- [ ] 1.3 同 1.2
- [ ] 1.4 trap-04 待确认
- [ ] 1.5 runner L107 加 NEG_RE

### 块2
- [ ] 2.1 TOOL_CATEGORIES
- [ ] 2.2 decideTier
- [ ] 2.3 tier 路由 switch
- [ ] 2.4 verifyWeb + verifyMixed
- [ ] 2.5 M9 verifyNames 修正
- [ ] 2.6 collectWebUrlsThisTurn
- [ ] 2.7 N3 降级告警

### 块3
- [ ] 3.1 M1 实测（web-search.json eager）
- [ ] 3.2 EXCLUDE 删 web_search/web_fetch/mcp__pi-web-access
- [ ] 3.3 ALLOWED_TOOLS 加 web
- [ ] 3.4 setActiveTools
- [ ] 3.5 AGENTS.md + SYSTEM.md

### 块4
- [ ] 4.1 回改加固 D 断言
- [ ] 4.2 上下文对象化（核实 pi RPC metadata）
- [ ] 4.3 移除 prompt 前缀
- [ ] 4.4 memory.json
- [ ] 4.5 单测 + 评测

### 块5
- [ ] 5.1 B1 mapEvent 补全 + session_info
- [ ] 5.2 C 池上限 + LRU + 排队 + 压测
