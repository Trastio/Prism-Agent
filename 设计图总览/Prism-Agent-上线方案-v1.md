# Prism-Agent 上线方案 v1.3.2（2026-10-16，登录门禁与评估收敛版）

> 定位：**方案层**。执行排期在评估闭环之后：题库全量首跑（以 tasks.json 为准，10-13 实数 60 题）→ 模考 → 本方案执行（含 40 并发压测，见 §九 step6 / §十 G2）。
> 继承提纲 §5.7（2026-10-01：单机 ECS 40 并发起步）全部已定决策，并校正其 10-08 自给化后的过时描述。
> v1.1 变更：①全篇"工位机"改称**本地开发机**（即你现在这台 Windows 电脑）②新增**§一 代码实况审计**（逐服务对照真实代码）③修正 v1 错误：autohome.db 云上**必须可写**（CAM 导入经 POST /import 写库）④新增必改代码清单与 Nginx 真实路径清单。
> v1.2 变更（2026-10-13）：§7.1 落拍板——打标管线本地**夜跑常态化**（D3 加强版），PAI-EAS 降为备胎（量化触发线），A/B/C 三选项收案；夜跑**手动触发、不建自动调度**（同日拍板）；§十一 D3 已决。
> v1.3 变更（2026-10-13，一致性收敛）：①Nginx location 按 vite 实测 target 分三组（16→8002、/static+/api/dashboard→8000、/ws→ws://8002）；②Gate G1 题数 38→34；③§十一"待拍板 5 项"→"4 项（D1/D2/D4/D5；D3/D6/D7 已拍板）"；④欠账数标口径日（5,845=10-12 / 5,523=10-13）；⑤§7.1 标题改"上云评估（结论：留本地）"；⑥"六容器"→"4 常驻+1 可选+build 阶段"；⑦执行序去掉重复的"40 并发压测"；⑧env 名统一 `AUTOHOME_DB_PATH`。**复核补正（同日）：②题数回正 38**（v1.3 误回 34——金标实数 38 且 10-13 已拍板保 38）；**⑨补跨容器地址 env `PRISM_DASHBOARDS_HTTP`/`SENTIMENT_BOARD`**（云上须改容器名，漏配则 /dash、/sentiment-board 反代连 127.0.0.1 扑空）。
> v1.3.1 变更（2026-10-13，代码变动后复核）：**北极星端口化（D8）落地后 vite proxy 实测 18→15 条**——/trajectory /attribution /badcases 迁出主站转 prism-ops:8020（**Nginx 不配这三条**），/events 埋点 ingest 保留主站；三组 target 改为 13→8002；G1/定位行题数改以 tasks.json 为准（10-13 实数 **60**=人工 38+存量+trap）；补 `.pi/skills/` 等同须进镜像项；补"轨迹/埋点库不迁移、云端从零"+轨迹文件无轮转观察（本地已 303MB）。
> **v1.3.2 变更（2026-10-16，登录门禁与评估收敛后复核）**：①vite proxy 15→**16** 条（登录门新增 /auth）；②§五.3 重写——产品登录门已上线，Basic-Auth 降为可选叠加（D2 语境收窄）；③轨迹轮转已上（尾巴包），§十二观察项同步收敛；④§九.4 密钥注入加 PRISM_ENV=prod/PRISM_AUTH_SECRET（fail-closed 拒启）；⑤G1 加 prompt-gate 前置+题数 72 口径，G4 加登录云端复测；⑥上云依赖时序：多轮话术→v1.2 批跑、舆情降本落地（并行窗口）排在上云执行前；⑦上线日避开 CAM 月末零售滞后窗口（月末批零售常滞后至次月上旬，首日门面别停在两个月前口径）。

---

## 一、代码实况审计（2026-10-12 逐文件实测）

### 1. prism-web（前端）

