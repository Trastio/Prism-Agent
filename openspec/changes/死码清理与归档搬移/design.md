# 死码清理与归档搬移 · design（含 proposal/tasks，2026-10-08）

## WHY
五轮 change 快速迭代 + 数据源迁移后，死码/断链/孤儿文件累积：误导 code review（每轮重复推导）、依赖表虚胖（Tailwind 口径失实）、根目录混乱。本 change 一次性清偿，**红线：只删零引用确证项，拒绝项不动**（拒绝项清单见 explore.md §一）。

## WHAT（三段）
1. **删**：10 类死码（explore §二清单）——guardrail.ts/pi_bridge.py/空目录/死导出/死端点/死 symbol/死依赖/垃圾文件
2. **卸**：9 个零引用依赖（含 Tailwind 全家 + vite 插件，纠正"Tailwind4"口径）
3. **搬**：4 份改造计划归 change 目录（修 8 处 file:///）+ 能力地图/会话备份/tasks_v1 → 文档/与 eval/baseline/ + SeriesCombobox → archive/

## 不做
- C 组一致性修复（sentimentCoverage URL / series 入口接线 / as_of 硬编码 / rename 后端）→ **"迁移收尾修复" change 单独走**
- last-verdict.json 收窄 → 单列小 change
- /trajectory /attribution /events/stats → 保留（人工面，加注释）
- typescript 依赖 → 保留（tsc 构建链在用）

## 执行序（tasks）

- [ ] T1 删 src/tools/guardrail.ts + 空目录 src/eval src/identity + pi_bridge.py
- [ ] T2 _shared.ts 删 readMeta/ToolResult（保 openAutohomeForTools）
- [ ] T3 extension 清理：redactSanitize import + 头注释重写（7 hook / 21 工具 / 出口闸）+ :950 语义已顺（随出口闸 M2/M3 改过，复核即可）
- [ ] T4 网关清理：诊断落盘 + userIdVal + /session/switch|messages 两端点
- [ ] T5 main.py：AUTOHOME_TOOL_MAP 死别名；/trajectory 等三端点加"人工消费面"注释
- [ ] T6 前端：/skills 删 fetch 留 mock；demoData.ts；_shared.tsx 5 孤儿导出；Icons 8 死 symbol（连带 CSS 段）
- [ ] T7 卸依赖 9 项 + vite.config 去 tailwindcss 插件 + package.json 三 tailwind 包
- [ ] T8 SYSTEM.md.template 删（内容快照进本 change 目录）
- [ ] T9 垃圾清理：foo/ __pycache__/ logs/ 根 .tmp-*.log / 业务数据 -shm/-wal / prism-api 跑偏 session / prism-dashboards 日志残片
- [ ] T10 搬移：4 改造计划（修 file:///）+ 能力地图/会话备份 → 文档/ + tasks_v1 → eval/baseline/ + SeriesCombobox → archive/
- [ ] T11 验收：tsc 对比基线零新增 + smoke:all 全绿 + grep 复扫零残留 + dev 渲染对比 + prism.py status 五绿

## 验收（可断言）
explore §三 全项 + git 级确认（无 git，以 grep 复扫代替）。

## 风险
| 风险 | 缓解 |
|---|---|
| Tailwind 卸载影响渲染 | styles.css 无 @tailwind 实证；dev 渲染前后对比验收 |
| /session 死端点误删（未来要历史回填） | 按需重建成本低（20 行）；本 change 目录留实现快照 |
| icons/CSS 连带删错 | 只删 symbol 块与明确标注段（.demo-watermark 保留——EmbedBoard 在用） |
