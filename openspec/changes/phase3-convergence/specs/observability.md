# Spec 2.7 · 观测层

> Step 6 Prism 自建观测层 + Step 8 badcase 轨迹。前置 [design.md](./design.md#step-6-观测层)。

## 待办
- 6.1 前置验证 extension import langfuse SDK
- 6.2 tool_call observation
- 6.3 tool_result observation
- 6.4 agent_settled observation + verdict 事件
- 8.1 extension 落 trajectories.jsonl
- 8.2 点踩回放
- 8.3 五维归因
- 8.4 动态评测集

## 设计细节

**6.1 前置验证（Gap 1 修正：含 better-sqlite3）**：
- extension 当前只 import node:fs/path（index.ts:15-16）
- 测试两个第三方包 import：① langfuse SDK（`@langfuse/core` 或 `langfuse`）② better-sqlite3（completion.ts 移植依赖）
- extension 目录无 package.json/tsconfig，需验证 pi 子进程能 resolve 项目 node_modules
- langfuse 失败→方案 B：pi_gateway 网关侧埋点（mapEvent 时写 observation）
- better-sqlite3 失败→completion.ts 移植改方案 B：行ID查库改网关侧（pi_gateway 调 FastAPI 校验端点）

**6.2-6.4 observation 写法**（extension 侧方案）：
- Langfuse 客户端：`const lf = new Langfuse({publicKey, secretKey, baseUrl})`（从 langfuse.json 读）
- hook 内 `lf.trace({id: sessionId, name: 'Prism Turn'})` 取当前 trace
- tool_call：`trace.span({name:'Prism Guardrail', metadata:{tool, blocked, reason}})`
- tool_result：`trace.span({name:'Prism Grounding', metadata:{as_of, coverage, nameMatch}})`
- agent_settled：`trace.span({name:'Prism Verifier', metadata:{verdict, evidence_ids, scope}})`
- 同一 sessionId 下追加，与 pi 插件 trace 共享

**mapEvent verdict（Step6.4，Gap 2 修正：verdict 数据源）**：
- extension agent_settled 当前用 `pi.appendEntry('prism-verified', ...)`（index.ts:467/476），但 RPC 模式 appendEntry 不出事件流
- **改法**：extension agent_settled 时写 verdict 文件 `.pi/sessions/{userId}/{sessionId}.verdict.json`（含 verdict/evidence_ids/scope/reason）
- pi_gateway 收 agent_settled 事件后读该文件，mapEvent 输出 `{type:'verdict', data:{verdict, evidence_ids, scope, reason}}`
- 前端状态栏显示 + EvidenceDrawer 联动
- runner 同样读此文件或 trajectories.jsonl

**8.1 trajectories.jsonl**：
- extension session_shutdown hook（502-504 当前空）落盘
- 路径：`.pi/sessions/{userId}/{sessionId}.jsonl` 已有 pi 自己的，Prism 侧另写 `trajectories/{sessionId}.jsonl`
- 字段：session_id / 完整对话 / tool_call序列 / tool_result / 状态栏快照 / final_conclusion / evidence行ID / as_of
- 每 agent_settled 追加一行（非关闭时写，防崩溃丢）

**8.2 点踩回放**：
- 前端点踩→POST /events {event_type:'feedback', value:'thumbs_down', session_id}
- main.py /events 落库
- 管理者后台（或 /trajectory/{session_id} GET）→ 读 trajectories/{session_id}.jsonl → 回放

**8.3 五维归因**：
- eval/attribution.ts：给定轨迹→五维标注
  - 对象理解（resolve_series 是否正确）
  - 能力选择（调对工具了吗）
  - 工具调用顺序（先 resolve 后 query？）
  - 权限与确认边界（ui_request 处理对吗）
  - 业务结果（结论是否站得住）
- 输出 attribution.json

**8.4 动态评测集**：
- badcase 归因后→自动生成评测题模板（用户消息+预期修正）
- 写入 eval/dynamic-tasks.json
- runner 读 dynamic-tasks 合并 TASKS

## 验收
- localhost:3000 Langfuse 看到 Prism 层 observation（Guardrail/Grounding/Verifier）
- metadata 带 series_key/维度/as_of
- verdict 事件前端可见
- trajectories.jsonl 落盘（agent_settled 后）
- 点踩→/trajectory/{session_id} 回放可用
- 五维归因标注可执行

## 依赖
- Step 1.3 验证器移植（verdict 有内容）
- Step 6.1 import 可行性验证
- Step 7 /events（点踩入库）

## 备注
Langfuse 本地 docker 已跑通（2026-10-05 验证：localhost:3000，6 容器 healthy，trace 入 events_core 表）。pi 插件已埋点，Prism 侧只需追加 observation。
