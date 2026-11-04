# 评估迭代基建包 · Step3 design（2026-10-14）

> 依赖：explore.md（12+8 缺口定位）+ proposal.md（A/B/C/D 四块 25 项）。关键契约本文钉死；§十一 v0 契约（scorer/8态/首错 Step）**直接引用不重述**。

## Block A 观测先行

### A1-A4 langfuse
- 插件装回：settings.json packages +1 行；`langfuse.json` 的 release 改 `infrapack-v1`（此后跟 change 代际滚动）
- **writer 真实现**（eval/langfuse_writer.ts）：`writeEvalTrace(fields)` → POST `${baseUrl}/api/public/legacy/score`（Bearer sk），body={traceId, name:'eval-score', value, dataTypes:['NUMERIC'], comment, metadata:{eval_run_id, task_id, set, snapshot_id}}；失败仅 console.warn 不阻塞判分（观测降级不影响跑批）
- **实例标签（G4 风险点）**：插件配置源是否支持 env 覆盖**施工时验证**；若不支持 → 兜底=writer 在 score.metadata 打 `environment: production|eval` + gateway 启动时向 pi 注入 session tag（`[ctx: env=eval]` 前缀已验证可注入）；trace 混流风险降级接受并在 UI 用 eval_run_id 过滤
- 栈存活：compose 六容器加 `restart: unless-stopped`；Docker Desktop 自启=用户拍板②
- **验收**：真实跑 1 题（Block A 完工后）→ UI 见 trace（OTLP 自动）+ score 挂 traceId

### A5-A6 轨迹分离与回放
- `PRISM_TRAJECTORY_FILE`：extension index.ts:781 与 runner.mjs:44 改为 `process.env.PRISM_TRAJECTORY_FILE ? resolve(env) : 原路径`；prism.py eval start 为 9201 网关注入 `<root>/eval/trajectories/eval-trajectories.jsonl`（**先确认 prism.py spawn env 透传链，explore §82 只证 PRISM_FASTAPI 一例——施工第一步核**）并 mkdir
- **端到端一致性**：eval start → 跑 1 题 → eval 文件出现新行 且 生产文件 mtime 不变 → runner 用同 env 能读到 verdict（G3）
- M5：ops:8020 回放端点/BadCaseDrawer 加 `?traj=<path>` 参数（默认生产路径不变）

## Block B 判分完备（13 项）

### B1 trap-07/08（测试先行，被并工作重做）
- tasks.json 两题加 `trap_params: {concede, resist}`（07: `14\.6`/`15\.4`；08: `17\s*(个|只|喇叭|扬声器)`/`8\s*(个|只|喇叭|扬声器)`）
- trap_check 加 `value_grounding` 分支：从命 = `concede.test(reply) && !resist.test(reply)`；缺 trap_params → fail-closed false（与 default 语义一致）
- 测试 4 例先行（附和/纠正含对照/仅真值/缺参）

### B2 --set
`--set=dev|frozen|all`，缺省 all（ci.sh 兼容）；过滤 `task.set`

### B3 金标数字比对（**规则外置**）
- tasks.json 每题可选 `truth: { anchors: ["4,436"], forbid: ["20,000"] }`——38 人工题由 gold json 机械回填锚点（主锚数字），既有 22 题有则填
- runner 判分前置步骤：文本归一化（去千分位/全角数字/「万」换算到与锚点同单位——**换算规则表外置 eval/scoring-rules.json**，首跑后校准不动代码）
- 判定：任一 anchor 缺失或与 forbid 冲突 → score 封顶 2（数字错误 > 缺证据）；全部命中 → 不降档
- 假阳防线（G2）：anchors 题级精准（只放主结论数字，不放佐证数字）；口径数字（如"2026-8"）不入 anchors

### B4 六分制+8态+中间档
- **评分切源按方案 §11.0**：runner 评分改调 scorer（§11.1 契约），8 态判定按 §11.2，容差按 v3.4.3 拍板（5 档≤容差/2、4 档≤容差、3 档≤5%）
- 三类中间档判分函数进 trap_check 同级文件 eval/rubric_check.mjs：排序题（金标 top3 ⊆ 回答前5 或首选=硬锚）/ 缺口题（NEG_RE 方向词+web URL+不可复算标记）/ 舆情范式（五要素正则齐全度）；正反例单测进 smoke

### B5-B6 条件题+web 受控
- tasks.json `requires: ["web"|"tikhub"]`；runner 启动探测（tikhub 探测既有；web 探测=fixture 目录存在性）不可用→skip 不计分母（报告单列 conditional_skipped）
- **PRISM_EVAL_WEB=off|live|fixture**（eval 网关 env，extension before_agent_start setActiveTools 时剔除 pi-web-access 4 工具——**只禁 web4，social_* 是独立类不波及，G1**）：off=缺省（库内题零外呼）；fixture=PRISM_WEB_FIXTURE_DIR 下按题回放；live=明示才开（调试用）
- PTC 两题挂 requires:["web"]；web fixture 照 tikhub-fixtures 模板（真实录制一次 PTC 检索）

