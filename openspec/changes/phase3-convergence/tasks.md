# Phase3 · Convergence · Tasks

> 2026-10-06
> 按 M1-M7 里程碑组织。前置 [proposal.md](./proposal.md) + [design.md](./design.md) + specs/。

---

## 里程碑

| M | Step | 主题 | 关键路径 |
|---|---|---|---|
| M0 | 0 | 基线留档 | runner 接 scorer 跑 16 题 |
| M1 | 1+2 | 接线+身份注入 | completion.ts 移植 + series_key 通道 + resolve_series |
| M2 | 3+4 | 上下文+护栏 | SYSTEM.md 动态化 + grounding 扩展 + 8 测试集搬移 |
| M3 | 5 | 重启+补漏 | 进程守护 + /ui-response + 鉴权 + 密钥移出 |
| M4 | 6 | 观测层 | langfuse observation + verdict 事件 |
| M5 | 7+8 | 埋点+badcase | /events + 点踩 + trajectories |
| M6 | 9 | 评测门禁 | runner 调 scorer + 单测 + CI |
| M7 | 10 | 收尾 | 删死代码 + 同步 smoke |
| UI | 全量 | 前端 | M1 后并行，M3 前完成 P0 |

**瓶颈**：34 题你写（M6 后接入，不阻塞主线）。

---

## M0 · 基线

- [ ] T-0.1 runner.mjs 临时接 scorer.ts（验证器口径）
- [ ] T-0.2 跑 16 题存 eval/eval-baseline.json
- [ ] T-0.3 npm run smoke:all 留档
- [ ] T-0.4 Langfuse 截图 pi 层 trace

## M1 · 接线+身份注入（Step 1+2）

### Step 1 接线
- [ ] T-1.1 删 extension L397-398 旧注释，定职责划分
- [ ] T-1.2 tool_call 加 fail-closed 未知工具（23 工具白名单）
- [ ] T-1.3 agent_settled 移植 completion.ts（删 decideVerification 287-313 + 正则 257-278，import verifyCompletion）
- [ ] T-1.4 退役 src/tools/query_*.ts（保留到 M7，标"参考实现"）

### Step 2 身份注入
- [ ] T-2.1 前端 composer 带 series_key（ChatView/KanbanView）
- [ ] T-2.2 main.py /chat/stream 透传 series_key
- [ ] T-2.3 pi_gateway series_key + scope 拼进 prompt 前缀
- [ ] T-2.4 before_agent_start 解析前缀填 {series_key} + 读 scope 调 pi.setActiveTools
- [ ] T-2.5 extension 注册 resolve_series 工具 + before_agent_start 强制前置核验（Gap 4）
- [ ] T-2.6 main.py /identity/resolve 端点（移植 resolve.ts 逻辑到 Python）
- [ ] T-2.7 新建 SeriesCombobox 组件

## M2 · 上下文+护栏（Step 3+4）

### Step 3 上下文
- [ ] T-3.1 SYSTEM.md 变量从 prompt 前缀取（删 L387-391 硬编码）
- [ ] T-3.2 闲聊检测（车系名/维度词典 + isAnalysis）
- [ ] T-3.3 SYSTEM.md 加"后台元数据禁止复述"
- [ ] T-3.4 角色分流落 before_agent_start hook

### Step 4 护栏
- [ ] T-4.1 tool_call fail-closed（M1 已做，此处确认）+ 行ID查库
- [ ] T-4.2 tool_result import verifyNames/collectNameTruth
- [ ] T-4.3 越界用 completion.ts verifyScope（M1 移植后生效）
- [ ] T-4.4 8 名称测试集搬到 extension/name-tests.ts

## M3 · 重启+补漏（Step 5）

- [ ] T-5.1 重启 pi_gateway + FastAPI + kill 孤儿 vite
- [ ] T-5.2 /health 增 startedAt + mtime + 进程崩溃自动 respawn
- [ ] T-5.3 main.py /ui-response 转发 + vite 代理 + AUTO_APPROVE 文档化
- [ ] T-5.4 --exclude-tools 补 mcp/记忆/子代理
- [ ] T-5.5 模式分流 scope 拼进 prompt + extension setActiveTools（Gap 3，非网关调）
- [ ] T-5.6 /chat/stream 透传 session_id + session_info 事件
- [ ] T-5.7 可配超时 PRISM_TURN_TIMEOUT
- [ ] T-5.8 MEM0_API_KEY 移出源码（删 L259 兜底）
- [ ] T-5.9 prism_views.db 只读 + 清 0 字节残留
- [ ] T-5.10 鉴权中间件（管理者密码 + 写端点保护）
- [ ] T-5.11 vite 代理 /events

