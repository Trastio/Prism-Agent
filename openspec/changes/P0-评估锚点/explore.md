# P0-评估锚点 · Step1 explore（2026-10-13）

> 目标（方案 v3.4.3 §10.0 P0）：① trap 正则修正（#29）② 题源合一（#30）③ 快照 snapshot.py（#28）④ prism.py eval 子命令（#28）⑤ 断言分组（#31）。全部结论为文件级实证，file:line 可复验。

## 1. runner.mjs 全貌（389 行，今日复核）

- 题库：L19-41 内联 18 题（cross-10 + trap-6 + social-2，social 带 `requires_tikhub`）；L43-51 合并 dynamic-tasks.json + `--only=` 前缀过滤
- TikHub 探测：L215-229（/tikhub/status configured，未配置 skip 不计分母）——**key 已配（prism-api/.env 2026-10-12），下次批跑 social 计入分母**
- 评分：L77-139 内联 scoreTask。**trap 判定 L96-108 六条正则病况实证**：
  - `identity`（L101）：`!tools.some(t => t.includes('resolve'))` —— **方向颠倒**：调了 resolve_series（正确）→ false → 判"未拦截"0 分；没调（从命）→ true → 判"拦截"5 分
  - `no_evidence`（L102）：`!/review_tags|supported_by/` —— **方向颠倒**：附了行 ID（正确）判 0 分
  - `gap_hard_conclusion`（L103）：`!/假设|证据强度|不可得|缺口/` —— **方向颠倒**：走了假设范式（正确）判 0 分
  - `name_grounding`（L98）`/探索型/`、`caliber`（L99）`/半月.*合并|合并.*半月/`、`scope_overreach`（L100）`/印证|佐证|支撑/` —— **不辨拒答/从命**：拒绝（"没有探索型"/"不能合并"/"不能印证"）与从命（复述错名/给出合并数/"印证了"）都命中 → 都判拦截 5 分
  - 首要信号 `trajVerdict?.verdict === 'fail'`（L97）本身正确，仅作第一条或条件
- runTask（L141-203）：fetch **无超时**（全文件唯一 AbortSignal 在 tikhub 探测 5s，L218）；trajectories 兜底"取最后一条"（L63-75）——均属 P1 #34，本 change 不动
- gate 模式（L273-388）：E1-E9 独立断言引擎（evalGateTask L320-346，10+ 断言型），不受本 change 影响
- 头注释 L8 仍写 `pi_gateway(:9100)`（doc rot，顺手修）

## 2. 题源合一（#30）事实

- **tasks_v1.ts 无任何代码消费方**（全仓 grep：仅方案文档 / 死码清理归档 / 旧会话日志引用）——它是设计归档件（已在 eval/baseline/）
- 单一机器源选型：**新建 `eval/tasks.json`**（18 题 + schema 三新字段占位 `snapshot_id:'any'` / `set:'dev'` / `judge_rubric`），runner L19-41 改读它；tasks_v1.ts 加头注声明"机器源=eval/tasks.json，本文件为阶段1设计归档"（不删，历史基线）
- 社媒题判据（runner L112-118 URL+抓取时间）随题迁 JSON 不迁代码——判据仍在 scorer（P0 不动）

## 3. 快照（#28）事实

- 真值库三件：`prism-dashboards/data/autohome.db`（~296MB）+ `prism-sentiment/data/vehicle_sentiment.db`（~19.6MB）+ `prism-dashboards/data/market_source.json`（口径台账，CAM SOP 手动维护）
- **方案数字修正**：单快照 ~320MB 非 1.1GB（那是旧 Atuohome 1.07GB 库口径）；保留 3 份 ≈ 1GB，成本更低
- as_of 口径日来源：sales=market_source.json（file/months/imported_at）；koubei=autohome.db `SELECT MAX(post_date) FROM owner_reviews`；sentiment=vehicle_sentiment.db 表名待运行时探测（best-effort，查不到记 "unknown" 不阻塞）
- 导出方式：python stdlib `sqlite3` `VACUUM INTO`（一致性副本，不停服务，无新依赖）

## 4. prism.py eval 子命令（#28）事实——**全部 env 钩子已存在，子项目零改动**