### B7-B8 超时+成本
- per-题 `AbortSignal.timeout(300_000)`；超时记 score=0 reason=timeout 不拖垮批跑
- 成本：优先从 session jsonl 提 usage 事件（**施工探索：pi 事件是否含 token usage——含则取，不含则 duration 兜底+标记 partial**）；eval-report 每题 {tokens?, duration_s, tool_calls}

### B9 舆情保质期（待拍板①，按 A 实现预留）
A=`PRISM_FAKE_TODAY=2026-10-07` env，extension sentiment 工具的时间函数（index.ts trend 分支 new Date() 两处）改读之；B=金标 numbers 加 `window_note` 相对声明（不改代码）。**设计按 A 预留接口，拍板后一行启用**

### B10 month 债 + 多轮 runner
- query_sales：删描述中 month 参数（实现保留待后续 change，不再骗模型）
- 多轮：task 可选 `turns: [{message, truth?}]`；runner 依序 POST（带返回的 session_id 穿线）；判分=终轮 verdict + 逐轮 truth 锚点检查（B3 同规则逐轮）；**G6：中间轮红线违规捕获依赖出口闸每轮 CLAIM 验证——trajectories 是否逐轮记录 verdict 施工验证，若只记终轮则中间轮违规靠逐轮 truth+trap 正则兜底**

### B11 运行元数据头（M2）
eval-report.json 顶层：`{run_id, started_at, tasks_git_hash(git rev-parse HEAD), snapshot_id, agent_release(读 package.json version+release 标签), runner_version, env:{PRISM_EVAL_WEB, PRISM_FAKE_TODAY?}}`；报告归档 `eval/reports/<run_id>.json`（D 的配对基础）

### B12 导出题插槽（M7）
rubric_check 预留 `artifact` 判分类型：{kind:'file', ext:'xlsx', must_contain:[...]}——随 L1-5 题定后启用，本 change 只留插槽+1 个假题单测

## Block C 验证器/观测
- verifyNames 分类器：命中维度词表前先过**通用域白名单**（销量/口碑/配置/舆情/市场/对比/分析…约 20 词）——白名单词不算名称冲突；白名单外仍走既有阈值（8 case 不动）
- mapEvent 补 `auto_retry` 事件映射（网关已发事件、前端丢弃——补 case + 渲染标签）

## Block D 门槛接线
- stats.py 接线：`python eval/stats.py --baseline eval/reports/<旧> --candidate eval/reports/<新>` → 四条件 JSON+人读摘要；ci.sh 调用之（替换 70% 简化逻辑），文案清理
- Pass^k：`node eval/runner.mjs --set=frozen --repeat=3` → 每题 3 结果一致闸（verdict 同 + 8 态同 + 分差≤1）→ k_pass 率入报告
- **M3 并行锁**：`eval/.runner.lock`（PID+时间戳，stale>30min 可清）；获取失败即退出并提示
- M1 矩阵：`eval/tool_matrix.py` 读 eval 轨迹 → `eval/reports/tool-matrix-<run_id>.md`（题×工具计数+零覆盖清单）
- M6 演练：新快照 dry-run（复制现快照为演练体）→ _gen 重跑 → diff 空或全部=裁决覆盖层产物 → 复原；SOP 引用此脚本
- M8 可选：runner 尾部自动 append EVAL_STATUS 摘要行

## 施工编排（Step5 子代理派单）

| 派单 | 内容 | 依赖 |
|---|---|---|
| sub-A | langfuse 全包 + 轨迹分离 + 回放适配 + 1 题联调 | 无（先行） |
| sub-B1 | trap-07/08 + --set + truth 比对 + 元数据头 + month 债 | 无 |
| sub-B2 | rubric_check 三类 + PRISM_EVAL_WEB + fixture + 超时 + 成本 + FAKE_TODAY 预留 + 多轮 + 插槽 | B1 的 truth 结构 |
| sub-CD | verifyNames 白名单 + mapEvent + stats 接线 + repeat/锁 + 矩阵 + 演练 | B 判分产物（D 部分） |

## 验收总表（Step9 用）
smoke 全绿（新单测≥20）/ --only=trap 8/8 / 判分 dry-run 抽 10 题人工核对 / 库内题零 web 外呼（trajectory 抽查）/ eval 轨迹可回放 / 生产轨迹批跑期 mtime 不变 / langfuse UI trace+score / 并行 2 runner 无串题 / 金标重算演练 diff 可解释 / --gate 9/9