## M4 · 观测层（Step 6）

- [ ] T-6.1 前置验证 extension import langfuse SDK + better-sqlite3（Gap 1，两个第三方包）
- [ ] T-6.2 tool_call observation（Guardrail）
- [ ] T-6.3 tool_result observation（Grounding）
- [ ] T-6.4 agent_settled observation（Verifier）+ verdict 文件 + mapEvent verdict 事件（Gap 2）

## M5 · 埋点+badcase（Step 7+8）

### Step 7 埋点
- [ ] T-7.1 prism-web/lib/tracker.ts（page_view/chat_start/active_tick/feedback）
- [ ] T-7.2 sendBeacon 上报
- [ ] T-7.3 main.py /events + SQLite 事件表
- [ ] T-7.4 ChatView 点踩/采纳按钮
- [ ] T-7.5 脱敏 VIN/车牌正则

### Step 8 badcase
- [ ] T-8.1 extension session_shutdown 落 trajectories.jsonl
- [ ] T-8.2 /trajectory/{session_id} GET 回放端点
- [ ] T-8.3 eval/attribution.ts 五维归因
- [ ] T-8.4 动态评测集（badcase→dynamic-tasks.json）

## M6 · 评测门禁（Step 9）

- [ ] T-9.1 runner.mjs → runner.ts，删正则 scoreTask（41-77），调 scorer.ts（Gap 5）
- [ ] T-9.2 单测：completion.test.ts / grounding.test.ts / resolve.test.ts / tool_call.test.ts
- [ ] T-9.3 CI 骨架（.github/workflows/eval.yml 或 ci.sh）+ 发版门槛 4 条件
- [ ] T-9.4 user-tasks.json 接入位
- [ ] T-9.5 ⬜ 你写 34 题（user-tasks-template.md → user-tasks.json）—— 不阻塞

## M7 · 收尾（Step 10）

- [ ] T-10.1 删 src/tools/query_*.ts + src/identity/resolve.ts
- [ ] T-10.2 保留 scorer.ts（M6 激活）
- [ ] T-10.3 verify/* 视 scorer 依赖定去留（scorer import 它，保留到 v2）
- [ ] T-10.4 同步 package.json smoke 脚本 + smoke:all
- [ ] T-10.5 _shared.ts 去留
- [ ] T-10.6 端到端验收（银河E5 三维度→结论→Langfuse 两层 trace）

## UI Track（M1 后并行）

### P0（M3 前完成）
- [ ] T-UI-1 删顶部死元素 + 侧栏空壳实装/下架
- [ ] T-UI-2 口碑/市场/配置看板接 _meta + 赋分接真链路 + 销量同比 + 演示态水印

### P1（M6 前完成）
- [ ] T-UI-3 SKILLS 库侧栏入口 + GET /skills
- [ ] T-UI-4 会话重命名 + list onClick 切换

### P2（M7 前完成）
- [ ] T-UI-5 hero 大字态 + Logo 卢浮宫金字塔
- [ ] T-UI-6 视图保活 + 产物视图 + 修 args/重复 case/as_of

---

## 全程并行簇

- **提示词层**（M2 Step3）：可与 M1 并行准备 SYSTEM.md/AGENTS.md 文本
- **你写 34 题**（M6 后接入）：从现在就可开始，不阻塞任何主线
- **UI Track**：M1 后并行，P0 优先

## 关键路径图

```
M0 基线 → M1 接线+身份 → M2 上下文+护栏 → M3 重启补漏 → M4 观测 → M5 埋点+badcase → M6 评测 → M7 收尾
                ↓ (M1 后)
              UI Track（P0→P1→P2）
```

## 风险跟踪

- [ ] R1 extension import langfuse SDK（M4 T-6.1 前置验证）
- [ ] R2 completion.ts 移植行为等价（M1 T-1.3 验收）
- [ ] R3 permission-system + fail-closed 叠加冲突（M1 T-1.1 实测）
- [ ] R4 series_key 时序（M1 T-2.4 验收）
- [ ] R5 scorer.ts 激活对接（M6 T-9.1）
