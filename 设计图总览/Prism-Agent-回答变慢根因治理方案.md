# Prism-Agent · 回答变慢根因治理方案

> 2026-10-07（v2 修订）
> 修订说明：① 修正 P0-2 引用的代码路径（原文指向并不存在的分支）；② 量化验收 #4 / #7（原为占位符）；③ 两项待决策定案——插件裁剪「直接改 agent-minimal」、ctx.json「统一到 pi sessionId」。
> 起因：前端 http://localhost:5173 反馈"agent 回答变慢/收不到回复"，要求定位并出治理方案。
> 性质：**根因治理方案**（审阅通过后施工；本文只给方案，不含已落地的代码改动）
> 证据来源：实测链路计时（Node/urllib/httpx）+ 进程与端口实测 + `.pi/sessions/trajectories.jsonl` + `pi-permission-system` 日志 + pi 官方 docs（`node_modules/@earendil-works/pi-coding-agent/docs/json.md`）
> 前置结论：**当前不是"慢"，是断链**——`8002/chat/stream` 返回 `200 + 0 字节`。

---

## 一、根因清单（按实际影响排序）

| # | 根因 | 实测证据 | 性质 | 影响 |
|---|---|---|---|---|
| R1 | **8002 反代被本机系统代理劫持** | Node/urllib 直连 `9200/chat` = 200/28530B；而 Node → `8002/chat/stream` = **200/0B**；`8002/autohome/*` = **502**；httpx 加 `trust_env=False` 或 `NO_PROXY=127.0.0.1` → 200 | 断链 | 前端收不到回复（当前主因） |
| R2 | **验证器对 mixed tier 强求库行 ID → 回灌重试** | trajectories：06:39–06:44 连续 4 次 `fail`（同因"缺少 supported_by 行 ID; 市场侧与产品力互为归因"），工具累积 9→30，单轮被拉到数十秒 | 设计 | 单轮耗时 ×2 以上 |
| R3 | **串行 agentic 循环 × 工具数** | 同模型：问候热态 TTFT 1.2s / 整轮 5.7s；"银河E5什么时候上市的" 7 次工具调用 = 17.1s（≈8 次串行推理） | 结构 | 26s 的主要增量 |
| R4 | **上游取数接口慢 + 超大 payload** | `8001/dashboard/market/api/series-list` 两次采样均 **10.8s / 160KB**；`koubei` 1.1s/29KB | 上游 | 单次工具即 +11s，且大 JSON 拖慢后续每次推理 |
| R5 | **冷启动 28s（12 插件 + 23 工具注册）** | Node → 9200 首次 = 28.0s，同一用户第二次 = 5.7s；`PI_CODING_AGENT_DIR=.pi/agent-minimal` 挂 12 个包 | 结构 | 新用户/新会话首次必慢 |
| R6 | **上下文只增不减 + 压缩阈值保守** | compaction `keepRecentTokens=30000/reserveTokens=16384`；trajectories 会话从 2 条累到 42 条；重试把失败回复也留在 branch | 结构 | 越聊越慢 |
| R7 | **`entry_appended` 未映射 → 每轮刷 `console.error`** | pi docs 明确 `pi.appendEntry()` 发 `entry_appended`；网关 `mapEvent` 无此 case → 落 `default` | 卫生 | 日志噪音（非延迟主因） |
| R8 | **`ctx.json` 读写路径规则不一致 + 首写竞态** | `sessions/default/` 只有 `default.ctx.json`，而会话文件是 `<时间戳>_<uuid>.jsonl`；`sessions/diag_w1/` 无任何 ctx.json | 正确性 | series_key/scope 每轮走默认 |
| — | ~~内存压力~~ | RAM 31.6GB / 空闲 6.4GB；4 个 pi.exe = 348+322+324+322MB ≈ 1.3GB（占 4%） | **排除** | 不成立 |

---

## 二、治理方案

### P0-1 · 修复反代被代理劫持（R1）

**目标**：让 `prism-api`（8002）对 localhost 的后端调用不再走系统代理。

`prism-api/main.py` 中所有后端调用都用 `httpx.AsyncClient(...)` 默认参数（`trust_env=True`），会采用本机系统代理 `http://127.0.0.1:7892`，导致对 127.0.0.1 的请求被代理返回 502，`/chat/stream` 因此拿到空响应。

**修法（建议 a+b 组合，a 先恢复链路，b 根治）**：

- **a) 运维零代码（立即见效）**：启动 `prism-api` 前注入 `NO_PROXY=127.0.0.1,localhost`（并**重启 8002 进程**）。
- **b) 代码根治**：新增一个 `httpx_client()` 工厂，显式 `trust_env=False`，替换下列调用点：
  - `main.py` `/chat/stream`（L324）、`/session` 列表（L348）、`/session` 创建（L356）、`/sentiment-board`（L372）、`/ui-response`（L393）、`/autohome/{tool}`（L559）。
