# Phase3 · Convergence · Step 1 Explore

> 2026-10-06
> change: phase3-convergence
> 对象：[Prism-Agent-收敛执行总计划 v3.1](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-收敛执行总计划.md)
> 性质：探查代码现状 + 衔接 v3.1 待办清单（不写方案，方案在 Step2 propose）

---

## 1. 探查方法

3 个子代理并行只读探查（2026-10-06）：
- A: extension (`.pi/extensions/prism-guardrails/index.ts`)
- B: gateway + FastAPI (`prism-api/pi_gateway.mjs` + `main.py` + `vite.config.ts`)
- C: verify/eval/src (`src/verify/` + `eval/` + `src/tools/` + `src/identity/`)

---

## 2. 现状清单（证据为文件:行号）

### 2.1 Extension（23 工具，非 3）

- **23 个 registerTool**（index.ts:371 自述）：3 query（56-69）+ 6 sentiment（128-153）+ 14 Atuohome（185-240）
  - query_* execute 调 FastAPI /dashboard/{dtype}
  - sentiment_* execute 调舆情 Board :8000
  - Atuohome 14 工具 execute 调 :8001
- **5+2 hook**：
  - before_agent_start（377-395）：注入 AGENTS.md + SYSTEM.md，**{series_key} 硬编码银河E5**（L387），{series_id}=7650（L388），{as_of}=当天（L390）
  - tool_call（399-413）：3 条拦截（裸SQL/数据库直连/敏感文件），**无 fail-closed 未知工具**（L397-398 注释"不再手写白名单"）
  - tool_result（416-445）：grounding 校验 _meta.as_of + **已有 prism-name-truth 名称真值集收集**（写 appendEntry）
  - agent_settled（448-488）：**内联 regex 验证**（decideVerification 287-313），**不 import completion.ts**，回灌走 appendCustomMessageEntry
  - session_before_compact（491-494）/ session_start（497-499）/ session_shutdown（502-504）：空 no-op
