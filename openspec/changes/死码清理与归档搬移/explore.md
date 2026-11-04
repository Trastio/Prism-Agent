# 死码清理与归档搬移 · Step1 explore

> 2026-10-08 · 对外部调研报告逐项实测复核后的执行清单（未验项全部补齐第一手证据）
> 原则：**删除目标必须零引用确证**；搬运不删；拒绝项不动。

## 一、实测复核结果（vs 外部报告）

### A 组修正
| 项 | 报告 | 实测 | 裁决 |
|---|---|---|---|
| guardrail.ts | 132 行 | **116 行** | 删（零 importer 确证） |
| 网关:409-418 别名 | 3 个无操作 | `promptMessage` 在 prompt 发送处**仍被引用**——只 `userIdVal` 是纯别名；另 :413 `const userIdVal = userId` | 删 userIdVal，保留 promptMessage（或 inline 后删两者，施工时对照） |
| Icons 死 symbol | 8 个 | **8 个确证**（box/clock/flask/mic/pin/settings/sliders/sun；24-16=8） | 删 |
| prism-web 零 import 依赖 | 10 个 | **9 个**（字体三件是活的——main.tsx 有 @fontsource css import，报告与我的首轮脚本都漏了）：assistant-ui/@nanostores/nanostores/cva/lucide/radix-ui/react-router/tailwind-merge/typescript¹ | 卸 8 个 + typescript 视构建方式² |
| C1 datasource | "6 条路径全失效" | **证伪**：/docs 与 /health 均 200；真问题仅 `sentimentCoverage` 用老路径形态 `/dashboard/overview?vehicle_name=`（应为 `/api/dashboard/overview/{vehicle_id}`） | 修 1 处 URL（归迁移收尾修复 change，不在本清理 change） |

¹typescript 虽"零 import"但 tsconfig/vite 构建链在用（tsc --noEmit），**保留**——报告这条不采纳。
²最终死依赖 8 个：`@assistant-ui/react @nanostores/react nanostores class-variance-authority lucide-react radix-ui react-router tailwind-merge`（+ 可选 tailwindcss/@tailwindcss/vite 见下）。

**Tailwind 特殊裁决**：styles.css 纯手写零 @tailwind、src 零引用，但 vite.config 挂着 `@tailwindcss/vite` 插件 + package.json 三个 tailwind 包。**本 change 卸载**（vite 插件 + tailwindcss + tailwind-merge），"Tailwind4"口径失实随之纠正。风险：`@tailwindcss/vite` 若参与 className 扫描生成——实测 styles.css 不含 @import "tailwindcss"，插件空转，卸载无渲染影响。收尾跑 dev server 渲染对比确认。

### B 组四拍板（已与用户确认方向：B1 删 / B4 删）
| 项 | 实测 | 裁决 |
|---|---|---|
| 网关 /session/switch + /messages（~55 行） | 前端 lib/tsx 零调用确证 | **删**（历史回填真要做时按需重建 20 行） |
| /session/rename | 前端在调（Sidebar.tsx:51）、后端 404 | **补 20 行后端**（归迁移收尾修复 change——RPC set_session_name 现成） |
| /skills fetch | SkillsPanel 先 fetch 失败落 mock | **删 fetch 留 mock** |
| SYSTEM.md.template | 零引用确证、与 SYSTEM.md 分叉 | **删**（历史归 change 目录） |
| /trajectory /attribution /events/stats | **零代码消费者确证**（tracker 只调 POST /events；trajectory/attribution 全仓无 fetch） | **保留**（badcase 人工查看面 + 北极星口径）——加"人工消费"注释 |

### C 组裁决（全部归"迁移收尾修复" change，不混入本清理）
- C1 sentimentCoverage URL 形态（1 处）
- C2 App.tsx 接 onSelectSeries（断链根源）
- C3 KanbanView as_of 硬编码 + 刷新无 onClick + ChatView 文案
- EvidenceDrawer：报断链不接线（EmbedBoard iframe 化后接线方式未定）

### D 组实测
- 8 处 file:/// 断链：两份改造计划里 2+1 处确证（另 5 处在另三份，搬运时全修）
- `eval/tasks_v1.ts` 在（runner.mjs 不再 import 它——内联了）→ 搬 eval/baseline/
- `prism-api/会话备份.md`（1.6MB）→ 搬 文档/
- `pi-Agent-能力地图.md` → 搬 文档/
- 根目录 4 份已归档 change 的改造计划 → 搬各自 change 目录或 文档/
- `prism-web/src/components/SeriesCombobox.tsx`：**零引用确证**（grep 只命中自身）→ 搬 prism-web/src/components/archive/（不删，C2 接线时可能复活）
- `Prism-Agent-收敛执行总计划.md`：保留根目录（活线程）

### 拒绝项复核确认（全部不动）
/dashboard/{dtype}（query_* 活数据链）｜scorer.ts/stats.py/langfuse_writer.ts（V4.2/发版门槛/M7 条款）｜agent_settled 保底｜verdict 双写（mapEvent 活兜底）｜manager_auth（红线#3）｜redaction 三份（跨语言 spec）｜mv_* 六表｜prism-sentiment/models｜agent-minimal 四插件｜/events POST（tracker 活链）

## 二、执行清单（本 change 范围）

### 删（零引用确证）
1. `src/tools/guardrail.ts`（116 行）
2. `prism-api/pi_bridge.py`
3. 空目录 `src/eval/` `src/identity/`
4. `_shared.ts` 死导出 readMeta + ToolResult（openAutohomeForTools 保留——completion.ts 活引用）
5. extension：redactSanitize import（:21）、头注释重写（7 hook/21 工具实况）
6. 网关：.tmp-raw-events 诊断落盘（:120-121）、userIdVal 别名、AUTOHOME_TOOL_MAP 死别名（main.py:658-659）
7. 网关：/session/switch + /session/messages 两端点（~55 行）
8. 前端：/skills fetch（留 mock）、demoData.ts、_shared.tsx 5 孤儿导出（KpiGrid/AreaChart/BarChart/HBars/DemoCard）、Icons 8 死 symbol
9. `SYSTEM.md.template`（历史内容先并入 change 归档）
10. 垃圾：foo/、__pycache__/、logs/、根 .tmp-*.log ×14、业务数据 autohome_copy.db-shm/-wal、prism-api 跑偏 session 文件、prism-dashboards 日志残片

### 卸（依赖）
`@assistant-ui/react @nanostores/react nanostores class-variance-authority lucide-react radix-ui react-router tailwind-merge @tailwindcss/vite tailwindcss`（9 项）

### 搬（不删）
- 根目录 4 份改造计划 → openspec 对应 change 目录（修 file:/// 链接）
- pi-Agent-能力地图.md → 文档/；会话备份.md → 文档/；tasks_v1.ts → eval/baseline/
- SeriesCombobox.tsx → prism-web/src/components/archive/

### 不动（红线）
verdict 双写、last-verdict.json（单列小 change 收窄）、/trajectory 等人工面、guardrail 死码所在的 src/tools/ 其余活文件（_shared.ts 保留 openAutohomeForTools）

## 三、验收
- `tsc --noEmit` 零错（基线：历史 TS5097 类遗留已存在，对比无新增）
- `smoke:all` 全绿
- 前端 dev server 渲染对比（Tailwind 卸载前后截图级一致性）
- grep 复扫：全部删除目标零残留引用
- prism.py status 五服务仍绿

## 四、Step2 前置问题
- 归档目录命名：`openspec/changes/<change>/` 内放原文件 vs `文档/归档/`——建议 change 目录（历史就近原则）
