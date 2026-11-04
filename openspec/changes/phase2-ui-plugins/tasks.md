# Tasks · UI 重构 + 插件接通

| ID | 任务 | 阶段 | 状态 |
|---|---|---|---|
| A1 | styles.css 全量替换（VS terracotta + 响应式 + 发丝） | A | ✅ 589 行 |
| A2 | 字体自托管（@fontsource inter/noto-sans-sc/bodoni-moda） | A | ✅ |
| A3 | AppShell 四区（应用栏/侧栏/主区/状态栏） | A | ✅ |
| A4 | 看板栏 5 格 + composer 仅对话 + 状态栏发丝 | A | ✅ |
| A5 | Icons sprite（加 atom/sun/layers/arrow-right/flask） | A | ✅ |
| B1 | agent-minimal 装回 7 插件 | B | ✅ permission-system/cc-safety-net/langfuse/web-access/ask-user/usage/subagents |
| B2 | langfuse cloud key 配置 | B | ⬜ 待用户配 key |
| B3 | extension_ui 双向通信 | B | ✅ pi_gateway 转发 ui_request + POST /ui-response 回填 + 前端自动批准 |
| B4 | 删白名单 + 验证器调优（闲聊放行） | B | ✅ 行为级拦截 + isAnalysis 判断 |
| B5 | ChatView thinking_delta 渲染 | B | ✅ 可折叠思考区 |
| C1 | 对象上下文（ObjectChip） | C | ✅ 应用栏 chip（SeriesCombobox 待 C4 接 resolve_series） |
| C2 | 棱镜结论看板 | C | ✅ 链路 + CLAIM + 缺口 |
| C3 | 舆情 iframe + 配置矩阵 + 口碑 + 销量 重设计 | C | ✅ 四看板全用新令牌重写 |
| C4 | 证据链（EvidenceDrawer） | C | ✅ 右抽屉 + supported_by + as_of + 可复算 SQL + 行/卡点击触发 |
| C5 | 清硬编码 | C | ✅ ReviewsBoard KPI 从 _meta/rows 算；MarketBoard 从 rows 算；ConfigBoard 从 specs 算 |
