# 阶段2·前后端对齐与 pi 集成 · Step 1 explore

> Prism-Agent 开发流程十步骤 · Step 1 explore
> 日期：2026-10-04
> 范围：把 phase2-harness 已建的后端/前端/pi_bridge 串成完整可用链路
> 上游：phase2-harness（M1-M7 主体已就位，但 /chat/stream + session + 舆情反代未接通）

---

## 一、现状盘点（已建 vs 未接通）

### 已建且验证通过（✅）
| 模块 | 产出 | 验证 |
|---|---|---|
| 数据源注册表 | `src/registry/datasource.ts` | smoke 通过，Atuohome+舆情 ready |
| 对象身份映射 | `src/identity/resolve.ts` | 4 case 通过（E5/铂智7X/歧义/不存在） |
| 口径视图 | `src/views/refresh.py` + `prism_views.db` | E5 序列/口碑/配置全部复现 v0.3 |
| 3 核心工具 | `src/tools/query_sales/reviews/config.ts` | smoke 通过，返回真实数据 + _meta |
| tool_call 护栏 | `src/tools/guardrail.ts` | 白名单+管理者+SQL关键字拦截 |
| tool_result grounding | `src/verify/grounding.ts` | 8 名称错误 100% 拦截 + 数值容差 |
| 完成验证器 | `src/verify/completion.ts` | 越界/无证据/缺口全 fail |
| 口碑定性结论 | `src/verify/koubei_claims.ts` | claim 溯源 + 抽检 |
| 真值校验 | `src/verify/reference.ts` | 多重集容差比对 |
| 评估集 | `eval/tasks_v1.ts` + `stats.py` | 16 题 + 6 trap + 4 统计脚本 |
| 前端骨架 | `prism-web/` | Vite+React+shadcn+brand-spec+Hermes 组件 CSS |
| 四看板 | `dashboards/*.tsx` | 自绘 SVG 图表，E5 真实数据联调通过 |
| pi_bridge.mjs | `prism-api/pi_bridge.mjs` | 单测通过：SDK 创建会话+工具注册+模型调用工具+真实数据回流 |
| FastAPI 看板接口 | `/dashboard/{reviews,sales,config}` | 三接口全通 |

### 未接通（❌ 本次要做的）
| 缺口 | 现状 | 影响 |
|---|---|---|
| `/chat/stream` 链路 | FastAPI 占位返回；前端 composer 只 preventDefault | **对话不能跑**（核心功能缺失） |
| session 管理 | sidebar 写死 2 条；pi SessionManager 没接 | 会话不能创建/切换/续接 |
| 舆情看板 | iframe 直接嵌 127.0.0.1:8000（跨域+上线不可达） | 开发期勉强，上线失效 |
| 状态栏 | 写死"数据源就绪/三维度☐" | 不反映真实 agent 状态 |
| scope 锁定 | composer 不带 scope | BI 看板对话没锁工具白名单 |
| supported_by 溯源 chip | 前端没渲染 | 结论不可溯源 |
| DeepSeek 显式配置 | pi_bridge 实际跑 claude-opus（SDK 默认） | 与 spec 不符 |

---

## 二、关键决策（2026-10-04 拍板）

| # | 决策点 | 方案 | 准则依据 |
|---|---|---|---|
| 1 | Python↔Node 桥 | **Node 常驻 HTTP 服务（pi_server.mjs）** | pi SDK 是 TS，必须跨语言；常驻避冷启动 |
| 2 | session 多用户 | **pi SessionManager + 每用户独立 sessionDir** | pi 自带 session 全套，不造轮子；sessionDir 参数支持自定义 |
| 3 | 舆情看板 | **iframe + FastAPI 反代**（不自绘） | 舆情 Board 已有完整看板，自绘=重造，违反"不造轮子"；用户接受风格差异 |
| 4 | model | **DeepSeek deepseek-v4-flash 显式配置** | spec 要求；getModel('deepseek','deepseek-v4-flash') |

---

