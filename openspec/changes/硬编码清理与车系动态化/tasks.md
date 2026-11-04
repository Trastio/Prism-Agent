# 硬编码清理与车系动态化 · Tasks

> 2026-10-06
> 前置 [proposal.md](./proposal.md) + [design.md](./design.md)

---

## 任务清单

### 防 0（主修复）
- [ ] T-0.1 删 prism-web/src/**/*.js（17 个）
- [ ] T-0.2 tsconfig.json 加 noEmit
- [ ] T-0.3 package.json build 改 tsc --noEmit && vite build
- [ ] T-0.4 验证浏览器加载 .tsx + 实测验收 1/3

### B（CLAIM 动态化）
- [ ] T-B.1 OverviewBoard 加 useQuery /identity/resolve 取 series_id
- [ ] T-B.2 KanbanView.tsx:118/123/127/129 CLAIM 卡 series/series_id/supported_by 动态化
- [ ] T-B.3 series 空 → CLAIM 卡空态

### Z1（ReviewsBoard model_id）
- [ ] T-Z1.1 ReviewsBoard.tsx:71 model_id 从 useQuery 结果取

### D（默认空 + 真阻断）
- [ ] T-D.1 App.tsx:24 useState('')
- [ ] T-D.2 四 Board useQuery enabled: !!series
- [ ] T-D.3 ChatView handleSend series 空禁用发送
- [ ] T-D.4 extension before_agent_start 空系列Key setActiveTools([])

### E（去兜底）
- [ ] T-E.1 ChatView.tsx:176 去兜底 '银河E5' + 空时通用文案

### F（车系 tab 实装）
- [ ] T-F.1 Sidebar 加 onSelectSeries/series prop
- [ ] T-F.2 车系 tab 搜索接 /identity/resolve
- [ ] T-F.3 最近车系 localStorage
- [ ] T-F.4 选中车系高亮
- [ ] T-F.5 App.tsx 传 onSelectSeries/series 给 Sidebar

---

## 验收

0. 无 .js + 加载 .tsx + tsc 零错
1. 选海豚→4 看板海豚
2. 证据 src 正确
3. 演示卡折叠
4. 默认空态
5. 空系列对话拦截 + setActiveTools([])
6. 建议空时通用
7. 车系 tab 可用
8. tsc 零错