- **实际形态**：Vite + React；`package.json` 有 `build` 脚本（`tsc --noEmit && vite build`），tsc 现状 0 错 → **build 产物可直接上云**，dev server 不上云
- **必迁移**：vite.config.ts 里 **16 条 proxy 路径**全部要转成 Nginx location（**v1.3.2 实测更正：登录门禁（10-15）新增 `/auth` → 16 条**——`/trajectory` `/attribution` `/badcases` 已迁出主站转 prism-ops:8020，Nginx **不要配**这三条；`/events` 埋点 ingest 保留主站；**施工时从 vite.config.ts 脚本生成，勿手抄**）：
  `/chat/stream`、`/chat/abort`、`/dashboard`、`/session`、`/ws`(WebSocket)、`/sentiment-board`、`/dash`、`/static`、`/api/dashboard`、`/ui-response`、`/events`、`/identity`、`/export`、`/tikhub`、`/skills`（/skills 为社媒能力包新增，漏配=能力总览 404）
  ⚠️ **16 条不是同一 target（v1.3.2 实测 vite.config.ts）**，Nginx 必须按**三组**落 `proxy_pass`：**14 条 → `prism-api:8002`**（含 `/auth` 与 `/ws`）（含 `/ws`）；**`/static` + `/api/dashboard` → `prism-sentiment:8000`**；**`/ws` → `ws://prism-api:8002`（带 Upgrade/Connection 头）**。勿一律指向 8002，否则 `/static`、`/api/dashboard` 云上 404。

### 2. prism-api（FastAPI main.py + Node pi_gateway.mjs，同容器）

- **依赖**：有 requirements.txt（fastapi/uvicorn/httpx/python-dotenv 级，轻）
- **env 实际消费清单**（来自代码）：`AUTOHOME_DB_PATH`、`PI_SERVER`、`PRISM_SENTIMENT_DB`、`SENTIMENT_BOARD`、**`PRISM_DASHBOARDS_HTTP`（prism-api→:8010 的地址，云上改容器名；fallback 别名 `AUTOHOME_HTTP`，main.py:879）**、`PI_BIN`、`PI_CODING_AGENT_DIR`、`PRISM_AUTO_APPROVE_UI`（缺它工具挂死）、`PRISM_GATEWAY_PORT`、`PRISM_TURN_TIMEOUT`、`PRISM_MAX_POOL`（默认 12）、`MEM0_API_KEY`、`TIKHUB_KEY_PRISM`（.env 单源；网关读取后以 PRISM_TIKHUB_KEY 名注入 pi 子进程）、`TIKHUB_BASE_URL`、LANGFUSE_*。⚠️ `SENTIMENT_BOARD` 与 `PRISM_DASHBOARDS_HTTP` 是**跨容器地址**，云上 compose 里必须改成容器名（如 `http://prism-sentiment:8000`/`http://prism-dashboards:8010`），漏改=反代连 127.0.0.1 扑空
- **❗必改代码 1（两处 CORS 硬编码）**：`main.py:51` 与 `pi_gateway.mjs:399`（原文误记 425，425 是 /chat 处理器；CORS 头在 399）写死 `http://localhost:5173` → 改为 `PRISM_ALLOWED_ORIGIN` 环境变量（云上 Nginx 同源反代，其实可收紧为关闭，但必须 env 化，不能留死值）
- **pi 运行时 Linux 化（零代码改动，全是配置）**：`PI_BIN` 已是 env 可覆盖（默认指向 `pi-windows-x64/pi.exe`，pi_gateway.mjs:51）→ 云上 `PI_BIN=<npm 安装的 Linux pi>`；spawn 参数全跨平台（`--mode rpc --approve --session-dir -e ...`）
- **`.pi/agent-minimal/` 整目录必须迁移**（pi 的家目录，代码写死引用）：`auth.json`（DeepSeek 密钥——**secret 注入不进镜像**）、`settings.json`、`npm/`（7 个 pi 插件，云端用 `pi install` 重建：permission-system / cc-safety-net / langfuse / web-access / ask-user / usage / subagents）、`models-store.json`
- extension（prism-guardrails/index.ts）纯 TS + fetch，**无原生模块依赖**（better-sqlite3 的 Bun NAPI 禁令在 Linux 同样成立，现状已合规）
- **同须进镜像（v1.3.1 补）**：`.pi/skills/`（2 个：car-reputation-research / config-compare——skill v2 已改动态扫描，漏拷=load_skill 空转）、`.pi/extensions/`、`AGENTS.md`/`SYSTEM.md`（提示词层）。注意 `.dockerignore` 只排除 `.pi/sessions/`，勿把整个 `.pi/` 排掉

### 3. prism-dashboards（口碑/配置/市场三看板）

