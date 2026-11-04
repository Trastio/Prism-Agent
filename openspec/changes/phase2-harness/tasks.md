# Tasks · 阶段2 核心Harness与语义工具

> 阶段2 · 21 任务（19 + 阶段1 复审新增 2）
> 依赖链见 design.md §7

---

## M1：口径视图 + 对象身份映射（解锁 TS 工具）

| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| T-2.2.1 | 数据源注册表（Atuohome SQLite + 舆情 REST + RAG 预留） | 我 | — | ✅ TS 完成+冒烟通过（中文路径 bug 用 chdir 绕过） |
| T-2.2.2 | 口径视图 v1：mv_sales_monthly / mv_reviews_dim / mv_config_spec + _meta | 我 | T-2.2.1 | ✅ 完成（prism_views.db + refresh.py，E5 序列/口碑/配置全部复现 v0.3） |
| T-2.2.0 | 对象身份映射层 + 覆盖率守卫（resolve_series + 联网核验触发） | 我 | T-2.2.1 | ✅ TS 完成+冒烟通过（4 case 全正确，铂智7X/歧义/不存在均拦截） |

**M1 验收**：物化视图三表可刷新；E5 真实序列复现；"铂智7X"映射到"铂智7"+覆盖率报告。

---

## M2：3 核心语义工具 + 名称 grounding（解锁验证层）

| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| T-2.2.3a | query_sales（含 expected_* + _meta 返回） | 我 | M1 | ✅ 完成+冒烟（E5 序列+版型明细+铂智7X 拦截） |
| T-2.2.3b | query_reviews（含打标覆盖率 _meta） | 我 | M1 | ✅ 完成+冒烟（9 维度+原文样本 review_id 溯源） |
| T-2.2.3c | query_config（展平嵌套 dict + 年款标注） | 我 | M1 | ✅ 完成+冒烟（79311=2027款 550 智充启航版） |
| T-2.2.4 | tool_call 护栏（cc-safety-net + 自建红线拦截 fail-closed） | 我 | — | ✅ 完成（白名单+管理者专属+SQL关键字拦截） |
| T-2.2.5 | tool_result grounding（数值 + 名称维度，8 错误测试集） | 我 | T-2.2.3a/b/c | ✅ 完成+冒烟（8 名称错误 100% 拦截，数值容差通过） |

**M2 验收**：3 工具可调用；名称 grounding 拦截阶段1 复审 8 错误 100%。

---

## M3：完成验证器（解锁评估集）

| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| T-2.3.1 | grounding.py 移植（数值 + 名称，接 tool_result + agent_settled） | 我 | T-2.2.5 | ✅ 完成（T-2.2.5 已实现，pi hook 接入留 M7） |
| T-2.3.2 | 完成验证器（CLAIM/VERIFY 汽车场景化，越界检查） | 我 | T-2.2.3 | ✅ 完成+冒烟（越界/无supported_by/数据缺口全 fail，合法通过） |
| T-2.3.3 | 口碑定性结论单独一套（claim 溯源 + 人工抽检流程） | 我 | T-2.3.2 | ✅ 完成+冒烟（buildKoubeiClaim+sampleForAudit+formatAuditReport） |
| T-2.3.4 | 真值校验（纯 Python 多重集容差比对） | 我 | T-2.3.1 | ✅ 完成+冒烟（E5 销量序列+口碑维度真值校验通过） |

**M3 验收**：报告① v0.2 "市场侧印证" 越界 fail；报告③ v0.2 无 supported_by fail；数据缺口未声明 fail。

---

## M4：评估集 + 批跑（你写问题并行）

| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| T-2.4.1a | 评估集模板框架 + 维度分配 + 6 trap 设计 | 我 | M3 | ✅ 完成（16题：跨维度10基于三份golden + trap6基于复审8错误） |
| T-2.4.1b | **34 评估问题主干**（你写，AI 偷工减料） | **你** | T-2.4.1a | ⬜ 待用户写（销10/配8/口10/舆6） |
| T-2.4.2 | 六分制评分器（销量/配置数值容差） | 我 | T-2.4.1 | ✅ 完成（0-5分+grounding+verify集成） |
| T-2.4.4 | 批跑环境（pi -p --mode json + 快照库 + 成本4维度） | 我 | T-2.4.1 | 🟡 框架完成，pi 联调留 M7 |
| T-2.4.5 | EVAL_STATUS.md 门禁台账 | 我 | T-2.4.4 | ✅ 完成 |

**M4 验收**：16 题就位（待用户 34 题）；6 trap 设计完成；评分器+统计栈可运行。

---

## M5：langfuse 闭环 + 统计栈（三份 golden case 跑通）

| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| T-2.4.3 | 统计栈（McNemar + Wilcoxon + Cliff's delta + bootstrap CI） | 我 | T-2.4.2 | ✅ 完成+冒烟（4脚本可运行，发版门槛4条件可计算） |
| T-2.4.6 | 双评委（GLM/Kimi 异源） | 我 | T-2.4.2 | 🟡 框架定（agent=DeepSeek，评委=GLM+Kimi），接入留评估期 |
| T-2.4.7 | langfuse 闭环（分数+失败维度+成本写回 trace） | 我 | T-2.4.4 | ✅ 完成（langfuse_writer.ts + summarizeRun，pi hook 接入留 M7） |

**M5 验收**：统计栈可运行；langfuse 写回框架就位；三份 golden case 跑通待 M7 pi 集成。

---

## 全程并行簇

| 簇 | 任务 | 负责 | 时机 |
|---|---|---|---|
| 提示词层 | T-2.1.1 AGENTS.md+SYSTEM.md / T-2.1.2 状态栏 hook / T-2.1.3 D3标记+缺口范式 | 我 | M1-M7 全程 |
| 前端 UI 层 | T-2.5.1~2.5.9（9 项，按 frontend-ui.md 设计） | 我 | M1 完成后并行启动 |
| pi 集成层 | T-2.5b.1~2.5b.11（11 项，前端↔FastAPI↔pi SDK） | 我 | M1+M2+M3 完成后启动（部分 M1 后可启动 FastAPI 骨架） |
| 评估问题 | T-2.4.1b 34 题 | 你 | M3 完成后并行 |

---

## M6：前端看板层（M1 完成后并行启动，与 M2-M5 同期推进）

| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| T-2.5.1 | Web 项目骨架（Vite + React 19 + shadcn + Tailwind v4 + assistant-ui） | 我 | — | ✅ 完成（package.json/vite.config/tsconfig/styles.css/main.tsx） |
| T-2.5.2 | 三栏布局 Shell（左 sidebar / 中对话 / 右预览，可拖拽，参考 Hermes） | 我 | T-2.5.1 | ✅ 完成（App.tsx 用 .app/.sidebar/.main className + 侧栏导航切换视图，无顶部模式条） |
| T-2.5.3 | Agent 对话区（assistant-ui 流式 + 工具活动 + 状态栏） | 我 | T-2.5.2, T-2.2.3 | 🟡 框架完成（ChatView.tsx），SSE 联调留 M7 |
| T-2.5.4 | 右侧预览面板：4 看板 tab + 报告预览框架 | 我 | T-2.5.2 | ✅ 完成（KanbanView.tsx board-bar segmented control + composer + statusbar） |
| T-2.5.5 | 口碑看板（读 mv_reviews_dim + 手写 SVG 图表） | 我 | T-2.5.4, T-2.2.2 | ✅ 完成（ReviewsBoard：维度表+hbars+原文样本+AreaChart+其他桶 badge） |
| T-2.5.6 | 市场看板（读 mv_sales_monthly + 手写 SVG 图表） | 我 | T-2.5.4, T-2.2.2 | ✅ 完成（MarketBoard：BarChart+版型 hbars+竞品对比表） |
| T-2.5.7 | 配置看板（读 mv_config_spec + 横排对比表） | 我 | T-2.5.4, T-2.2.2 | ✅ 完成（ConfigBoard：横排 12 spec_id×5 配置项+赋分卡+非车系级缺失 badge） |
| T-2.5.8 | 舆情看板（嵌套舆情 Board 21 GET） | 我 | T-2.5.4 | ✅ 完成（SentimentBoard.tsx iframe 嵌入 127.0.0.1:8000） |
| T-2.5.9 | 报告交付物预览（md/excel/word） | 我 | T-2.5.4 | 🟡 框架占位（AgentMode 右侧），实际渲染留 M7 |

