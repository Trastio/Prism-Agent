# 硬编码清理与车系动态化 · Step 2 Proposal

> 2026-10-06
> 前置：[explore.md](./explore.md) + [改造计划 v3](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-硬编码清理与车系动态化-改造计划.md)

---

## WHY

全栈深度审查发现前端硬编码银河E5 + 看板不随车系变。三轮审查打中根因：**幽灵 .js 17 个**被 vite 加载（.js 优先 .tsx），导致 .tsx 改动不生效。同时 CLAIM 卡片/证据 src/默认值仍有真硬编码，车系 tab 是空壳，空 series 绕过 fail-closed。

## WHAT

| 项 | 主题 | 核心动作 |
|---|---|---|
| 防 0 | 主修复 | 删 17 .js + tsconfig noEmit + build 改 tsc --noEmit |
| A | series prop 全链路 | .tsx 已完成，删 .js 后验证 |
| B | CLAIM 动态化 | series_id 从 /identity/resolve 取，supported_by 动态 |
| C | DemoCard | .tsx 已完成，删 .js 后验证 |
| D | 默认空 + 真阻断 | useState('') + setActiveTools([]) |
| E | 去兜底 | ChatView SUGGESTIONS 空时通用文案 |
| F | 车系 tab 实装 | 搜索+最近车系+点击切换+高亮 |

## 决策（已拍板）

1. **D1 默认空 series**（用户必须主动选，符合红线#7）
2. **W2 真阻断**：extension 空系列Key 时 `pi.setActiveTools([])`（非拼提示词，符合红线#5）
3. **W1 不改 main.tsx 扩展名**（tsconfig 无 allowImportingTsExtensions，会 TS5097）
4. **W4 series_id 来源**：从 /identity/resolve 取（非 useQuery，reviews/sales 字段是 model_id）
5. **F 项留本轮**（D1 需要车系选择入口）

## 影响范围

| 文件 | 改动 |
|---|---|
| prism-web/src/**/*.js（17 个） | 删除 |
| prism-web/tsconfig.json | 加 noEmit |
| prism-web/package.json | build 改 tsc --noEmit |
| prism-web/src/App.tsx | useState('') + Sidebar onSelectSeries/series prop |
| prism-web/src/components/KanbanView.tsx | CLAIM 卡 B 动态化 |
| prism-web/src/components/dashboards/ReviewsBoard.tsx | Z1 model_id 动态化 |
| prism-web/src/components/ChatView.tsx | E 去兜底 + D 对话拦截 |
| prism-web/src/components/Sidebar.tsx | F 车系 tab 实装 |
| .pi/extensions/prism-guardrails/index.ts | D setActiveTools([]) 真阻断 |

## 验收

0. 无 .js 幽灵 + 加载 .tsx + tsc 零错
1. 选海豚→4 看板海豚数据
2. 证据 src 正确车系名/model_id
3. 演示卡默认折叠
4. 默认空态/提示选车系
5. 空系列对话拦截 + setActiveTools([])
6. 建议问题空时通用文案
7. 车系 tab 可搜+最近+切换+高亮
8. tsc 零错

## 不做

- mapEvent 事件不全（观测域，留 v2）
- L2 身份注入 prompt 前缀（pi 限制，留 v2）
- 路由/停止生成/复制/重试（体验类，留下一轮）
