# Phase3 · Convergence · Step 2 Proposal

> 2026-10-06
> change: phase3-convergence
> 前置：[explore.md](./explore.md) + [收敛执行总计划 v3.1](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-收敛执行总计划.md)
> 性质：proposal（WHY/WHAT/决策/影响/风险/验收）。详细落法见 [design.md](./design.md)。

---

## WHY（为什么做）

两轮复审（v1/v2/v3 共 25 项修正）+ explore 探查打中**三类系统根因**：

1. **红线机制化没生效**：guardrail/验证器/身份解析三套逻辑躺在 `src/verify/*`，extension 用内联 regex 版不 import 它们。红线#1（数据真实性）现在靠人盯，不是机制保障。
2. **运行态与磁盘不一致 + 链路断点**：series_key 全链路丢失、mapEvent 无 verdict、/ui-response 前端回填断链、{series_key} 硬编码银河E5、/health 无崩溃重启、MEM0_API_KEY 硬编码。
3. **观测层零可观测 + 评估用正则**：Langfuse 只有 pi 通用层 trace，Prism 业务语义全不是 trace 字段；runner 用本地正则 scoreTask，scorer.ts（已实现验证器评分）是死码未激活。

靠人盯守不住红线#1，必须 harness 机制化。

## WHAT（做什么，8 Step + UI Track）

| Step | 主题 | 核心动作 |
|---|---|---|
| 0 | 基线 | runner 接 scorer.ts 跑 16 题留验证器口径基线 |
| 1 | 接线 | 移植 completion.ts 替换内联 regex + fail-closed + 退役 query_*.ts |
| 2 | 身份注入 | series_key 拼进 prompt + resolve_series 工具 + SeriesCombobox |
| 3 | 上下文 | SYSTEM.md 动态化 + 闲聊不注入 + 角色分流落 hook |
| 4 | 护栏 | grounding 名称维度扩展 + 越界完整化 + 8 测试集搬 extension |
| 5 | 重启+补漏 | 进程守护 + /ui-response 转发 + 鉴权 + 密钥移出 + 可配超时 |
| 6 | 观测层 | extension langfuse observation + mapEvent verdict 事件 |
| 7 | 埋点 | 前端 SDK + /events + 点踩采纳 + 北极星可算 |
| 8 | badcase | trajectories.jsonl + 五维归因 + 动态评测集 |
| 9 | 评测门禁 | runner 调 scorer.ts + 单测 + CI 骨架 + 34 题接入位 |
| 10 | 收尾 | 删死代码 + 同步 smoke 脚本 |
| UI | 全量 | P0 删死元素+图表接真数据 / P1 SKILLS+会话重命名 / P2 hero+Logo+视图保活 |

## 决策（已拍板）

1. **V2.1+R3-1 白名单定夺**：permission-system（已运行）独占工具级批准；guardrail 不做白名单，只做行为级拦截 + fail-closed 未知工具。叠加不冲突。
2. **series_key 注入选型**：拼进 prompt 文本前缀（`[ctx: series_key=银河E5]`），before_agent_start 解析。池仍按 userId 分键。
3. **scorer.ts 激活非删**：explore 确认 scorer.ts 已 import verify/* 三文件，runner 改调它即激活，Step10 保留。
4. **rubric 归属**：机制红线（veto）我定，语义质量分（六分制各档）你定。本轮只接机制红线，语义质量留 v2。34 题你写。
5. **4 待拍板项**：事件库独立 / Langfuse 与自建表 session_id 关联不双写 / 心跳 30s / 无交互>5min 不计。
6. **范围**：一个 change 全做（含 UI 全量 P0/P1/P2）；34 题你写、#25 PM 推理工具留 v2。

## 影响范围

| 层 | 改动 |
|---|---|
| extension (`.pi/extensions/prism-guardrails/index.ts`) | agent_settled 移植 completion.ts + tool_call fail-closed + tool_result grounding 扩展 + resolve_series 工具 + langfuse observation + verdict 事件 + 8 测试集搬入 |
| FastAPI (`prism-api/main.py`) | /identity/resolve + /ui-response 转发 + /events + session_id 透传 + series_key 透传 + 鉴权 + /health 增强 |
| pi_gateway (`prism-api/pi_gateway.mjs`) | series_key 拼进 prompt + 密钥移出 + mapEvent verdict + 进程守护 + 可配超时 |
| 前端 (`prism-web/`) | 埋点 SDK + 反馈按钮 + UI 全量 + SeriesCombobox 新建 + vite 代理 |
| `.pi/agent-minimal/settings.json` | 插件装载 + extensions 声明（R3-3 补） |
| TS 旧码 (`src/`) | 退役 query_*.ts + identity/resolve.ts；verify/* 视 scorer 依赖定；保留 scorer.ts |
| 评估 (`eval/`) | runner 调 scorer.ts + verdict 事件 + 单测 + CI 骨架 |
| 文档 | 八项工作设计稿/运行架构/运行流程/项目提纲 同步 |

## 风险

1. extension import langfuse SDK 未验证（Step6.1 前置，失败则改网关侧埋点）
2. completion.ts 移植后与内联 regex 版行为等价性需验证（Step1.3 验收）
3. permission-system + guardrail fail-closed 叠加冲突（Step1.1 实测）
4. series_key 拼进 prompt 与 before_agent_start 解析时序（Step2.4 验收）
5. token：一个 change 跨度大 → 每步归档压缩 + 子代理并行

## 验收（change 整体）

1. 后端红线：8 名称错误 100% 拦截 + 越界 fail + 无 supported_by fail
2. 观测：Langfuse 两层 trace 可见 + 事件流含 verdict
3. 北极星：DAU/周结论数/成本可算
4. badcase：点踩→轨迹回放→五维归因链路通
5. 评测：16 题验证器评分 + 单测覆盖 4 模块 + CI 骨架可触发
6. UI：5 看板真数据 + P0/P1/P2 全量 + 3 小缺陷清零
7. 权限：管理者操作弹密码，普通查询只读
8. 进程守护：/health 就绪探针 + 崩溃重启
9. 文档：四份设计图同步
10. 收尾：死代码清零 + smoke:all 全过

## 不做（本轮边界）

- 34 题内容（你写）
- Rubric 语义质量分 + LLM-as-Judge（评估 v2）
- 40 并发池上限/排队/压测（上线前 gate，本轮只做可配超时）
- metabase / 在线时长看板展示（上线后）
- Annotation Queues（评估 v2）
- §5#25 PM 推理工具+跨会话记忆（v2）
