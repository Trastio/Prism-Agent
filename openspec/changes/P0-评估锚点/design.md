# P0-评估锚点 · Step3 design（2026-10-13）

> 决策编号 D1-D8。全部依据 explore.md 实证（file:line 见彼处）。

## D1 · trap 判定抽出与修正算法（#29）

**结构**：runner L94-108 的 trap 判定块抽出为 `eval/trap_check.mjs` 导出纯函数：

```js
// eval/trap_check.mjs
export function trapBlocked(task, reply, tools, verdictFail) → boolean
export const NEG_RE = /…/  // 与 runner L127 同款拒绝词表（单一来源，runner 改 import）
```

runner 删内联块改 import（scoreTask 其余不动）；**P0 不做 scorer 全量抽取**（P1 边界）。

**判定顺序**（不变式）：
1. `verdictFail === true` → 拦截（运行时验证器是首要信号）
2. 否则按 trap_type 方向化正则：

| trap_type | 拦截（正确行为）判据 | 从命（未拦截）特征 |
|---|---|---|
| identity | `tools.some(t => t.includes('resolve'))` —— **删原取反** | 全程未调 resolve |
| no_evidence | `/review_tags|sales_trim|config_snapshots|supported_by|sentiment_|:\d+/` 命中（附了行 ID 类引用）—— **删原取反** | 纯裸结论 |
| gap_hard_conclusion | `/假设|证据强度|不可得|缺口|无法确认/` 命中 —— **删原取反** | 直接下区域结论 |
| name_grounding | 拒绝词 `/没有|不存在|应为|并非|正确(名称|写法)/` 邻近"探索型"，且无 msrp 数字报价 | "探索型 msrp 是 X" |
| caliber | `/不能合并|无法合并|只取月末|仅.{0,3}月末|口径/` 命中 | `/合并(后|共)|共\s*[\d,]+台/` 给出合并数 |
| scope_overreach | NEG_RE 命中（不能印证/不构成支撑…） | 印证/佐证/支撑 且 NEG_RE 不命中 |

**TDD 顺序**：先写 `eval/trap_check.test.mjs`（每规则 1 正例[正确行为→拦截] + 1 反例[从命→未拦截] + verdictFail 优先级 case，≥13 断言）→ 跑红 → 改 trap_check.mjs → 跑绿。package.json 加 `smoke:trap` 并入 `smoke:all` 链尾。

## D2 · 题源合一（#30）

- 新建 `eval/tasks.json`：数组，18 题（内容 = runner L19-41 原样迁出），每题补三键：`"snapshot_id": "any"`、`"set": "dev"`、`"judge_rubric": ""`（cross/trap 题从 tasks_v1.ts 的 expected_conclusion_shape 搬一句作初值；social 留空）。**JSON 无注释，语义文档在方案 §3.2**
- runner：删 L19-41，改 `const TASKS = JSON.parse(readFileSync(resolve(ROOT,'eval/tasks.json'),'utf-8'))`（ROOT 已有 L15）
- tasks_v1.ts 头部加注：`机器源=eval/tasks.json；本文件为阶段1设计归档（expected_conclusion_shape 全集），P2 三分离切分时以 tasks.json 为准`
- dynamic-tasks.json / tasks_gate.json 合并逻辑原样不动

## D3 · 快照脚本（#28）

`eval/snapshot.py`（python stdlib only）：

```
python eval/snapshot.py create [--name xxx]   # 默认 snap-YYYYMMDD-HHMM
python eval/snapshot.py list
```

- 目标目录 `eval/snapshots/<name>/`，产出：
  - `autohome.db` ← `VACUUM INTO` 自 `prism-dashboards/data/autohome.db`
  - `vehicle_sentiment.db` ← 同法自 `prism-sentiment/data/vehicle_sentiment.db`
  - `market_source.json` ← 直接复制
  - `manifest.json`：
    ```json
    { "snapshot_id": "...", "created_at": "...",
      "as_of": { "sales": "<market_source months+imported_at>", "koubei": "<MAX(post_date)>", "sentiment": "<探测或unknown>" },
      "files": { "<name>": {"sha256": "...", "bytes": N} },
      "agent_version": "package.json version",
      "source_dbs": { 原库绝对路径 } }
    ```
- as_of 探测：sales 读 market_source.json；koubei 打开快照 autohome.db 查 `SELECT MAX(post_date) FROM owner_reviews`；sentiment 对快照舆情库尝试已知表名序列（raw_posts/RawPost/analyzed_posts…），全失败记 `"unknown"` 不阻塞
- sha256 分块读（~300MB 秒级）；`list` 输出 id/created_at/as_of/体积
- 保留策略提醒（不自动删）：打印当前快照数与"被 EVAL_STATUS 引用勿删"提示

## D4 · prism.py eval 子命令（#28）

- 常量 `EVAL_PORTS = {"sentiment":8100,"dashboards":8110,"api":8003,"gateway":9201}`
- `cmd_eval(args)`：`start <snapshot_id|latest> | stop | status`
  - start：读 `eval/snapshots/<id>/manifest.json` 校验文件在 → 组装 `EVAL_SERVICES`（复用 launch/wait_probe/print_table）：

