# 全链路审查完整修复 Implementation Plan（主索引）

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development。本 change 极大（40 项 / 6 Phase / 35 task），按 Phase 分文件组织 plan，本文件为索引。

**Goal:** 修复 v3 全链路审查报告 40 项问题，系统整体收敛。

**Architecture:** 6 Phase 各自 subagent → simplify → code-review 子循环，最后统一 archive。

**Spec:** `openspec/changes/audit-fixes-complete/`
**决策文档:** `docs/审查报告修改决策-2026-10-06.md`
**审查报告:** `C:\Users\<you>\Desktop\TRAE-Review\舆情看板\全链路深度审查报告-2026-10-06.md`（v3，595 行）

## 用户决策

1. §9.4 事件切/并：bug，统一参数
2. 7.3 健康分：时间窗有意保留，其余 3 处 bug 修
3. H2 ABSA：A 方案前端提示
4. 6.3 口径：大改统一构造器 scoped_posts()
5. M5 confidence：本 change 一起做

## Phase 索引

| Phase | 主题 | task 数 | plan 文件 |
|---|---|---|---|
| Phase 1 | 采集层容错 | 4 | `2026-10-06-audit-fixes-phase1-collector.md` |
| Phase 2 | 分析层 | 8 | `2026-10-06-audit-fixes-phase2-analyzer.md` |
| Phase 3 | 收敛层口径统一（大改） | 5 | `2026-10-06-audit-fixes-phase3-scopes.md` |
| Phase 4 | 健康分一致性 | 4 | `2026-10-06-audit-fixes-phase4-health.md` |
| Phase 5 | 静默降级显式化 | 7 | `2026-10-06-audit-fixes-phase5-degradation.md` |
| Phase 6 | 前端 + 运维 | 8 | `2026-10-06-audit-fixes-phase6-frontend-ops.md` |

## 执行顺序

Phase 1 → 2 → 3 → 4 → 5 → 6（Phase 3 是大改，放中间让前面的口径基础先就位）

每 Phase 完成 subagent → simplify → code-review 子循环后 commit，最后统一 archive。

## Self-Review（3.5 自查，主索引层）

- ✅ 6 Phase 覆盖 explore 所有 40 项
- ✅ 用户 5 个决策点已落实到 design/specs/tasks
- ⚠️ 跨 Phase 耦合点（H1+T2.7 / T4.1+T6.4 / T5.5+Phase3）需在子 plan 标注依赖
- ⚠️ Phase 3 大改风险最高，子 plan 需详细拆 task + 口径回归测试

各 Phase 子 plan 需各自做 3.5 自查收敛。