- 依赖 7 个包（轻）
- **❗v1 错误修正：`data/` 整目录必须挂卷且可写**——autohome.db 是 WAL 库且 CAM 月末导入经 `POST /import` **写库**（import_sales_excel.py upsert sales_trim），另有 7 个可写 json 配置（market_source/option_prices/policy_prices…）。不是只读快照。
- `AUTOHOME_DB_PATH`（env；对应 `main.py` 内变量 `AUTOHOME_DB`）默认相对路径已由 env 钉死能力，云上注入 `/data/...`

### 4. prism-sentiment（舆情查询面）

- **核心依赖轻，torch/unsloth 在 requirements.txt 里已注释**（F-16 设计：不装则维度口碑优雅降级）→ **云端直接 `pip install -r requirements.txt`，镜像小**
- `DB_PATH` env 钉死（相对路径换库的老坑已防）；vehicle_sentiment.db 为只读快照（云端不写）
- start.py supervisor（崩溃 3s 重启）云端由 docker `restart: unless-stopped` 替代

### 5. prism.py 启动器（Windows 专属，不上云）

- netstat/taskkill/GBK 解码/os.startfile/bat 壳/Startup lnk 全是 Windows 专属 → **云上由 docker compose + healthcheck 替代，prism.py 不迁移**，本地开发机继续使用
- 其携带的关键 env（`PRISM_AUTO_APPROVE_UI=1` 等）必须写进 compose environment

### 6. 全局卫生检查（实测通过）

- 服务代码**零盘符/绝对路径硬编码**（grep `C:\` 干净）
- Windows 专属清单（云上不需要）：prism.py、pi-windows-x64/、Startup lnk、better-sqlite3 中文路径 workaround、os.startfile
- **.dockerignore 必须包含**：`node_modules/`、`pi-windows-x64/`、`.pi/sessions/`、`logs/`、`业务数据/`、`*.db*`、教材 PDF、`设计图总览/`（镜像瘦身，现仓库这些目录数 GB）

## 二、总体拓扑

```
用户浏览器（49 人，无登录，localStorage 本地 ID）
   │ HTTPS 443（域名 + ICP 备案）
   ▼
Nginx（ECS 本机，唯一公网入口）
   ├─ /            → prism-web dist/ 静态文件
   ├─ 13 条 location（§一.1，含 /ws）→ prism-api :8002
   │      └─ pi_gateway :9200（同容器 spawn）
   │           └─ pi RPC 池（PI_BIN=Linux pi，上限 12×215MB）
   │                └─ DeepSeek API（远程，配额宽裕 60 倍）
   │      └─ 容器内再反代：/sentiment-board→:8000、/dash→:8010（仅本机回环）
   ├─ /static + /api/dashboard → prism-sentiment :8000（vite 实测直连目标）
   ├─ prism-sentiment :8000 ─ vehicle_sentiment.db（只读快照）
   ├─ prism-dashboards :8010 ─ autohome.db（**可写**，CAM 导入）
   └─ /data 卷：prism_events.db + .pi/sessions 轨迹 + 两库 + 备份
   ★ prism-ops :8020 不进上图公网面——仅宿主机 loopback 映射（127.0.0.1:8020），管理者经 SSH 隧道访问（D8 方案 A，见 §四）