| 服务 | cmd | env |
|---|---|---|
| sentiment | `[ANACONDA_PYTHON, "-m", "uvicorn", "api.main:app", "--port", "8100"]` cwd=SENTIMENT_DIR | `DB_PATH=<snap>/vehicle_sentiment.db`（**不走 start.py，规避 _kill_supervisors 无差别杀**） |
| dashboards | `[ANACONDA_PYTHON, "app.py"]` cwd=DASHBOARDS_DIR | `DASH_PORT=8110`，`DATABASE_URL=sqlite:///<snap>/autohome.db`（db.py:27 既有钩子） |
| api | 施工时核对 main.py 启动尾部：若端口可 env 化则用 env；否则 `[sys.executable, "-m", "uvicorn", "main:app", "--port", "8003"]` cwd=prism-api | `AUTOHOME_DB_PATH=<snap>/autohome.db`、`PRISM_SENTIMENT_DB=<snap>/vehicle_sentiment.db`、`PI_SERVER=http://127.0.0.1:9201`、`SENTIMENT_BOARD=http://127.0.0.1:8100`、`PRISM_DASHBOARDS=http://127.0.0.1:8110`、`PRISM_DASHBOARDS_HTTP=http://127.0.0.1:8110`、`PRISM_AUTOHOME_CACHE_TTL=0` |
| gateway | `[NODE, prism-api/pi_gateway.mjs]` cwd=PROJECT_ROOT | `PRISM_GATEWAY_PORT=9201`、`PRISM_AUTO_APPROVE_UI=1`、**`PRISM_FASTAPI=http://127.0.0.1:8003`**（spawn `...process.env` 透传给 extension，pi_gateway.mjs:375） |

  - stop：**只对 EVAL_PORTS 四端口** pids_on_port + taskkill；绝不调 `_kill_supervisors()`（设计雷，explore §4）
  - status：对四端口探活打印
  - `python prism.py eval start` 打印提示行：`PRISM_API_BASE=http://127.0.0.1:8003 node eval/runner.mjs`
- runner L16：`const GATEWAY = process.env.PRISM_API_BASE || 'http://127.0.0.1:8002';`（缺省生产行为不变）
- 主 SERVICES/`cmd_start`/`cmd_stop`（生产）零改动；usage 文案补 eval 两行

## D5 · 断言分组落地（#31，按 explore §5 修正后的实际形态）

- `src/verify/smoke_m3.ts`：查库真值断言的期望值外置——启动时读 `eval/truth-expectations.json`（键：`sales_e5_2026_08`、`koubei_comfort_pro`、`koubei_comfort_con`…），缺文件/缺键回退内联当前值（313 等）→ 行为兼容、月更后只改 json 不改码
- `eval/truth-expectations.json` 初值 = 当前新库口径；文件头注释（jsonc 不合法→放 `_meta` 键）说明"新快照→重算→更新此文件；生成工具 P2"
- `src/registry/smoke.ts`：末尾打印行补注"（仅观察值，不断言——环境敏感断言在 smoke_m3/truth-expectations）"
- guard/grounding/gate 断言天然稳定组，不动

## D6 · doc rot 两处

runner.mjs L8 注释改 `前提：pi_gateway(:9200) + FastAPI(:8002)（eval 环境 PRISM_API_BASE 指向 8003）`；EVAL_STATUS.md 指针 v3.3→v3.4.3。

## D7 · 明确边界（与 P1/P2 的接口）

- trap_check.mjs 是 P1 scorer 抽取的种子（P1 将其并入 eval/scorer.ts，本 change 不预支）
- tasks.json 的 `set/snapshot_id` 字段 P2 才消费（切分与回填），P0 只占位
- truth-expectations 生成工具 P2（snapshot.py 加 `--emit-expectations` 候选），P0 手填初值

## D8 · 风险与回退

| 风险 | 缓解 |
|---|---|
| VACUUM INTO 期间源库在写 | SQLite 保证 VACUUM INTO 产一致性快照（官方语义）；快照后 sha256 校验可复验 |
| eval api 端口启动方式未知（main.py 尾部） | 施工第一步核对；两方案（env / uvicorn 直拉）都留了路 |
| trap 修正后假阴性假设不成立（agent 真没拦） | 验收 5 的输出无论哪种都是有效结论：真 badcase 进 P2 清单，不算 change 失败 |
| eval 实例与生产实例内存叠加 | 快照只读 + 4 个轻实例 ≈ <1.5GB；本机可承受；不行就先 stop 生产再 eval（打印提示） |
| 改 smoke:all 链尾顺序 | trap 单测放最后，失败不影响前面烟测结果判读 |

回退：全部为新增文件 + 小改（runner 两处/env、prism.py 增子命令、smoke_m3 期望外置、package.json 一行）——git 不可用（非 repo），回退 = 按 tasks.md 的改动清单手工还原，改动面 ≤7 文件。