## 三、与 phase2-harness spec 的偏差（需回写）

| spec 原写 | 改成 | 原因 |
|---|---|---|
| pi-integration §2.2 "Python async for event in session.send()" | Node 常驻 HTTP + FastAPI 转发 | pi SDK 是 TS，不能 Python 直调 |
| pi-integration §4 "Redis 会话 store" | pi SessionManager 文件持久化 + 每用户 sessionDir | pi 自带，不造轮子；Redis 留上线期多实例 |
| frontend-ui §2.4 "舆情自绘 ECharts" | iframe + FastAPI 反代 | 不重造舆情 Board 前端 |

---

## 四、本次要做的工作（依赖顺序）

```
1. pi_server.mjs（常驻 HTTP，封装 SDK + session + 工具 + 护栏 + 验证器）
   ↓
2. FastAPI /chat/stream + /session 转发到 pi_server
   ↓
3. 前端 composer EventSource + sidebar /session + 状态栏联动
   ↓
4. FastAPI /sentiment-board/{path} 反代 + 前端 iframe 改用反代
   ↓
5. 清理：删示例 chip + 配置横滚 + DeepSeek 验证
```

---

## 五、pi-agent 能力核实（不造轮子依据）

| 能力 | pi 提供 | 我们做 |
|---|---|---|
| 会话创建/恢复/列表/续接 | `SessionManager.create/open/list/continueRecent` | 只包 HTTP API 层 |
| 会话持久化 | 默认 JSONL 文件 `~/.pi/agent/sessions/` | 用默认，自定义 sessionDir 按用户隔离 |
| 会话分支 | `createBranchedSession` | 不需要 |
| 工具注册 | `customTools` + `defineTool` | 注册 query_sales/reviews/config |
| 工具白名单切换 | `setActiveToolsByName` | scope 锁定用 |
| 事件流 | `session.subscribe(listener)` | NDJSON/ SSE 转 |
| 模型选择 | `getModel('deepseek','deepseek-v4-flash')` | 显式传 |
| 系统提示词 | `DefaultResourceLoader({systemPrompt})` | 注入 AGENTS.md |
| extensions 加载 | `DefaultResourceLoader({noExtensions})` | 开发期禁 permission-system |
| 工具活动推送 | `tool_execution_start/end` 事件 | 转 SSE 给前端 |
| 完成事件 | `agent_settled` 事件 | 接验证器 |
| langfuse 埋点 | `@langfuse/pi-observability-plugin` | 评估期保留（开发期 noExtensions 一起禁了） |

**结论**：pi 满足所有 session/agent-loop 需求，不需要造轮子。我们只做"业务工具 + 验证器 + HTTP 接缝"。

---

## 六、风险

1. **pi_server 常驻进程管理**：开发期手动启动 `node pi_server.mjs`，上线期用 systemd/docker。需 graceful shutdown + 异常重启。
2. **每用户 sessionDir 路径**：`~/.pi/agent/sessions/<encoded-cwd>-<userId>/`，要确认 pi 接受非默认 sessionDir。
3. **SSE 长连接 + Node 常驻**：pi_server 要支持 SSE 流式响应（不能用普通 HTTP），FastAPI 转发时要透传 SSE 不缓冲。
4. **noExtensions 禁了 langfuse**：开发期可接受，评估期要改"只禁 permission-system 保留 langfuse"——需自定义 ResourceLoader。
5. **iframe 反代 cookie/session**：舆情 Board 可能用 cookie 维持会话，反代要透传。

---

## 七、explore 结论

本次工作是 phase2-harness 的收尾接通，不是新阶段。pi-agent 满足所有基础设施需求，我们只做业务工具 + 验证器 + HTTP/iframe 接缝。5 步依赖顺序清晰，关键风险是 pi_server 常驻 + SSE 透传。

**下一步 Step 2 propose**：写 proposal.md + design.md + tasks.md（聚焦本次 5 步），回写 phase2-harness spec 的 3 处偏差。