- **c) 可观测**：`/chat/stream` 在 `httpx` 返回非 2xx 时**显式报错**（现在 4xx/5xx 不抛异常 → 静默空响应，是最坑的一点）。

**验收**：`8002/chat/stream` 返回非 0 字节；`8002/autohome/get_trims?series_id=6298` 返回 200；前端能出现回复。

---

### P0-2 · 收敛验证器回灌（R2）

**目标**：混合来源的"库外事实"不再被判成必然失败。

现状：tier=`mixed`（本轮同时调了库工具与 web 工具）时，`verifyCompletion` 对整篇结论要求 `supported_by` 库行 ID；而"上市时间/新闻"这类库外事实永远给不出库行 ID → 必然 fail → 回灌让 agent 整轮重做 → 再 fail。

**修法**：

- **a) 语义修正（mixed 分支需「新增」放行条件，不是复用既有路径）**：现状——混合来源里的"库外事实"（上市时间/新闻）给不出库行 ID → `supported_by` 为空 → `verifyCompletion` 直接判 fail（`src/verify/completion.ts` L173）→ `libResult.pass=false` → 落入"lib fail → 回灌"分支（`index.ts` L911-920），整轮重做。
  **注意（原方案此处写错）**：现有 `web_downgrade` 仅在 `libResult.pass && !webResult.pass`（库通过、web 失败）时触发（`index.ts` L905-910），**与"空 supported_by"方向相反，不能复用**。
  需在 mixed 分支**新增**一条判定：`webResult.pass && !libResult.pass` 且结论库行 ID 为空 → 判 **pass**（来源由 web 真值集兜底），不回灌、不置 `web_downgrade`。
- **b) 同因截断**：连续两次回灌得到**同一 failure 集合**即停止重试（防同因死循环）。
- **c) 上限显式化**：把回灌次数上限常量化并写入 verdict，便于观测。

**验收**：单条混合问题的 `agent_settled` 次数 ≤ 1；trajectories 中不再出现同因连续 `fail`。

---

### P1-1 · 削减串行工具轮次（R3）

**目标**：单轮工具调用数下降，缩短串行推理链。

- 高频组合在工具层合并（如"核验对象 + 取一维数据"一次返回），减少一次"推理 → 决策 → 再调用"。
- 提示词引导"一次取全所需维度"，而非逐维试探。
- 现状基线：7 次工具调用/轮；目标 ≤ 3。

**验收**：同类问题的 `toolCalls` 中位数下降；整轮 P50 延迟下降。

---

### P1-2 · 上游取数提速与减肥（R4）

**目标**：`series-list` 10.8s / 160KB 降到可用区间。

- 上游在 `Atuohome_Agent`（8001），非本仓；**本仓可做**：
  - 在 `prism-api` 对 `/autohome/*` 加 TTL 缓存（如 60s）与并发去重。
  - **字段裁剪**：只回必要列（现 160KB 全量回传给模型，是上下文炸弹）。

**验收**：`search_cars` 端到端 p95 < 2s，回传体积 < 20KB。

---

### P1-3 · 冷启动与插件裁剪（R5）

**目标**：冷启动首 token 从 28s 降到可用区间。

- **插件裁剪**：`.pi/agent-minimal/settings.json` 现挂 12 个包，其中 `langfuse 观测 / pi-memory / pi-memory-mem0 / mcp-adapter / subagents / todo / workspace-history / usage` 对"前端对话"均不需要 → 移入独立精简 profile（前端对话只留 `guardrails` + 必要项）。
- **langfuse 端点缺失**：其 `baseUrl=http://localhost:3000`，实测 3000 端口未监听 → 要么启动 langfuse，要么移除该插件（二者取一，不能留"配了但连不上"）。
- **预热**：网关启动时预 spawn 1 个进程（warm pool），避免首个真实用户吃冷启动。

**验收**：冷启动 TTFT < 8s；`/health` 可见 `needsRestart` 联动正常。

---

### P1-4 · 上下文治理（R6）

**目标**：长会话不因上下文膨胀而持续变慢。

- 调整 compaction 阈值（`keepRecentTokens` / `reserveTokens`）。
- **工具结果入库前裁剪**：大 JSON 只保留"摘要 + 行 ID + as_of"，原文不入 branch。
- 重试轮的失败回复不留在 branch（或标记为可压缩）。
- **验收**：20 轮会话第 20 轮 TTFT ≤ 首轮的 1.5×（阈值：增幅 ≤ 50%，见 §四 #7）。

---

### P2-1 · mapEvent 补全（R7）

- `mapEvent` 补 `entry_appended`（以及 `queue_update` / `session_info_changed` / `thinking_level_changed`）→ 显式 `return null` 或转前端。
- 顺带修正 `index.ts` 中"RPC 模式 appendEntry 不出事件流"的错误注释（pi docs 已证伪）。

