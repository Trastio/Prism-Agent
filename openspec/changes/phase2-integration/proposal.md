# Proposal · 前后端对齐与 pi 集成

> Prism-Agent 开发流程 · Step 2 propose
> 日期：2026-10-04
> 范围：把 phase2-harness 已建模块串成完整可用链路（5 步）
> 上游：`explore.md`（已确认 pi 满足基础设施，不造轮子）

---

## 一、为什么做（WHY）

phase2-harness 建了后端工具层、验证层、评估层、前端骨架、pi_bridge 单测——但**链路没接通**：
- 前端 composer 点了没反应（/chat/stream 占位）
- session 写死（pi SessionManager 没接）
- 舆情 iframe 跨域（上线失效）

价值验证不了：agent 能不能在前端真实跑出 E5 报告，目前没法演示。

---

## 二、做什么（WHAT）

5 步，依赖顺序：

| 步 | 内容 | 产出 |
|---|---|---|
| 1 | **pi_server.mjs** 常驻 HTTP 服务 | 封装 createAgentSession + 工具注册 + SessionManager + 事件流 |
| 2 | **FastAPI /chat/stream + /session** 转发 | Python 反代 Node pi_server（SSE 透传） |
| 3 | **前端 composer EventSource + sidebar /session** | 对话流式渲染 + 会话列表 + 状态栏联动 |
| 4 | **FastAPI /sentiment-board/{path} 反代 + iframe** | 舆情看板同源嵌入 |
| 5 | 清理：删示例 chip + 配置横滚 + DeepSeek 验证 | 收尾 |

---

## 三、关键决策（已拍板）

| # | 决策 | 准则依据 |
|---|---|---|
| 1 | Node 常驻 HTTP（pi_server.mjs） | pi SDK 是 TS，必须跨语言；常驻避冷启动 |
| 2 | pi SessionManager + 每用户 sessionDir | pi 自带 session 全套，不造轮子 |
| 3 | 舆情 iframe + FastAPI 反代 | 舆情 Board 已有看板，自绘=重造 |
| 4 | DeepSeek deepseek-v4-flash 显式 | spec 要求 |

---

## 四、影响范围

**新建**：
- `prism-api/pi_server.mjs`（Node 常驻服务）
- `openspec/changes/phase2-integration/`（本 change）

**改动**：
- `prism-api/main.py`：/chat/stream + /session + /sentiment-board 反代
- `prism-web/src/components/KanbanView.tsx`：composer 接 EventSource + 删示例 chip
- `prism-web/src/components/ChatView.tsx`：composer 接 EventSource
- `prism-web/src/components/Sidebar.tsx`：会话列表接 /session
- `prism-web/src/components/dashboards/SentimentBoard.tsx`：iframe 改 /sentiment-board/
- `prism-web/src/components/dashboards/ConfigBoard.tsx`：横滚

**不动**：
- phase2-harness 已建的后端工具/验证/评估代码
- pi-agent SDK 源码（只用，不改）
- 舆情 Board / Atuohome 源项目

---

## 五、验收

1. **对话跑通**：前端输入"用 query_reviews 查银河E5舒适维度" → 流式响应 + 工具活动面板显示调用 + 真实数据回流
2. **session 可用**：sidebar 显示真实会话列表，新建会话/切换会话生效
3. **舆情看板同源**：iframe 走 /sentiment-board/ 无跨域，开发期可见
4. **DeepSeek**：pi_server 日志显示 model=deepseek-v4-flash
5. **状态栏联动**：对话时三维度完成度/as_of 随工具调用更新

---

## 六、不做（边界）

- 不做 Redis 会话（pi 文件持久化够，上线期再考虑）
- 不做 langfuse 接入（noExtensions 一起禁，评估期再改自定义 loader）
- 不做 supported_by 溯源 chip 渲染（下一轮）
- 不做 scope 锁定的前端切换逻辑（先固定 agent 模式，BI scope 留下一轮）
- 不改 phase2-harness 已建代码（只接缝）
