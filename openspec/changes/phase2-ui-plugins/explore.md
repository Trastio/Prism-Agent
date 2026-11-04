# 阶段2·UI 重构 + 插件接通 · Step 1 explore

> 2026-10-04
> 范围：UI 重构（方案 P0-P5）+ 7 插件接通 + 删白名单 + 双向通信 + 验证器调优 + thinking 渲染
> 上游：UI重构方案.md（已定稿 10 决策）+ 全面审查清单（33 问题）+ pi-Agent 能力地图

---

## 一、三阶段施工

### 阶段 A：P0+P1 设计底座 + 外壳重建
- styles.css 全量替换（VS 暖纸 terracotta 令牌 + @media 响应式 + 发丝阴影）
- 字体自托管（Bodoni Moda + Inter + Noto Sans SC 本地 @font-face）
- AppShell 四区（应用栏/侧栏/主区/右抽屉）
- 看板栏 5 格（棱镜结论 + 舆情‖配置·口碑·销量）
- composer 仅对话视图
- 状态栏发丝化
- Icons sprite 预注入

### 阶段 B：插件接通 + agent 修复
- 精简 agentDir 装回 7 插件（禁 pi-memory/mem0）
- langfuse cloud key 配置
- extension_ui_request 双向通信（pi_gateway 转发前端→弹框→回填）
- 删 prism-guardrails 白名单（用 pi-permission-system 替代）
- 验证器调优（只对分析类结论触发）
- ChatView 加 thinking_delta 渲染

### 阶段 C：P2-P5 看板重设计 + 数据接入
- 对象上下文（ObjectChip + SeriesCombobox + resolve_series）
- 四看板差异化版面（棱镜结论/舆情 iframe/配置矩阵/口碑/销量）
- 证据链（EvidenceDrawer + 选中即问 AskPopover）
- 清硬编码（KPI/状态栏/as_of 全接接口）
- 状态四态（骨架/错误/缺口/满）

---

## 二、关键技术难点

### extension_ui 双向通信（阶段 B 核心）
当前：pi→前端单向 NDJSON 流
需要：pi 弹 extension_ui_request → 前端弹框 → 用户选 → 回填 extension_ui_response

方案：
- pi_gateway 收到 extension_ui_request 时，在 NDJSON 流里插入 `{type:'ui_request', data:{id, method, title, options}}`
- 前端收到 ui_request → 弹 confirm/select 对话框
- 前端 POST `/ui-response` → pi_gateway 收到 → 写入 pi stdin `{type:'extension_ui_response', id, value}`
- pi_gateway 的 /chat 循环里等 ui_response（用 Promise + Map<id, resolve>）

### 字体自托管（阶段 A）
- 用 @fontsource npm 包（`@fontsource/inter` + `@fontsource/noto-sans-sc`）
- Bodoni Moda 手动下载（Google Fonts 下载 woff2，放 src/assets/fonts/）
- index.html 删 Google Fonts link，改 @font-face 本地引用

---

## 三、依赖链

```
A1 styles.css 令牌 → A2 字体 → A3 AppShell → A4 看板栏/composer/状态栏
B1 agentDir 装插件 → B2 langfuse key → B3 双向通信 → B4 删白名单 → B5 验证器调优 → B6 thinking 渲染
C1 对象上下文 → C2 四看板 → C3 证据链 → C4 清硬编码
```

A 和 B 可部分并行（A 改前端，B 改后端）。C 依赖 A+B 完成。