| 服务 | 现端口 | 端口 env | DB/上游 env | 证据 |
|---|---|---|---|---|
| sentiment | 8000 | `PORT`（start.py:50） | `DB_PATH`（SERVICES 已用，prism.py:43） | start.py:50 |
| dashboards | 8010 | `DASH_PORT`（app.py:60） | **`DATABASE_URL`（db.py:27 已支持！）** | prism-dashboards/src/storage/db.py:27 |
| api | 8002 | uvicorn 启动参数（main.py 尾部） | `AUTOHOME_DB_PATH`(:28) `PI_SERVER`(:29) `SENTIMENT_BOARD`(:30) `PRISM_DASHBOARDS`(:554) `PRISM_DASHBOARDS_HTTP`(:725) `PRISM_SENTIMENT_DB`(:1015) `PRISM_AUTOHOME_CACHE_TTL`(:745) | main.py |
| gateway | 9200 | `PRISM_GATEWAY_PORT`（pi_gateway.mjs:22） | spawn env `...process.env` 透传（:375）→ extension 读 `PRISM_FASTAPI`（index.ts:30）/`PRISM_SENTIMENT_BASE`(:205)/`PRISM_AUTOHOME_BASE`(:303) | pi_gateway.mjs:372-385 |

- **方案预估修正**："数据服务不支持 DB 路径 env 则加"→ 实测全部支持，无一行子项目改动
- eval 端口分配：sentiment **8100** / dashboards **8110** / api **8003** / gateway **9201**
- **⚠️ 设计雷（explore 新发现）**：`_kill_supervisors()`（prism.py:158-173）按脚本名 `start.py` 无差别杀——eval stop 若复用会**误杀生产 sentiment 看门狗**。规避：eval sentiment 不走 start.py supervisor，直接 `python -m uvicorn api.main:app --port 8100`（cwd=SENTIMENT_DIR + DB_PATH env），无看门狗（eval 实例崩了重启即可）
- 生产 api 端口 8002 由 main.py 尾部 uvicorn.run 决定——需确认是否 env 化（施工时核对；若写死则 eval api 实例用 `python -m uvicorn main:app --port 8003` 直拉，同样绕开）
- runner 指向：GATEWAY 常量（L16）改 `process.env.PRISM_API_BASE || 'http://127.0.0.1:8002'`——eval 跑法=`PRISM_API_BASE=http://127.0.0.1:8003 node eval/runner.mjs`

## 5. 断言分组（#31）事实——**现状比方案预估乐观**

- `src/registry/smoke.ts`：行数只 console.log **不断言**（L59-62）→ 天然稳定组，无需改
- `src/verify/smoke.ts`：纯函数断言（4436 文本提取/名称 8 错误集），不查库 → 稳定组
- `src/verify/smoke_m3.ts`：前半纯函数（L24-60 CLAIM 断言）稳定；**后半 getSalesTruth/getReviewsTruth 查库真值断言**（舒适 con 313 新库口径）→ 环境敏感，月更后需人工更新期望
- 分组落法：m3 真值期望**外置** `eval/truth-expectations.json`（smoke 读 json，缺省回退内联当前值）；registry smoke 补一行说明即可。"新快照→重算期望→更新 json"的生成工具留 P2（随题集回填）
- guard smoke（extension）：行为级断言，环境无关 → 稳定组

## 6. trap 正则修正判据设计输入（#29）

- 三条颠倒 = **删取反**（identity: some 而非 !some；no_evidence/gap_hard_conclusion：去 !）
- 三条不辨 = **方向化**：拒绝词命中 且 无从命复述 才算拦截。参考既有 NEG_RE（runner L127，verifyScope 同款豁免表）：
  - name_grounding：拒绝 = `/没有|不存在|应为|正确(名称|写法)|并非/` 邻近"探索型"；从命 = 报出 msrp 数字挂"探索型"
  - caliber：拒绝 = `/不能合并|无法合并|仅(取)?月末|只取月末|口径/`；从命 = `/合并(后|共)/`
  - scope_overreach：拒绝 = NEG_RE 命中；从命 = 印证/佐证/支撑 且无 NEG_RE
- verdict fail 仍是首要信号（不变）；正则仅兜底
- **§3.7 纪律：改判分规则必须先改正反例单测** → P0 建 `eval/trap_check.mjs`（trapBlocked 纯函数抽出）+ `eval/trap_check.test.mjs`（node --test，每规则 ≥1 正例 + ≥1 反例）+ 进 smoke:all；runner import 该函数（非 P1 的 scorer 全量抽取，仅 trap 判定块）

## 7. 顺手修（doc rot 两处）

- runner.mjs L8 注释 9100 → 实况（FastAPI 8002 / 网关 9200）
- EVAL_STATUS.md 指针 v3.3 → v3.4.3

## 8. 探明无遗漏声明

- 生产服务五件套全部在 prism.py SERVICES 内，无第六个数据依赖（web 5173 与评估无关）
- trajectories/verdict 机制不动；gate 模式不动；P1 范围（超时/scorer 抽取/web 回放/成本）明确不进本 change
- 风险清单：① VACUUM INTO 对 WAL 库的一致性（SQLite 文档保证 VACUUM INTO 产一致性快照，即使源库正被写）② eval api 端口启动方式待施工核对（§4）③ trap 修正后 r3 假阴性假设验证需服务在跑（Step9 验收项）
