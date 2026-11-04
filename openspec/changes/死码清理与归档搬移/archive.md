# 死码清理与归档搬移 · 归档

> 2026-10-08 · 轻量 change（explore 实测复核 → design/execute → 验收），十步走完

## 执行结果

### 删（快照留 snapshots/）
- src/tools/guardrail.ts（116 行，零引用确证）
- prism-api/pi_bridge.py（phase2 化石）
- SYSTEM.md.template（孤儿，快照留档）
- 空目录 src/eval src/identity；demoData.ts
- _shared.ts 死导出 ToolResult（readMeta 已被用户的单源化重写先行移除）
- extension：redactSanitize 死 import + 头注释重写（21 工具/7 hook 实况）
- 网关：.tmp-raw-events 诊断落盘、userIdVal 别名、/session/switch + /session/messages 两死端点（~55 行）
- main.py：AUTOHOME_TOOL_MAP 死别名；/trajectory 加"人工消费面，勿删"注释
- 前端：/skills 空转 fetch（留 mock）、_shared.tsx 5 孤儿导出（KpiGrid/DemoCard/AreaChart/BarChart/HBars）、Icons 8 死 symbol（剩 16）
- 垃圾：foo/ __pycache__/ 根 .tmp-*.log ×15、业务数据 -shm/-wal、prism-dashboards 日志残片

### 卸（9 依赖）
@assistant-ui/react @nanostores/react nanostores class-variance-authority lucide-react radix-ui react-router tailwind-merge @tailwindcss/vite tailwindcss（+vite 插件移除——"Tailwind4"口径失实纠正，build 2.05s 证实空转）

### 搬（不删）
- 3 份已归档改造计划 → 对应 change 目录（修 3 处 file:/// 断链为相对路径）
- pi-Agent-能力地图.md、会话备份.md → 文档/；tasks_v1.ts → eval/baseline/；SeriesCombobox.tsx → prism-web/src/components/archive/（修 ../Icons 相对路径）

### 对外部报告的实测修正（重要——防未来重复推导）
1. **logs/ 不是垃圾**：prism.py 启动器活日志目录（五服务占用）——报告误判，保留
2. **字体三件是活依赖**：main.tsx @fontsource css import（报告与首轮脚本都漏）——不卸
3. **typescript 保留**：tsc 构建链在用
4. **promptMessage 非纯别名**：prompt 发送处活引用——只删 userIdVal
5. **C1"6 路径全失效"证伪**：/docs /health 均 200；真问题仅 sentimentCoverage URL 形态 → 归"迁移收尾修复"change
6. guardrail.ts 实测 116 行非 132

## 验收记录
- 根 tsc：11 错全为历史基线（TS5097×10 + datasource 旧类型×1），**零新增** ✅
- web tsc：0 错 ✅；vite build 成功 ✅
- smoke:all 全绿（50/50 含 identity 4）✅
- grep 复扫删除目标零残留 ✅
- prism.py status 五服务运行中 ✅

## 留下一轮（"迁移收尾修复" change 已立项范围）
sentimentCoverage URL / App.tsx 接 onSelectSeries（三看板 series 断链根源）/ KanbanView as_of+刷新 / ChatView 文案 / rename 后端 20 行 / EvidenceDrawer 断链报告
