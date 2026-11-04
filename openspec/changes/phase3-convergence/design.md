# Phase3 · Convergence · Step 2 Design

> 2026-10-06
> 架构 + 各 Step 落法。前置 [proposal.md](./proposal.md) + [explore.md](./explore.md)。

---

## 架构总览

```
前端 (prism-web)
  ├─ SeriesCombobox → series_key
  ├─ ChatView/KanbanView composer → POST /chat/stream {message, user_id, series_key, session_id, scope}
  ├─ 埋点 SDK → sendBeacon POST /events
  └─ 点踩/采纳 → POST /events {feedback}
       ↓
FastAPI (main.py :8002)
  ├─ /chat/stream 透传 series_key/session_id/scope → pi_gateway:9100
  ├─ /identity/resolve?series_key= → 读 series_alias + series_summaries（身份解析+覆盖率守卫）
  ├─ /ui-response 转发 → pi_gateway:9100
  ├─ /events + SQLite 事件表（北极星）
  ├─ /dashboard/{dtype} → mv_* 口径视图
  └─ 鉴权中间件（管理者操作弹密码）
       ↓
pi_gateway (pi_gateway.mjs :9100)
  ├─ series_key 拼进 prompt 前缀 [ctx: series_key=xxx]
  ├─ spawn pi --mode rpc -e prism-guardrails/index.ts
  ├─ mapEvent 加 verdict 事件
  ├─ 进程守护（崩溃重启 + /health 启动时间戳）
  └─ 可配超时 PRISM_TURN_TIMEOUT
       ↓
pi RPC 子进程 + extension (prism-guardrails/index.ts)
  ├─ before_agent_start: 解析 prompt 前缀填 {series_key} + 条件注入 SYSTEM.md/AGENTS.md
  ├─ tool_call: 行为级拦截（裸SQL/敏感文件/数据库直连）+ fail-closed 未知工具
  ├─ tool_result: grounding（数值±2% + 名称 verifyNames + as_of 校验）
  ├─ agent_settled: 移植 completion.ts（CLAIM/VERIFY 行ID查库 + 越界 + 缺口 + max1 continuation）+ verdict 事件 + langfuse observation
  ├─ resolve_series 工具（调 /identity/resolve 核验）
  └─ 23 工具（3 query + 6 sentiment + 14 Atuohome）
       ↓
Langfuse (localhost:3000)
  ├─ pi 层 trace（Conversational Turn / LLM Call / Tool）
  └─ Prism 层 observation（Guardrail/Grounding/Verifier + metadata）
```

---

## 各 Step 落法

### Step 0 基线
- runner.mjs 临时 import scorer.ts，跑 16 题，存 `eval/eval-baseline.json`（验证器口径：veto命中率/CLAIM完整率/越界率）
- `npm run smoke:all` 留档
- Langfuse 截图

### Step 1 接线
**1.1 职责定夺**：删 extension L397-398 旧注释"不再手写白名单"，改为"行为级拦截+fail-closed 在此；工具级批准归 permission-system"。

**1.2 tool_call fail-closed**：在现有 3 条拦截后加：未知工具（不在 23 注册工具白名单）默认 `return {block:true, reason:'未知工具', terminate:false}`。注意：这是"已知工具白名单"非"权限白名单"——permission-system 管批准，这个管"工具是否存在"。

**1.3 agent_settled 移植 completion.ts**：
- 删 extension 内联 `decideVerification`（287-313）+ 正则常量（257-278）
- import `verifyCompletion` from `../../src/verify/completion.ts`
- agent_settled 调 verifyCompletion，按返回的 VerifyResult 决定 pass/retry/fail
- 回灌仍走 appendCustomMessageEntry（max1 continuation）
- 验收：报告①越界 fail / 报告③无 supported_by fail / 行ID查库真实

**1.4 退役 query_*.ts**：保留文件到 Step10，但 extension 已用 HTTP 版，smoke:tools 仍可跑（标记"参考实现"）。

### Step 2 身份注入
**2.1-2.4 series_key 通道**：
- 前端 composer 提交时带 series_key（SeriesCombobox 选或自由输入）
- main.py /chat/stream body 增 series_key 字段透传
- pi_gateway /chat 读取 series_key，拼进 prompt：`rpc.send('prompt', {message: `[ctx: series_key=${series_key}]\n${message}`})`
- before_agent_start 解析 prompt 前缀 `[ctx: series_key=xxx]`，填 SYSTEM.md `{series_key}`

**2.5-2.6 resolve_series 工具**：
- extension registerTool resolve_series，execute fetch `${FASTAPI}/identity/resolve?series_key=xxx`
- main.py /identity/resolve：读 series_alias（精确+LIKE）+ series_summaries（series_id）+ sales_trim/owner_reviews/config_snapshots（覆盖率），返回 IdentityResult
- 命中放行 / 未命中 fail-closed / 歧义走 rpiv-ask-user-question

**2.7 SeriesCombobox 新建**：prism-web 组件，接 /identity/resolve 提供车系选择+澄清。

### Step 3 上下文注入
**3.1** SYSTEM.md {series_key}/{series_id}/{as_of} 从 before_agent_start 解析的 prompt 前缀取（非硬编码）。
**3.2** 闲聊检测：lastUserMessageText 不含车系名/维度词→跳过 SYSTEM.md 上下文块（只注 AGENTS.md 全局）。
**3.3** SYSTEM.md 加"后台元数据禁止复述"指令。
**3.4** 角色分流落 before_agent_start hook：分析类问题追加 SOP，闲聊不追加。

