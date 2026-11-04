# Prism-Agent 能力扩展 + 插件补全方案

> 2026-10-05
> 目标：① 接入两项目原子能力（20+ 工具）② 扩展用户群体（不只汽车 PM）③ 补全 pi 插件

---

## 一、两项目原子能力接入

### 1.1 舆情 Board（21 个 GET 端点 → 6 个语义工具组）

Prism 不重造舆情看板（iframe 嵌入），但 agent 需要能调舆情数据做分析。

| 工具组 | 对应端点 | 用途 |
|---|---|---|
| sentiment_overview | /overview, /heat-metrics, /sentiment-summary | 声量/情绪总览 |
| sentiment_trend | /trend, /sentiment-trend, /increment-overview, /comment-sentiment-trend | 趋势分析 |
| sentiment_dimension | /dim-sentiment, /dim-examples, /comment-sentiment-overview, /comment-sentiment-diff | 维度热帖+示例 |
| sentiment_posts | /top-posts, /posts, /post-comments, /top-opinions | 帖子原文 |
| sentiment_competitive | /competitor-comparison, /fleet-overview | 竞品声量 |
| sentiment_events | /top-events, /vehicles/{id}/events, /event-distribution, /negative-radar | 事件预警 |

**实现**：prism-guardrails extension 注册 6 个 `sentiment_*` 工具，execute 调 FastAPI `/sentiment-board/{path}` 反代 → 舆情 Board :8000。

### 1.2 Atuohome（15 个 MCP 工具 → Prism 语义工具）

| 工具 | 来源 | Prism 注册名 | 用途 |
|---|---|---|---|
| search_cars | MCP | search_cars | 车型搜索 |
| get_model_detail | MCP | get_model_detail | 车型详情 |
| get_model_generations | MCP | get_model_generations | 代际 |
| get_similar_models | MCP | get_similar_models | 相似车型 |
| get_trims | MCP | get_trims | 版型列表 |
| get_config | MCP | get_config_detail | 配置详情（比 query_config 更细） |
| get_review_analysis | MCP | get_review_analysis | 标签聚合（比 query_reviews 更细） |
| search_reviews | MCP | search_reviews | 全文检索 |
| get_dimension_reviews | MCP | get_dimension_reviews | 维度原文 |
| get_energy_analysis | MCP | get_energy_analysis | 能耗 |
| search_news | MCP | search_news | 资讯 |
| get_dealer_price | MCP | get_dealer_price | 经销商报价 |
| get_sales_data | MCP | get_sales_detail | 销量明细（比 query_sales 更细） |
| score_models | MCP | score_models | 评分 |
| fetch_reviews | MCP | ❌ 不接（红线：采集需管理者授权） |

**实现**：FastAPI 加 `/mcp/{tool_name}` 反代 → Atuohome :8001 MCP。extension 注册 14 个工具，execute 调 FastAPI 反代。

### 1.3 工具总数

| 类别 | 工具数 |
|---|---|
| 口径视图（已有） | 3（query_reviews/sales/config） |
| 舆情（新增） | 6（sentiment_*） |
| Atuohome（新增） | 14（search/detail/generations/similar/trims/config_detail/review_analysis/search_reviews/dimension_reviews/energy/news/dealer_price/sales_detail/score） |
| **总计** | **23** |

---

## 二、扩展用户群体（不只汽车 PM）

### 2.1 当前定位
提纲定义 Prism 是"汽车 PM 竞品分析 data agent"——棱镜三维度（配置/口碑/销量）+ 舆情外挂。

### 2.2 扩展方向
普通用户（非 PM）的需求：
- **买车选车**：对比车型、看口碑、查报价 → 需 search_cars/get_similar_models/get_dealer_price/search_reviews
- **用车养车**：能耗分析、缺陷主题、维修口碑 → 需 get_energy_analysis/defect-themes/get_dimension_reviews
- **行业关注**：资讯、销量趋势、舆情事件 → 需 search_news/get_sales_detail/sentiment_events
- **报告生成**：自动生成对比报告/选车建议 → 需 write/edit + score_models

### 2.3 模式扩展
当前两个模式：BI 看板 + Agent 对话。加第三个：
- **选车助手模式**：普通用户场景，工具白名单只开放只读查询（search/reviews/sales/config/news/energy/price），不开放写/采集/评分。SYSTEM.md 注入"选车助手"人设而非"汽车 PM"。

### 2.4 权限分层（pi-permission-system）
| 角色 | 工具白名单 | 红线 |
|---|---|---|
| 普通用户 | search/reviews/sales/config/news/energy/price/sentiment_* | 只读，无写无采集 |
| 汽车 PM | + score_models + get_model_detail/generations/trims | 只读 + 评分 |
| 管理者 | + fetch_reviews（采集触发） + write/edit（报告生成） | 需密码弹窗 |

---

## 三、pi 插件补全

### 3.1 已装（7 个）
permission-system / cc-safety-net / langfuse / web-access / ask-user / usage / subagents

### 3.2 需补装的

| 插件 | 用途 | 理由 |
|---|---|---|
| pi-memory | 显性记忆（跨会话记住用户偏好/常用车系） | 普通用户"上次看了银河E5"不需要重说 |
| @amaster.ai/pi-memory-mem0 | 隐性记忆 | agent 主动关联"你上次问过续航，这次看油耗？" |
| rpiv-todo | 任务清单面板 | PM 多步骤分析"先看配置→再看口碑→再看销量"的进度跟踪 |
| pi-mcp-adapter | MCP 桥 | Atuohome 15 个 MCP 工具的 stdio 桥（如不走 FastAPI 反代） |
| pi-mega-compact | 上下文压缩增强 | 23 个工具 + 长对话，默认 compaction 可能不够 |
| pi-workspace-history | workspace undo/redo | 用户"回退到上一轮"安全网 |

### 3.3 不装的
| 插件 | 理由 |
|---|---|
| pi-soly | 工作流引擎，棱镜 SOP 已在 AGENTS.md |
| pi-claude-marketplace | 不需要 Claude Code 插件市场 |
| pi-zentui | 不需要 TUI 主题 |
| @remnic/plugin-pi | 与 pi-memory 重复 |

### 3.4 总插件数
已有 7 + 补装 6 = **13 个**

---

## 四、实施路径

1. **舆情 6 工具**（extension 注册 + FastAPI 反代已有 /sentiment-board/）
2. **Atuohome 14 工具**（FastAPI 加 /mcp/ 反代 + extension 注册）
3. **补装 6 插件**（pi install）
4. **权限分层**（permission-system 配置 3 角色）
5. **选车助手模式**（SYSTEM.md 多人设 + 工具白名单）
