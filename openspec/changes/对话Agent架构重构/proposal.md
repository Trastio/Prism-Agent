# 对话 Agent 架构重构 · Step 2 Proposal + Tasks + Self-check

## WHY
Prism 是对话 agent，棱镜理论是支撑点。当前 Harness 把棱镜当默认身份每轮注入 + 没有会话实体 + UI 以车系为核心 → 闲聊被汽车 SOP 污染 + 跨话题串 + 历史空白。

## WHAT（15 项，5 层）
- 层0 会话隔离（switch_session/get_messages/历史加载/白名单）
- 层1 提示词分层（通用层 + 数据能力子层 + 分析框架子层）+ 删 memory.json
- 层2 验证层通用放行（host 白名单降为标记，真值集保留）
- 层3 series_key 轮次级（前端不传，agent 自己识别）
- 层5 前端删车系核心元素

## 决策
- 棱镜拆两层（数据能力 vs 分析框架）
- memory.json 彻底删除（branch 承担同会话延续）
- 工具不收窄（全开 + 描述引导）
- host 白名单降为标记（真值集保留）
- series_key 不再前端传（agent 自己识别/调 resolve_series）

## Self-check
- Gap1: get_messages 返回结构未实测 → 施工时抓一次真实返回
- Gap2: ctx.json per-session 路径 → 用 sessionDir 而非 userId
- Gap3: 关键词检测 best-effort → 验证层 tier 路由兜底
- 无悬空依赖，可施工