```

自给化后原"上云三风险"处置：#1 外部服务暴露 → 子服务只绑内网，仅 Nginx 443 对外；#2 限流穿透 → 写端点仅管理者后台路径；#3 TikHub 单点 → 随采集面留本地开发机移出云上风险面。

## 三、资源与预算（1 个月包月，以购买页实测为准）

| 项 | 规格 | 依据 | 估算 |
|---|---|---|---|
| ECS | ecs.g9i.xlarge 4c16g，Alibaba Cloud Linux 3 | §5.7 | ~¥500-800/月 |
| 数据盘 | 50GB ESSD 挂 /data | 库 371MB + 轨迹 + 备份余量 | ~¥35/月 |
| 带宽 | 峰值 5Mbps 按流量 | 40 路 SSE ≈1.6Mbps，流量小 | ~¥0.72/GB×<10GB |
| 证书/域名 | 免费 DV + 一个域名 | | ~¥50/年 |
| **首月合计** | | | **~¥600-900** |

内存预算（实测锚点，2026-10-13 审查修订）：OS+Docker+Nginx ~1.5GB；api+gateway ~0.3GB；**pi 池：MAX_POOL=12 是软顶不是硬顶**（代码复核 pi_gateway.mjs:346-362：池满且全部在忙时仍 spawn 新进程，"排队"仅打日志不生效；仅空闲进程会被 LRU 淘汰）——常态 12×215MB=2.6GB，**40 并发全忙最坏 ~40 进程 ≈ 8.6GB**；sentiment+dashboards ~0.4GB → 常态合计 ~5GB/16GB 余量 3 倍，**40 并发最坏 ~11GB/16GB：能活但无排队保护**（真排队/硬顶列入必改候选，G2 压测必测此场景）。Langfuse 不上 ECS（§七）。

## 四、容器化清单（执行 change 的施工范围）

**compose 容器**：**5 常驻**（`nginx` / `prism-api`（含 pi_gateway + pi 池）/ `prism-sentiment` / `prism-dashboards` / **`prism-ops`（北极星运营看板，2026-10-13 D8 拍板方案 A）**）+ **1 可选**（`redis`，默认 no-profile）；另有 **build 阶段**产出 prism-web dist（非常驻容器）。

**prism-ops 上云形态（D8 · 方案 A：部署上云 + SSH 隧道访问，不上公网）**：
- 部署：compose 加容器（与 prism-api **只读共享 volume**：prism_events.db + .pi/sessions/trajectories.jsonl——数据同机实时读，零同步）；容器内 `PRISM_OPS_HOST=0.0.0.0`（容器内绑 127 连不上端口映射），compose `ports: ["127.0.0.1:8020:8020"]` **只映射宿主机 loopback=零公网暴露**（不进 Nginx location，nmap 扫不到）
- 访问：管理者本地 `ssh -L 8020:localhost:8020 <ecs>` 建隧道后浏览器照常开 localhost:8020（上云时落一个双击 .bat 壳，模板：`ssh -N -L 8020:localhost:8020 user@<ECS_IP>`）
- 理由：北极星看的是**线上实时埋点**（数据源在云上，留本地看不到——与 langfuse 不同，后者看本地批跑轨迹）；SSH 隧道=零暴露面+零鉴权建设，内测期最优

| 容器 | 基础镜像要点 | 挂载 | 关键 env |
|---|---|---|---|
| prism-api | node:20 + python3.11 双运行时（或 node 主 + pip 装 main.py 依赖） | /data/sessions→.pi/sessions、agent-minimal | PI_BIN、PRISM_AUTO_APPROVE_UI=1、AUTOHOME_DB_PATH、PRISM_SENTIMENT_DB、**SENTIMENT_BOARD + PRISM_DASHBOARDS_HTTP（跨容器地址，改容器名）**、DEEPSEEK_API_KEY(secret)、PRISM_ALLOWED_ORIGIN(新) |
| prism-sentiment | python3.11 + requirements.txt（torch 已注释） | /data/vehicle_sentiment.db(只读) | DB_PATH |
| prism-dashboards | python3.11 + requirements.txt | **/data/autohome.db + 7 json（可写）** | — |
| prism-ops | python3.11 + FastAPI（极轻） | prism_events.db + trajectories.jsonl **只读**共享 | PRISM_OPS_HOST=0.0.0.0（默认 127.0.0.1，ops_server.py:498） |
| nginx | nginx:alpine + conf（15 location + 静态 + HTTPS） | dist/ | — |

**必改代码（执行 change 第一步）**：
1. CORS env 化（main.py:51 + pi_gateway.mjs:425 两处）
2. 生成 Nginx conf（15 条 location 承接 vite proxy，**按 §一.1 三组 target 落 `proxy_pass`** + WebSocket upgrade for /ws；北极星三路径不配，见 §四 prism-ops 段）
3. `.dockerignore`
4. prism-web 生产 build 验证（API base 全相对路径 ✓ 现状已满足）
5. **全容器统一 TZ=Asia/Shanghai**（北极星看板本地日分桶依赖 OS 时区，漏配=日期桶漂移一天；北极星 change 已定，v1.2 审查补登）

## 五、网络与安全

1. HTTPS：域名 + 免费 DV，Nginx 终止，80→443
2. 子服务仅 docker 内网/127.0.0.1；安全组只开 22（限办公 IP）+ 443
3. **v1.3.2 重写（登录门禁已于 2026-10-15 上线）**：产品级统一口令门已就位（token/HttpOnly/user_id 服务端签发防冒用/全路由 401）——"伪造 user_id"暴露面已消。原 Nginx Basic-Auth 降级为**可选叠加层**（D2 语境更新：上云时 HTTPS+强密码+secure cookie 必做，Basic-Auth 是否叠加留 D2 一并拍）。上云 6 项升级清单（速率限制/登出吊销/admin 独立凭证等）真源=openspec/changes/登录门禁/verification.md
4. 密钥矩阵（D6 拍板后修订）：云上需 **DEEPSEEK_API_KEY**（agent-minimal/auth.json 注入）+ **TIKHUB_KEY_PRISM**（2026-10-13 D6 拍板上云，社媒工具云端可用，8 次/轮成本护栏兜底）+ Nginx Basic-Auth 口令；GLM/bocha/tavily/anspire/Langfuse 密钥留在本地开发机。⚠️ 连带观察（10-13 审查）：prism-sentiment 的 top-opinions 查询路径调 GLM 做同义归并（进程内缓存，重启首调 ~9s）——GLM 留本地则该看板项云端降级，执行 change 须验证其降级形态

## 六、数据层与运营

| 库 | 云上角色 | 更新方式 |
|---|---|---|
| autohome.db | **可写**（仅 import 端点写） | CAM 月末：scp xlsx 上云 → 跑 import 脚本或走 POST /import（SOP 平移）；market_source.json 同步更新 |
| vehicle_sentiment.db | 只读快照 | 本地开发机每周导出 → scp 替换 |
| prism_events.db + .pi/sessions（含 trajectories.jsonl） | 运行时可写 | 与生产库物理隔离（红线）；每日快照留 14 天。⚠️ v1.3.1：trajectories.jsonl 本地已 **303MB 且无轮转**（append-only 单文件），v1.3.2：**轮转已上（2026-10-16 尾巴包：>100MB 轮转 .1）**，云端磁盘告警仍保留；**初始迁移不带**（本地 303MB 为开发测试数据，云端从零积累，北极星看线上实时数据正合适） |

备份：数据盘每日自动快照（~¥1-2/月）；库变更前后手动快照。

## 七、Langfuse 与舆情采集面（两个"不上云"决策）

- **Langfuse 云端不上**：self-host 需 4-6GB（ClickHouse）挤占余量；cloud 合规未结论；trace 兜底三件套（verdict.json/trajectories/prism_events）已实测覆盖评估闭环 → **合规未决从阻塞项降为远期决策**
- **舆情采集面留本地开发机**（TikHub 采集 + GLM 打标 + Qwen3-4B ABSA）：ECS 无 GPU；采集是批处理不需在线；代价=舆情数据 1-7 天延迟（可接受）

### §7.1 微调模型（Qwen3-4B ABSA）上云评估（结论：留本地，见 §7.1.1）

**架构事实先行**：微调模型只存在于**采集打标管线**（批处理），**查询路径完全不碰模型**——看板与 Agent 只读 `post_comments.dim_sentiment` 列（dashboard.py 的 `_check_comment_model_available` 只读加载标志不做推理）。所以**上线的网站永远不需要 GPU**；问题收窄为"新采集的评论，由谁在哪儿打标"。

**实测负载（2026-10-12 查库）**：日增评论 1k~1 万条、峰值单日 4.4 万；存量 79,129 条中已打标 73,284、欠账 5,845（10-12 口径；10-13 复核为 5,523，见 §7.1.1）。按 CPU 推理 4B-4bit 的实测速度（用户确认"很慢"），万条批次 CPU 需十几小时起——**CPU 跑批不可行，直接排除**。

| 阶段 | 方案 | 成本 | 触发条件 |
|---|---|---|---|
| 一（内测期，本方案默认） | 打标管线留本地开发机（有 GPU），库快照**周同步**上云；热门车系上市期可手动加同步 | ¥0、零改动 | 现在即生效 |
| 二（扩量期）**首选：LLM prompt 替代微调**——评论 ABSA 是"15 维度#情感"结构化抽取，DeepSeek/GLM prompt 可做；万条 ≈ 数元 token 费；管线随之上云收尾 | **前置实验（必须）**：抽 1,000 条已打标评论双跑（微调 vs prompt），维度+极性一致率 ≥90%（阈值人工定）才切换；历史数据不重标，看板 as_of 声明注明引擎版本切换点 | API 数元/万条 | 内测站稳、需要缩短舆情延迟时 |
| 二 fallback | PAI-EAS GPU 按量实例部署 LoRA adapter，仅跑批时段拉起（T4 档约 ¥1-3/小时，月几十元） | ~¥30-100/月 | 一致性实验不达标 |
| 三（训练侧） | 后续微调新版本：继续用本地开发机 GPU；或按需开竞价 GPU 实例跑数小时 | 数元/次 | 需要重训时 |

**推荐路径（2026-10-12 实验后修订）**：~~prompt 替代为主攻~~ → **实验证伪**。1,000 条实测（scripts/absa_prompt_experiment.py + result/detail 落档）：零样本 GLM-4-flash vs 微调标签——整条一致 14.8%、维度×极性 F1 0.26、**负面检出召回仅 37%**；非中性子集（微调给出 ±1 的 502 条）F1 0.37/负面召回 48%。40 条分歧人工仲裁：**微调明显更准（52% vs 5%）**——微调的噪声集中在无实义短评乱标单维 0，但在实义评论上（尤其负面与维度定位）远强于零样本 flash。GLM 行为缺陷清单：漏负面、无内容评论过度触发全正、维度错位（异响→外观）、词汇漂移 42 对（"动力"vs"动力/加速"）。
**修订后（同日二轮实验后再次修订）**：**glm-5.3-flash 复活 prompt 路线，但引入新约束——口径断层**。1000 条配对：F1 0.26→**0.42**、非中性 F1 0.37→**0.55**、负面召回 37%→**52%**（非中性 70%）、精度翻倍（过度触发已修）；32 条分歧仲裁**反转**：5.3 更准（**41% : 19%**，微调残留优势在隐含负面/语境习惯；5.3 强在讽刺识别"三连杆我谢谢"/"攒续航满意必须满意"与价格抱怨）。**但聚合漂移是硬约束**：总负面 +29%（330:256），外观负面×3.0/智能化×2.25/续航×1.75，智能化/智驾/安全性/内饰净值**符号翻转**——直接换引擎=看板跨期对比失真。

**扩量期三选项（PM 口径资产决策）**：
| 路线 | 口径 | 成本 | 代价 |
|---|---|---|---|
| A. PAI-EAS 跑批微调 | 与历史连续 | ~¥30-100/月 | 最省心，微调噪声（无实义乱标）延续 |
| B. **5.3-flash 持续打标 + 历史全量重标一次** | 升级为新口径（重标写新列留原值审计，as_of 断点声明） | 重标 7.9 万条一次性 ~¥80-150；后续 ~¥100-300/月（日增 1 万条峰日 4.4 万） | 一次性工程 + 月成本高于 A；顺带修复微调乱标噪声 |
| C. 双引擎并行一期（新评论双标对比） | 观察期 | B 成本 + 微调侧 | 决策最稳，拖扩量期 |

**推荐**：内测期不变（本地 GPU）；扩量期 **A 起步保连续**，若决定切 B 先用 C 双跑 2-4 周攒证据。

### §7.1.1 2026-10-13 拍板（D3 加强版）：本地夜跑常态化，GPU 租用降为备胎 ✅

用户拍板，取代上表"扩量期三选项"的悬置状态：

- **打标管线全链路留本地开发机，夜间定时跑批**——TikHub 采集 → GLM 帖子级分析 → Qwen3-4B 评论级 ABSA 全在本地夜里完成；阶段一从"内测过渡"升级为**常态方案**，不再以"扩量必迁云"为前提。理由：①查询路径零推理（网站永不需要 GPU），GPU 只在夜批用，与白天使用不冲突；②不换引擎=口径连续（两轮实验证明的硬约束自动满足）；③49 人内测量级（日增 1k~1 万、峰值 4.4 万）本地 RTX 4080 Laptop 可承受（窗口实测见下）。
- **同步节奏**：起步维持**周快照**上云；将来需要日级舆情时效（如新车上市期）再加夜间 scp+换库自动化（半小时级工作量）。用户看到的数据新鲜度瓶颈在同步节奏，不在打标。
- **PAI-EAS 降为备胎，量化触发线**：夜跑批**连续一周拖过次日 08:00 才完成** → 启动迁移评估；未触发不花钱。
- **配套三件事**：①**夜跑由用户手动触发（2026-10-13 拍板：不建自动调度，每晚跑不跑、几点跑由用户临场定）**——手动执行 daily_update.py 即可；运行环境=PATH Anaconda Python + `KMP_DUPLICATE_LIB_OK=TRUE`（prism-sentiment venv 无 torch/unsloth，requirements 里注释着，属 F-16 设计）；跑批期间勿让机器睡眠（GPU 段峰值日 ≤2h，睡前启动当日可完成）；②断更天然容忍：手动节奏下"某晚没跑=数据停在最近一次 as_of"，舆情端 F-16 优雅降级不崩，次日手动补跑即可（daily_update.py 退出码 0/1/2/3 供核查当晚是否成功）；③夜跑窗口实测**已完成（2026-10-13，scripts/absa_throughput_test.py，300 条真实欠账样本）**：吞吐 **6.63 条/s**（含预热批，稳态 ~8-9 条/s；150ms/条）、显存峰值 5.8/12GB、模型加载 60s——**日增 1 万 ≈ 25 分钟、峰值 4.4 万 ≈ 1.8 小时、欠账 5,523（10-13 复核）≈ 15 分钟，08:00 触发线余量约 6 倍**（峰值日叠上 TikHub 采集与 GLM 帖子级分析的 API 耗时，也远在夜窗内）。
- **A/B/C 处置**：A（PAI-EAS）= 上表触发线的备胎；B（5.3 全量重标换口径）= 仅当未来主动决定升级口径时再议（聚合漂移硬约束仍在，总负面 +29%/外观×3.0）；C（双引擎并行）= 并入触发线触发后的评估动作，不再单独排期。

## 八、监控运维（最小集）

compose healthcheck + 阿里云云监控免费项（CPU/内存/磁盘告警）+ Nginx 5xx 周查；日志 docker logs 落 /data/logs logrotate 7 天。观测三件套按周由管理者拉取。

## 九、迁移步骤（9 步，执行 change 按此施工验收）

1. 购 ECS/数据盘/域名，**第一天提交 ICP 备案**（2-4 周，最长项）
2. **必改代码 change**（CORS env 化 + Nginx conf + .dockerignore + 5 份 Dockerfile + compose；**+prism-ops 容器化**：PRISM_OPS_HOST env 已落盘（ops_server.py 尾部，本地默认 127.0.0.1 不变），剩 Dockerfile/compose 条目/events+trajectories 只读 volume 挂载/隧道 .bat 模板四小项）
3. 云端装 Docker 起 compose（无数据），全链路冒烟（smoke 云端版）
4. 密钥注入（**含 `PRISM_ENV=prod` + `PRISM_AUTH_SECRET`——fail-closed 拒启断言：不设直接起不来**），验证 DeepSeek 连通 + **红线四道闸云端复测**（裸 SQL 拦截/fail-closed/出口闸/名称真值）
5. 数据上云：两库 scp → /data 挂载 → 口径抽查（E5 口碑 1187——2026-10-13 复核✓；风云T7 舆情 10-11 记 515 → 10-13 核库已 ~630，**锚点数字随舆情周更持续漂移，执行日以当日库值复核**）；**prism_events.db 与 trajectories.jsonl 不迁移**——本地留档，云端从零积累
6. **40 并发压测**（gate）+ 修复｜**本地已实测通过（2026-10-31）**：40 用户并发 40/40 成功、0 错误、峰值内存 3.56GB（约 90MB/进程，远低于估算 215MB）；p95 107s（瓶颈为模型 API 时延，非容器）。**云端仍需复测**（G2 判据不变）
7. DNS 切换 + 灰度（5 人×3 天 → 49 人）
8. 快照策略 + 告警 + 运营手册（CAM 云版 SOP/舆情周同步 SOP/值守一页纸）
9. 本地开发机保留 1 个月热备（DNS 可随时切回），之后才允许退役

**回滚**：任一级故障 → DNS 切回本地开发机（prism.py 一键拉起）。

## 十、上线 Gate（全绿才放量）

G1 评估（tasks.json 全量批跑过发版门槛 4 条件 + 模考；题数以 tasks.json 为准——10-13 实数 60，**v1.2 起含多轮批 72**；**前置：prompt-gate 绿**——提示词指纹与批跑报告一致）｜G2 40 并发压测（错误率<1%/无锁死/内存<70%）｜G3 红线云端复测｜G4 安全（镜像无密钥/nmap 子服务不可达/**登录门云端复测：401 逐路由 + 登录链路 + user_id 防冒用**）｜G5 数据一致性抽查｜G6 备份恢复演练

> **G2 本地实测基线（2026-10-31，Docker Compose 本地栈，40 个独立 token）**
>
> | 场景 | 结果 |
> |---|---|
> | `/health` 40 并发 × 800 | 800/800 成功，p95 59ms，1148 req/s |
> | `/chat` 20 用户并发 | 20/20 成功，p50 68s / p95 90s，峰值 1.82GB |
> | `/chat` 40 用户并发 | **40/40 成功**，p50 83s / p95 107s / max 128s，峰值 **3.56GB** |
>
> 判据对照：错误率 0% < 1% ✓｜无锁死 ✓｜内存 3.56/15.44 = 23% < 70% ✓
>
> 已知约束：**同一用户并发第二请求会被拒**（网关按用户维护单一 pi 进程），前端须保证同一会话串行；40 并发下 DeepSeek 上游未限流，生产需监控配额。

## 十一、待拍板 4 项（D1/D2/D4/D5；D3/D6/D7/D8 已拍板）

| # | 决策 | 推荐 |
|---|---|---|
| D1 | 域名+备案 | **走**，第一天提交；期间 IP+Basic-Auth 过渡 |
| D2 | 准入门 | **v1.3.2 语境更新：产品登录门已上线**，D2 收窄为"上云叠加层是否要 Basic-Auth"（推荐：不叠，登录门+HTTPS 足够；叠加徒增 49 人运维） |
| D3 | 舆情采集留本地开发机 | **⚖ 2026-11-01 翻案：采集面上云**（用户拍板）。原否决理由「ECS 无 GPU（Qwen3-4B CPU 打标不可行）」已失效——10-20 极性引擎切 DeepSeek（9c9f64f）、Qwen3-4B 退役、全链 API 化；TikHub key 已在云端（D6）。落地=云端 cron 跑 daily_update 对云端栈 + 舆情预算护栏 env 搬云 + 工位机 PrismSentimentDaily/Catchup 退役 + 本机舆情库降级开发副本。口碑（之家直采）维持工位机不翻案（反爬硬约束） |
| D4 | Langfuse 云端不上 | **不上** |
| D5 | Redis | **不上**，compose 预留 profile |
| D8 | 北极星运营端口上云形态（2026-10-13 拍板） | **方案 A：部署上云 + 只映射宿主机 loopback + SSH 隧道访问**（不进 Nginx/不挂 Basic-Auth/零公网暴露；数据同机实时读，详见 compose 容器节 prism-ops 段） |
| D6（10-13 审查新增） | TikHub key 是否上云 | **✅ 2026-10-13 已拍板：上云**。TIKHUB_KEY_PRISM 注入云端 env，社媒深挖对 49 人开放；成本护栏（8 次/轮）已在执行层兜底 |
| D7（10-13 审查新增） | permission `--approve` 全自动批准是否收紧 | **✅ 2026-10-13 已拍板：维持全自动批准，含付费工具（花钱也允许），不做分级确认**。防线=工具白名单 fail-closed + EXCLUDE + 成本护栏 8 次/轮（护栏保留防刷）；网关继续依赖 PRISM_AUTO_APPROVE_UI=1 |

## 十二、执行期待验证项（方案层无法拍死的）

- ~~Linux 版 pi（npm 包）RPC 行为与 Windows pi.exe 一致~~ **已实测（2026-10-31，Node 22 + pi 0.85.1）**：端到端对话成功；**关键：npm 包版本必须锁 0.85.1**，1.0.1 会出现"deepseek-v4-flash 跨 4 个 provider 歧义"。**Linux Bun 二进制版仍未测**（本地为 Windows pi.exe）
- ~~extension 在 Linux 运行时加载~~ **已实测（Node 运行时）**：prism-guardrails 正常加载、`PRISM_TRAJECTORY_FILE` 生效；**已在镜像中补装 `better-sqlite3`**（src/tools/_shared.ts 直接 import）；Bun 运行时未测
- ~~compose 全链路 + Nginx location 的 WebSocket/长流行为~~ **已实测**：5 容器 + Nginx 反代 + SSE 长流 + 登录门 + 完整工具调用对话（identity/resolve → dashboard/sales×3 → verify/claim）全部通过
- ~~MAX_POOL 软顶在 40 并发下的实际进程数/内存/无排队行为~~ **已实测**：40 进程无排队、无拒绝，峰值 3.56GB（见 §十 G2 注）