- **import**：只 node:fs/node:path（15-16），无第三方包，无 verify/*，无 query_*

### 2.2 Gateway + FastAPI

**pi_gateway.mjs（:9100）**：
- /chat（300-311）只读 user_id + message，**series_key 全链路丢失**
- /chat 通过 rpc.send('prompt', {message})（334）下发，无 scope/session_id 透传
- /health（293-297）返回 status/model/poolSize，**无崩溃自动重启**（proc.on exit 仅清理，L95-103；惰性重建 L235-267）
- spawn env（253-261）：PI_CODING_AGENT_DIR + **MEM0_API_KEY 硬编码兜底 L259**
- AUTO_APPROVE（L34）：PRISM_AUTO_APPROVE_UI==='1' 开发自动批准，否则转前端
- mapEvent（40-72）：text_delta/thinking_delta/tool_call/tool_result/status_update/settled/error/ui_request，**无 verdict**
- ui_request 上行（142-149）+ /ui-response 下行端点（410-427）**存在**，但 uiRequests Map 无超时清理

**main.py（:8002）**：
- /dashboard/{dtype}（65）、/chat/stream（147）、/session GET+POST（177/185）、/sentiment-board（196）、/autohome/{tool}（237）、/health（264）
- /chat/stream 转发 message/user_id/scope/session_id（158-163），**无 series_key**
- **缺失**：/identity/resolve、/events、/ui-response 转发、鉴权

**vite.config.ts**：
- 代理 /chat/stream、/dashboard、/session、/ws、/sentiment-board、/static、/api/dashboard
- **缺失**：/events、/ui-response 代理

### 2.3 verify/eval/src

**src/verify/ 四文件完整**：
- completion.ts：Claim/VerifyResult 接口（21-34）+ verifyCompletion（152-188）+ 行ID查库（verifySupportedBy 46-67）+ 越界（verifyScope 109-128）+ 缺口（verifyDataGaps 131-144）+ attemptMap max1（150）
- grounding.ts：数值（extractNumbers 38-51 + verifyNumbers 54-79 ±2%）+ 名称（collectNameTruth 86-96 + verifyNames 112-186 + findClosest 243-254）+ groundResult（279-292）
- reference.ts：getSalesTruth（20-30）+ getReviewsTruth（33-47）+ compareMultiset（50-86）
- koubei_claims.ts：KoubeiClaim + buildKoubeiClaim + sampleForAudit + formatAuditReport

**8 名称错误测试集**：grounding.ts:6-11（注释）+ smoke.ts:43-53（可执行 cases）

**verify/* 唯一消费者 = scorer.ts**（scorer.ts:9-11 import 三文件），extension 不 import

**scorer.ts 是死码**：无任何外部 import 者（grep 全仓仅自身定义）

**eval/runner.mjs**：
- 用本地正则 scoreTask（41-77），**不调 scorer.ts**
- 16 题 TASKS 数组（19-38）：cross-01..10 + trap-01..06
- eval-report.json 写死 L182
- 34 题模板 user-tasks-template.md 存在但 **0 题填写**

**src/tools/query_*.ts**：三个文件 import _shared.ts + resolve.ts，仅被 src/tools/smoke.ts 引用，agent runtime 未注册（extension 用 HTTP 版）

**src/identity/resolve.ts**：resolve_series（147-214）完整实现，**4 case 测试集**（smoke.ts:31-34：银河E5/铂智7X/7X歧义/虚构），**非 8 case**

**package.json smoke**：datasource/identity/tools/grounding/m3/guard + smoke:all 串联 6 个

---

## 3. v3.1 计划与现状的对齐修正

| v3.1 计划项 | 现状探查后修正 |
|---|---|
| Step1 "extension 注册 3 工具" | 实际 23 工具（3 query + 6 sentiment + 14 Atuohome）。退役的是 src/tools/query_*.ts，extension 的 23 工具全保留 |
| Step1 "移植 completion.ts 替换内联 regex" | 确认 extension agent_settled 是内联 decideVerification，completion.ts 完整逻辑在 src/verify/，移植可行 |
| Step4 "8 测试集搬到 extension" | 8 测试集在 src/verify/grounding.ts + smoke.ts，搬移时连带 verifyNames/findClosest |
| Step9 "runner 接 scorer.ts" | scorer.ts 是死码但实现完整（已 import verify/*），runner 改调它即可激活，不需重写 |
| Step9 "mapEvent 加 verdict" | mapEvent 40-72 确认无 verdict，agent_settled（60-61）只输出 settled，需扩展 |
| Step5 "/ui-response 转发" | pi_gateway:410 端点已存在，main.py 缺转发 + vite 缺代理，是断链点 |
| Step2 "identity 4 case" | 确认 4 case 非 8 case（8 是 grounding 名称测试） |
| Step6 "import langfuse SDK" | extension 现只 import node 内置，需验证第三方 import |

---

## 4. 待办清单（按 v3.1 Step 组织，进 Step2 propose 展开）

### Step 0 基线
- 0.1 runner 临时接 scorer.ts 跑 16 题留验证器口径基线
- 0.2 smoke:all 跑通留档
- 0.3 Langfuse 截图 pi 层 trace

### Step 1 接线
- 1.1 删 extension L397-398 旧注释，定职责（permission-system 工具级 + guardrail 行为级 + fail-closed）
- 1.2 tool_call 补 fail-closed 未知工具
- 1.3 agent_settled 移植 completion.ts 完整逻辑替换内联 decideVerification
- 1.4 退役 src/tools/query_*.ts（保留 verify/* + _shared.ts 作参考实现）

### Step 2 身份注入+核验
- 2.1 前端 ChatView/KanbanView composer 带 series_key
- 2.2 FastAPI /chat/stream 透传 series_key
- 2.3 pi_gateway series_key 拼进 prompt 前缀
- 2.4 before_agent_start 解析前缀填 {series_key}
- 2.5 extension 注册 resolve_series 工具（调 /identity/resolve）
- 2.6 FastAPI /identity/resolve 端点
- 2.7 新建 SeriesCombobox 组件

### Step 3 上下文注入
- 3.1 SYSTEM.md 变量从 prompt 前缀取（非硬编码）
- 3.2 闲聊检测（不含车系名/维度词→跳过对象块）
- 3.3 后台元数据禁止复述指令
- 3.4 角色分流逻辑落 before_agent_start hook

### Step 4 护栏完整化
- 4.1 tool_call fail-closed 未知工具 + 行ID查库
- 4.2 tool_result grounding 名称维度扩展（接 verifyNames）
- 4.3 越界检查完整化
- 4.4 8 名称测试集搬到 extension 目录

### Step 5 重启+补漏
- 5.1 重启 pi_gateway + FastAPI + 清孤儿 vite
- 5.2 /health 就绪探针 + 进程崩溃自动重启 + 启动时间戳
- 5.3 /ui-response main.py 转发 + vite 代理 + AUTO_APPROVE env 策略
- 5.4 --exclude-tools 补 mcp/记忆/子代理
- 5.5 模式分流 scope + setActiveTools（BI 按看板分 scope）
- 5.6 /chat/stream 透传 session_id + session_info 事件
- 5.7 可配超时 env PRISM_TURN_TIMEOUT
- 5.8 密钥移出源码（MEM0_API_KEY L259）
- 5.9 视图库只读 + 清残留 prism_views.db
- 5.10 鉴权/权限分层（管理者密码弹窗）
- 5.11 vite 代理 /events（Step7 用，先埋）

### Step 6 观测层
- 6.1 前置验证 extension import langfuse SDK
- 6.2 tool_call observation
- 6.3 tool_result observation
- 6.4 agent_settled observation + verdict 事件进 mapEvent

### Step 7 前端埋点+北极星
- 7.1 前端 SDK（page_view/chat_start/active_tick/feedback）
- 7.2 sendBeacon 上报
- 7.3 FastAPI /events + SQLite 事件表
- 7.4 ChatView 点踩/采纳按钮
- 7.5 脱敏 VIN/车牌正则

### Step 8 badcase 轨迹
- 8.1 extension 落 trajectories.jsonl
- 8.2 点踩回放
- 8.3 五维归因
- 8.4 动态评测集

### Step 9 评测门禁
- 9.1 runner 删正则 scoreTask，调 scorer.ts
- 9.2 单测覆盖 4 模块
- 9.3 CI 骨架 + 发版门槛 4 条件
- 9.4 34 题接入位

### Step 10 收尾
- 10.1 删 src/tools/query_*.ts + src/identity/resolve.ts
- 10.2 保留 scorer.ts（非死码，Step9 激活）
- 10.3 verify/* 视 scorer.ts 依赖定去留
- 10.4 同步 package.json smoke 脚本 + smoke:all
- 10.5 _shared.ts 去留

### UI Track（并行）
- UI-1 删死元素+侧栏空壳
- UI-2 图表接真数据+演示态隔离
- UI-3 SKILLS 库
- UI-4 会话重命名+列表切换
- UI-5 hero+Logo
- UI-6 视图保活+产物视图+3 小缺陷

---

## 5. 风险确认

1. extension import langfuse SDK 未验证（Step6.1 前置）
2. completion.ts 移植后与 extension 内联版行为等价性需验证
3. scorer.ts 激活后与 runner 16 题对接
4. series_key 拼进 prompt 与 before_agent_start 解析的时序
5. permission-system + guardrail fail-closed 叠加不冲突

---

## 6. 下一步

进 Step2 propose：把待办清单转成 proposal.md + design.md + specs + tasks.md 四件套。