> T-2.5.10/11（API 网关/会话）归 pi-integration.md（M7）

**M6 验收**：四看板组件就位（口碑/市场/配置/舆情），顶部模式切换+底部 composer 就位，brand-spec 视觉落地。

---

## M7：pi-agent 集成层（前端↔FastAPI↔pi SDK 全链路，依赖 M1+M2+M3）

| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| T-2.5b.1 | FastAPI 骨架 + Redis 会话 store | 我 | — | 🟡 FastAPI 骨架完成（main.py + /dashboard + /health 通过），Redis store 留上线前 |
| T-2.5b.2 | pi_bridge.mjs：createAgentSession 封装 + 注册 query_reviews 工具 + AGENTS.md 注入 | 我 | T-2.2.3, T-2.2.4, T-2.3.2 | ✅ 完成+联调通过（SDK创建会话+工具注册+模型调用工具+真实数据回流，E5 9维度返回正确） |
| T-2.5b.3 | SSE /chat/stream 流式（pi 事件 → SSE 映射） | 我 | T-2.5b.2, T-2.5.3 | ✅ 完成（NDJSON 事件流出 message_update/tool_call/tool_result/agent_settled） |
| T-2.5b.4 | scope 锁定（setActiveTools 白名单切换，BI 模式核心） | 我 | T-2.5b.2 | ✅ 完成（resolveScopeTools + setActiveToolsByName） |
| T-2.5b.5 | WebSocket /ws/status 状态推送（三维度完成度/token/as_of） | 我 | T-2.5b.2, T-2.1.2 | 🟡 框架定，待 pi hook 接入 |
| T-2.5b.6 | /dashboard/{type} 看板数据 REST（含 _meta 口径声明） | 我 | T-2.2.2, T-2.5.4 | ✅ 完成（reviews 9行/sales 8行/config 60行 全通） |
| T-2.5b.7 | /session 会话 CRUD + 浏览器本地 ID | 我 | T-2.5b.1 | 🟡 占位，Redis 接入留上线前 |
| T-2.5b.8 | supported_by 溯源 chip 渲染（前端） | 我 | T-2.5b.3 | 🟡 待 SSE 联调 |
| T-2.5b.9 | agent_settled 验证器结果前端显示（通过/continuation/fail） | 我 | T-2.5b.3 | 🟡 待 SSE 联调 |
| T-2.5b.10 | langfuse 埋点 + trace 写回（评估字段） | 我 | T-2.5b.2 | 🟡 框架完成（langfuse_writer.ts），pi hook 接入留联调 |
| T-2.5b.11 | Redis-backed SessionManager wrapper（多实例共享，上线前） | 我 | T-2.5b.1 | ⬜ |

**M7 验收**：`POST /chat/stream` 流式返回文本+工具活动+状态栏；BI 看板提问 scope 锁定（口碑看板只调 query_reviews）；切换实例会话从 Redis 恢复；验证器结果前端可见；supported_by chip 可溯源；langfuse trace 含评估字段。

---

## 提示词层任务（2.1，独立并行）

