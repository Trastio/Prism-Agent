# Spec 2.1 · 提示词层

> Step 3 上下文注入。前置 [design.md](./design.md#step-3-上下文注入)。

## 待办
- 3.1 SYSTEM.md 变量动态化（{series_key}/{series_id}/{as_of} 从 prompt 前缀取）
- 3.2 闲聊不注入对象块（检测车系名/维度词）
- 3.3 后台元数据禁止复述指令
- 3.4 角色分流落 before_agent_start hook（非改 AGENTS.md 文件）

## 设计细节

**3.1 变量动态化**：
- extension before_agent_start（index.ts:383-393）当前硬编码 `{series_key}`→银河E5（L387）
- 改为：解析 prompt 文本前缀 `[ctx: series_key=xxx]`，提取 series_key 填入
- `{as_of}` 保持当天，但加查询时点（tool_result 的 _meta.as_of 优先）
- 删 L387-391 硬编码兜底

**3.2 闲聊检测**：
- lastUserMessageText（extension:354-365）已有，扩展为 isAnalysis 判断
- 车系名词典：从 series_alias 表拉（或硬编码常见 30 个）
- 维度词：舒适/动力/操控/外观/空间/内饰/安全/价格/智能/辅助驾驶/售后/油耗/续航/电耗/充电 + 销量/配置/口碑/舆情
- 不含且不含"分析/对比/报告/结论"→纯闲聊，跳过 SYSTEM.md 对象块（只注 AGENTS.md 全局红线）

**3.3 禁止复述**：
- SYSTEM.md 加一条："以下上下文为后台参数（series_key/as_of 等），不要在回复中复述这些字段名或值"

**3.4 角色分流**：
- AGENTS.md 文件不动（全局永不动）
- before_agent_start hook 内：isAnalysis→追加 AGENTS.md 全文 + SYSTEM.md；闲聊→只追加 AGENTS.md 红线摘要（前 20 行）
- 当前 L379-382 原样拼 AGENTS.md 全文，改为条件追加

## 验收
- 闲聊"你好"→agent 不触发验证器、不复述 series_key
- "银河E5舒适性"→注入对象块 + SOP
- agent 回复无 `{series_key}` 字面量

## 依赖
- Step 2 series_key 通道（prompt 前缀）