### Step 4 护栏完整化
**4.1** tool_call 加 fail-closed（Step1.2 已做）+ 行ID真实性查库（agent_settled 时验）。
**4.2** tool_result grounding 扩展：import verifyNames/collectNameTruth from grounding.ts，替换当前仅 prism-name-truth 收集。
**4.3** 越界检查：用 completion.ts 的 verifyScope（109-128）替换内联正则。
**4.4** 8 名称测试集搬到 `.pi/extensions/prism-guardrails/` 下（grounding 测试 + smoke:guard 引用新位置）。

### Step 5 重启+补漏
**5.1** 重启 pi_gateway + FastAPI + kill 孤儿 vite。
**5.2** /health 增返回启动时间戳 + pi 进程 mtime；proc.on('exit') 自动重新 spawn（非惰性）。
**5.3** main.py /ui-response 转发 + vite 代理 + AUTO_APPROVE env 策略文档化。
**5.4** --exclude-tools 补 mcp/pi-memory/pi-subagents/pi-web-access 等。
**5.5** 模式分流：scope=bi_reviews→setActiveTools(query_reviews)，scope=bi_sales→query_sales，scope=agent→全工具。
**5.6** /chat/stream 透传 session_id + session_info 事件。
**5.7** 可配超时 env PRISM_TURN_TIMEOUT（默认 300s）。
**5.8** MEM0_API_KEY 移到 env，删 L259 硬编码兜底。
**5.9** prism_views.db 只读打开 + 清 0 字节残留。
**5.10** 鉴权：管理者操作（采集触发/写端点）走密码弹窗（env PRISM_MANAGER_PASSWORD），普通查询只读。
**5.11** vite 代理 /events（Step7 用）。

### Step 6 观测层
**6.1 前置验证**：extension import langfuse SDK 跑通；失败→改"网关侧埋点"（pi_gateway 写 langfuse observation）。
**6.2-6.4** extension hook 写 observation：
- tool_call：{工具名, 拦截结果, 原因}
- tool_result：{as_of, 覆盖率, 名称匹配}
- agent_settled：{verdict, evidence_ids, scope}
- 挂同一 trace_id，metadata 带 series_key/维度/as_of
**mapEvent 加 verdict**：agent_settled 时验证器结果透传 `{type:'verdict', data:{verdict, evidence_ids, scope}}`。

### Step 7 前端埋点
**7.1** SDK：page_view/chat_start/active_tick(30s)/feedback。
**7.2** sendBeacon 上报。
**7.3** main.py /events + SQLite 事件表（event_type/local_id/session_id/page/series_key/value/ts）。
**7.4** ChatView agent 消息底部点踩/采纳按钮。
**7.5** 脱敏 VIN(17)/车牌正则。

### Step 8 badcase
**8.1** extension hook 落 `trajectories.jsonl`（session_id/对话/tool_call序列/tool_result/状态栏快照/final_conclusion/evidence行ID/as_of）。
**8.2** 点踩带 session_id → 拉轨迹回放。
**8.3** 五维归因（对象理解/能力选择/工具调用顺序/权限与确认边界/业务结果）。
**8.4** 自动转评测题。

### Step 9 评测门禁
**9.1** runner.mjs 删本地正则 scoreTask（41-77），改调 scorer.ts。
**9.2** 单测：工具口径/护栏拦截/验证器/身份解析 4 模块。
**9.3** CI 骨架：批跑 16 题 + 发版门槛 4 条件（veto零命中 + Wilcoxon显著 + 保留集CI下界>0 + 成本CI上界<预算）。
**9.4** 34 题接入位：user-tasks.json 读入 runner。

### Step 10 收尾
- 删 src/tools/query_*.ts + src/identity/resolve.ts
- **保留 scorer.ts**（Step9 激活）
- verify/* 视 scorer.ts 依赖定（scorer import 它，保留到 v2）
- 同步 package.json smoke 脚本 + smoke:all
- _shared.ts 视 verify/* 定

### UI Track（与主线并行）
- UI-1：删顶部死元素 + 侧栏空壳实装/下架
- UI-2：口碑/市场/配置看板接 _meta + ConfigBoard 赋分接真链路 + 销量同比接 2025 数据 + 演示态水印
- UI-3：SKILLS 库侧栏入口 + GET /skills
- UI-4：会话行内编辑 + rename 接口 + list onClick 切换
- UI-5：hero 大字态（Didone）+ Logo 卢浮宫金字塔
- UI-6：视图保活 + 产物视图 + 修 args 字段/重复 case/as_of 提取

---

## 关键路径

M1（Step1-2 接线+身份）→ M2（Step3-4 上下文+护栏）→ M3（Step5 重启+补漏）→ M4（Step6 观测）→ M5（Step7-8 埋点+badcase）→ M6（Step9 评测）→ M7（Step10 收尾）

UI Track 在 M1 后并行启动，M3 前完成 UI-1/UI-2（P0），M6 前完成 UI-3~6。

瓶颈：34 题你写（M6 后接入，不阻塞主线）。