**验收**：网关日志不再出现"未知事件类型"。

---

### P2-2 · ctx.json 路径统一（R8）

- **统一命名**：读写使用同一 key（建议统一用 pi sessionId 或 jsonl basename，二选一并全局对齐）。
- **顺序修正**：把 `mkdirSync(userDir)` 提前到 ctx 写入之前（消除新用户首写 ENOENT）。

**验收**：新用户首轮 ctx.json 写入成功，且 extension 能读到正确 `series_key`/`scope`。

---

## 三、改造清单（文件级）

| 项 | 文件 | 改动性质 |
|---|---|---|
| P0-1 | `prism-api/main.py`（L314-339、L345-358、L364-378、L385-398、L546-568） | 新增 httpx 工厂 + 替换调用点 + 显式非 2xx 报错 |
| P0-2 | `.pi/extensions/prism-guardrails/index.ts`（L873-920）、`src/verify/completion.ts` | 语义修正 + 同因截断 + 上限常量 |
| P1-1 | `.pi/extensions/prism-guardrails/index.ts`（工具注册/描述）、提示词 | 工具合并 + 引导（需评估，勿动既有正确逻辑） |
| P1-2 | `prism-api/main.py`（/autohome 代理） | TTL 缓存 + 字段裁剪 |
| P1-3 | `.pi/agent-minimal/settings.json`、`prism-api/pi_gateway.mjs`（预热） | 插件裁剪（**直接改 agent-minimal**，已定案）+ warm pool |
| P1-4 | `.pi/settings.json`（compaction）、`prism-api/pi_gateway.mjs`（工具结果裁剪） | 阈值 + 裁剪 |
| P2-1 | `prism-api/pi_gateway.mjs`（mapEvent）、`index.ts`（注释） | 补 case |
| P2-2 | `prism-api/pi_gateway.mjs`（L315/L413）、`.pi/extensions/prism-guardrails/index.ts`（L670-683） | 命名对齐（**统一到 pi sessionId**，已定案）+ 建目录提前 |

> 说明：凡涉及既有函数实现（如 `mapEvent`、`verifyCompletion` 路由、httpx 调用点），**保留原有分支逻辑，只做叠加式修改**，并在改动时明确告知核心函数变动。

---

## 四、验收标准（可断言）

1. `8002/chat/stream` 返回体 **> 0 字节**；`8002/autohome/get_trims?series_id=6298` = 200。
2. 单条混合来源问题的 `agent_settled` 次数 ≤ 1，trajectories 无同因连续 `fail`。
3. 冷启动 TTFT < 8s；热态 TTFT < 3s。
4. `search_cars` 缓存命中 p95 < 0.5s；**冷调用（缓存未命中）≤ 11s**（受上游 10.8s 限制）；回传体积 < 20KB。注：冷调用若要 < 2s，需上游 `Atuohome_Agent` 同步优化，超出本仓范围（见 §六）。
5. 网关日志无"未知事件类型"。
6. 新用户首轮 ctx.json 写入成功且被 extension 读到。
7. 20 轮会话：第 20 轮 TTFT ≤ 首轮的 1.5×（阈值：增幅 ≤ 50%）。

---

## 五、施工顺序

1. **P0-1**（先恢复链路；运维 a + 代码 b/c）
2. **P0-2**（去重试抖动）
3. **P1-3 + P1-2**（冷启动与上游，见效最大）
4. **P1-4 + P1-1**（上下文与工具轮次）
5. **P2-1 + P2-2**（卫生与正确性）

---

## 六、已定案 / 待核实

**已定案（施工按此执行）**：

- **插件裁剪方式 → 直接改 `.pi/agent-minimal/settings.json`**（不新建精简 profile）：只维护一份配置，避免双配置真值源分裂（改一处漏一处）。
- **`ctx.json` 命名 key → 统一到 pi sessionId**：网关侧本就以 sessionId 写入（`pi_gateway.mjs` L413），改动面最小；extension 读法对齐该 key，并把 `mkdirSync(userDir)` 提前到写入之前。

**待核实**：

- `prism-api` 的启动方式（是否有启动脚本可注入 `NO_PROXY`）。
- 网关 stderr 是否有消费者（若被接进无人读取的管道，`console.error` 可能阻塞事件循环）。

**待决策（不阻塞 P0，可并行推进）**：

- 上游 `series-list` 是否连同 `Atuohome_Agent` 一起优化（本仓只做缓存+裁剪为下限方案，见 §四 #4）。

---

## 七、不做

- 不改 pi 网关的整体进程模型（一用户一进程）——经实测内存占用非瓶颈，无需改池化策略。
- 不引入新的中间件/组件，全部在既有 `prism-api` / `guardrails` / 配置层内解决。