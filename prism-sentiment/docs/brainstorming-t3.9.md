# Brainstorming: T3.9 锚点上下文对话

## 需求回顾

用户点击看板图表元素（趋势折线、平台饼图、事件柱状图、异常时间线），弹出侧边对话面板，自动注入锚点上下文，支持 SSE 流式对话和 Generative UI 回复。

## 设计决策

| # | 问题 | 决策 | 关键理由 |
|---|------|------|---------|
| 1 | 后端 API 结构 | 新增 `api/routes/dialog.py`，两个端点 | 与 spec 一致，职责独立 |
| 2 | SSE 流式格式 | `data: {type, content}\n\n` 协议 | 简单可靠，Vue 原生 EventSource 可解析 |
| 3 | Generative UI 协议 | LLM 返回 JSON blocks，前端按 type 渲染 | spec 已定义 5 种类型，结构化解析 |
| 4 | 上下文注入 | 后端组装锚点数据 + 相关帖子 + 统计信息 | 前端只需传 anchor_type + anchor_data，后端查 DB |
| 5 | 对话存储 | dialog_conversations + dialog_messages 表已存在 | 无需新建表，直接用 |
| 6 | 前端面板 | CSS slide-out panel，Vue 3 动态组件 | 最小改动，复用已有 CDN 架构 |
| 7 | 图表点击事件 | ECharts `onClick` 事件 → 打开对话面板 | 标准 ECharts API，零侵入 |
| 8 | LLM 调用 | DeepSeek-V4-Flash，与 analyzer/reports 一致 | 统一 API 配置 |

## 后端 API 设计

```
POST /api/dialog/anchor
  body: AnchorDialogRequest {
    vehicle_id: str
    anchor_type: str          # trend | platform | event | anomaly
    anchor_data: dict         # {date, value, ...} 点击的具体数据点
    message: str              # 用户消息（首轮为空则自动生成摘要问题）
    conversation_id?: str     # 续轮对话时传入
  }
  response: SSE stream
    data: {"type": "text", "content": "..."}
    data: {"type": "chart", "config": {...}}
    data: {"type": "table", "headers": [...], "rows": [...]}
    data: {"type": "stat_cards", "cards": [...]}
    data: {"type": "post_list", "posts": [...]}
    data: {"type": "done", "conversation_id": "..."}

GET /api/dialog/{conversation_id}/history
  response: [{role, content, generative_ui, created_at}]
```

## 上下文注入策略

按 anchor_type 查询不同数据：
- **trend**: 指定日期 ±3 天的帖子 + 情感分布 + 热度指标
- **platform**: 指定平台的所有帖子样本 + 情感分布
- **event**: 指定事件标签的帖子 + 时间分布
- **anomaly**: 异常日期 ±3 天的帖子 + 声量对比

## Generative UI 渲染

LLM prompt 指示返回结构化 JSON blocks：
```
[GEN_UI:text]这是分析文本...[/GEN_UI]
[GEN_UI:chart]{"title":"情感趋势","xAxis":...}[/GEN_UI]
```
前端用正则提取 blocks，按 type 动态渲染 Vue 组件。

## 实现范围

TDD 原子任务：
1. **T3.9.1** 测试 + 实现：Dialog API 后端（SSE 流式 + 历史查询）
2. **T3.9.2** 测试 + 实现：上下文注入（按 anchor_type 查 DB）
3. **T3.9.3** 测试 + 实现：前端对话面板 + 图表点击事件 + Generative UI 渲染

3 个 commit。
