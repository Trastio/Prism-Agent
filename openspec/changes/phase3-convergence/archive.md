# Phase3 · Convergence · Archive

> 2026-10-06
> change: phase3-convergence
> 状态：**十步流程走完归档**

## 十步流程完成情况

| 步骤 | 状态 | 产物 |
|---|---|---|
| Step1 explore | ✅ | explore.md（3 子代理探查 + 现状清单） |
| Step2 propose | ✅ | proposal.md + design.md + specs×7 + tasks.md |
| Step3.5 自查 | ✅ | self-check.md（7 Gap 全修） |
| Step5 subagent-driven-development | ✅ | M0-M7 施工 + UI Track/单测子代理并行 |
| Step6 simplify | ✅ | 死代码清理 V1/V3/G1/M1/C1 |
| Step7 code-review | ✅ | 1 P0 + 7 P1 + 10 P2 发现 |
| Step8 receiving-code-review | ✅ | review-response.md（全部 P0/P1/P2 已修，无遗留） |
| Step9 verification | ✅ | verification.md（10 验收点全达成或明确留 v2） |
| Step10 archive | ✅ | 本文档 |

## 已完成

**M0-M7 主线 + UI Track 全量 + 单测 4 模块**：

- **红线机制化**：completion.ts 移植（行ID查库+越界+缺口+max1 continuation）+ grounding verifyNames（8 名称错误拦截）+ fail-closed 未知业务工具（24 工具白名单）
- **红线#7 身份核验**：resolve_series 强制前置（before_agent_start fetch /identity/resolve，未命中 fail-closed）+ series_key 全链路
- **观测层**：verdict.json（按 sessionId 分目录）+ mapEvent verdict 事件 + trajectories.jsonl + /attribution 五维归因
- **北极星**：/events + SQLite 事件库 + /events/stats + 前端 tracker（sendBeacon 30s 心跳 + 点踩）
- **评测门禁**：runner 读 trajectories verdict 评分 + CI 骨架 + 单测 4 模块（43 case）+ 动态评测集
- **M3 补漏**：/health 就绪探针 + 进程崩溃 respawn + /ui-response 转发 + 鉴权 + 密钥移出 + 可配超时 + exclude-tools + scope setActiveTools + session_info
- **UI Track 全量**：SeriesCombobox + 5 看板接真数据 + SKILLS 库 + 会话重命名 + hero/Logo + 视图保活 + 产物视图 + 3 小缺陷清零
- **Step7 code-review 修 16 bug**：P0-1/P1-1~7/P2-1~10 全修
- **文档同步**：四份设计图

## 验收 10 条

1. ✅ 后端红线 8 名称拦截 + 越界 fail
2. 🟡 Langfuse 两层 trace（verdict.json 兜底，Prism observation 留 v2）
3. ✅ 北极星可算
4. ✅ badcase 五维归因 + 动态评测集
5. ✅ 16 题验证器评分 + 单测 4 模块（43 case）+ CI
6. ✅ UI 5 看板真数据 + P0/P1/P2 全量 + 3 小缺陷清零
7. ✅ 权限弹密码
8. ✅ 进程守护崩溃重启
9. ✅ 四份设计图同步
10. ✅ 死代码清零 + smoke:all 全过（5 smoke + 43 单测 0 fail）

## 留 v2（明确非阻塞）

- Langfuse Prism 层 observation（方案 B 网关侧）
- 34 题你写（接入位就绪）
- Rubric 语义质量分 + LLM-as-Judge
- 40 并发池上限/排队/压测（上线前 gate）

## 文件清单

新增（11）：
- .pi/extensions/prism-guardrails/tool_call.test.ts
- src/verify/grounding.test.ts
- src/verify/completion.test.ts
- tests/identity_api.test.ts
- prism-web/src/lib/tracker.ts
- prism-web/src/components/SeriesCombobox.tsx
- prism-web/src/components/SkillsPanel.tsx
- prism-web/src/components/PyramidLogo.tsx
- eval/ci.sh
- eval/dynamic-tasks.ts
- openspec/changes/phase3-convergence/*（10 文档）

修改：
- .pi/extensions/prism-guardrails/index.ts（5 hook 完整化 + resolve_series + verdict.json + trajectories）
- prism-api/pi_gateway.mjs（series_key+scope 拼 prompt + mapEvent verdict + /health + 进程 respawn + 密钥移出 + session_info）
- prism-api/main.py（/identity/resolve + /ui-response + /events + /trajectory + /attribution + 鉴权 + LIKE 转义）
- prism-web/src/lib/chat.ts + components/ChatView.tsx + App.tsx + vite.config.ts
- prism-web/src/components/dashboards/*（5 看板接真数据）
- prism-web/src/styles.css（演示态水印 + hero + 视图保活）
- SYSTEM.md（第9条禁复述）
- eval/runner.mjs（读 verdict 评分 + 动态评测集合并）
- src/verify/completion.ts（P2-3 try/finally）
- package.json（smoke 脚本同步 + 4 单测）
- 设计图总览/Prism-Agent-项目提纲.md + 三份 HTML

删除（6）：
- src/tools/query_sales.ts / query_reviews.ts / query_config.ts
- src/identity/resolve.ts / smoke.ts
- src/tools/smoke.ts