| ID | 任务 | 负责 | 依赖 | 状态 |
|---|---|---|---|---|
| T-2.1.1 | AGENTS.md（全局 SOP 锁）+ SYSTEM.md（会话快照锁） | 我 | — | ✅ 完成（AGENTS.md + SYSTEM.md.template） |
| T-2.1.2 | 状态栏 hook（SystemState 模式，max_iterations 硬闸门） | 我 | T-2.1.1 | 🟡 框架定（前端状态栏+WS），pi hook 接入留 M7 |
| T-2.1.3 | D3 来源标记 + 数据缺口假设范式 | 我 | T-2.1.1 | ✅ 完成（AGENTS.md <gap_assumption_pattern> + <discipline>） |

---

## 3.5 自查收敛（已完成，2026-10-03）

审查发现 7 个 gap，全部已修：

| # | Gap | 修复 | 落点 |
|---|---|---|---|
| 1 | resolve_series 返回 series_key 但 query_config 要 series_id | IdentityResult 增 series_id 字段 + 反查机制 | tool-interface §2.2.0 |
| 2 | "12+ 错误"实际 8 个名称错误 | 明确 8 条测试集清单 | tool-interface §2.2.5 / design / proposal / explore / verification 全替换 |
| 3 | 歧义时"要求澄清"机制未定 | 明确走 rpiv-ask-user-question 插件 | tool-interface §2.2.0 流程2 |
| 4 | 联网核验触发条件模糊 | 明确：alias 命中但数据表无行 = 覆盖率缺失 → 触发联网 | tool-interface §2.2.0 流程3 |
| 5 | 30-50 题分工不清 | 明确：我转 16 题（跨维度10+trap6），你写 34 题（销/配/口/舆） | evaluation §2.4.1 分工表 |
| 6 | 物化视图刷新机制含糊 | 明确：开发期手动命令 + 上线期轮询 mtime + 兜底 cron | tool-interface §2.2.2 刷新机制 |
| 7 | ctx 字段没写用法 | 明确 ctx.sessionId/userId/callStack 用于 L2/L3 隔离 + 状态栏 | tool-interface §2.2.3 ctx 用法 |

**自查结论**：spec 层无悬空依赖、验收可验、名称测试集明确、对象身份映射边界覆盖。可进 Step 5 subagent-driven-development。

**3.5 自查二轮（前端层加入后，2026-10-04）**：
- 前端层 11 项依赖关系清晰：Shell/对话/预览框架依赖 M1 口径视图，看板依赖 M2 工具联调
- Hermes 参考边界明确（只抄三栏布局 + shadcn 栈 + assistant-ui，砍桌面专属功能）
- 新增风险 3 条（前端后端并行耦合 / 舆情嵌套上云 / Hermes 照搬误区）已进 proposal 风险节
- 自查通过，可进 Step 5

---

## 关键路径

```
后端主线（支柱一→二）:
T-2.2.1 → T-2.2.2 → T-2.2.3 → T-2.2.5 → T-2.3.1 → T-2.3.2 → T-2.4.1a → T-2.4.1b(你) → T-2.4.4 → T-2.4.7
                                                                              ↘ T-2.4.2 → T-2.4.3
前端 UI 并行（M1 后启动）:
T-2.5.1 → T-2.5.2 → T-2.5.4 → T-2.5.5/6/7/8/9(看板并行, 按 frontend-ui.md)
pi 集成（M1+M2+M3 后）:
T-2.5b.1(FastAPI骨架) → T-2.5b.2(pi_bridge,依赖M2工具+M3验证器) → T-2.5b.3(SSE) → T-2.5b.4(scope) → T-2.5b.5(WS) → T-2.5b.6(dashboard REST)
                                                                  ↘ T-2.5b.8/9(前端联动) / T-2.5b.10(langfuse) / T-2.5b.11(Redis SM,上线前)
```

**瓶颈**：T-2.4.1b（你写 34 题）卡关键路径。M3 完成后即可启动。
**集成关键节点**：T-2.5b.2（pi_bridge）依赖 M2 工具 + M3 验证器就绪——这是前端可联调的最早时间点。开发期 FastAPI 骨架（T-2.5b.1）+ 前端 Shell 可更早启动。
