# Proposal · UI 重构 + 插件接通

> 2026-10-04 · 三阶段：A(底座+外壳) / B(插件+agent修复) / C(看板重设计+数据)

---

## WHAT

### A. P0+P1 设计底座 + 外壳
- styles.css 全量替换（VS terracotta 令牌 + 响应式 + 发丝）
- 字体自托管（@fontsource + Bodoni Moda 本地）
- AppShell 四区 + 看板栏 5 格 + composer 仅对话 + 状态栏发丝

### B. 插件接通 + agent 修复
- 7 插件装回（permission-system/cc-safety-net/langfuse/web-access/ask-user/usage/subagents）
- langfuse cloud key
- extension_ui 双向通信
- 删白名单（用 permission-system）
- 验证器调优（闲聊不触发）
- thinking_delta 渲染

### C. P2-P5 看板 + 数据
- 对象上下文 + 四看板重设计 + 证据链 + 清硬编码

---

## 验收
A: 暖纸配色 + 响应式 + 外壳对齐 hermes + 看板 5 格 + composer 仅对话
B: 7 插件加载 + langfuse trace 可见 + permission-system 弹框生效 + 闲聊不卡 + thinking 可见
C: 对象切换 + 四看板差异化 + 数字可下钻 + 零硬编码
