# 评估迭代基建包 · Step2 proposal（2026-10-14）

> 目标：**基建先行**——首跑前把观测（langfuse 提前）+ 判分 + 门槛三段工程全部就绪，使首跑一次成型（全量判分 + 全量 trace + 四条件可算）。
> 事实依据 explore.md（12 缺口全部有代码级定位）。铁律：十步流程，Step5 施工子代理、Step7 隔离审查子代理。

## Block A · 观测先行（langfuse + 轨迹分离）——**最优先**

1. **栈复活**：compose 拉起六容器 + `restart: unless-stopped` + Docker Desktop 自启（**待拍板②**）
2. **插件装回**：settings.json packages + release 代际化（`p0-infra-v1` 级，跟 change 代际）
3. **writer 真实现**：score 走 legacy API（201 已实证）挂插件 traceId + eval_run_id 标签；替换 console.log 占位
4. **实例标签**：生产 9200（environment=production）vs eval 9201（environment=eval）——OTLP 侧 env 注入，防混流
5. **eval 轨迹分离**：新增 `PRISM_TRAJECTORY_FILE` env——extension index.ts:781 与 runner.mjs:44 同源读它；prism.py eval start 注入独立文件（eval/trajectories/）；北极星继续读生产文件
6. **【M5】eval 轨迹回放适配**：ops:8020 回放/BadCaseDrawer 支持指定轨迹文件路径（否则分离后 eval badcase 无法回放=分离只做了一半）
- **验收**：真实跑一题 → langfuse UI 见 trace + score 回写（两阶段联调第二步）；eval 批跑期间生产 trajectories mtime 不变；**eval 轨迹可在 ops 回放**

## Block B · 判分完备（10 项）

1. trap-07/08 value_grounding 接入（trap_check 加类别 + `trap_params` 字段 + **测试先行**，契约：改实现必先改测试）
2. runner `--set=<dev|frozen|all>`（缺省 all 兼容 ci.sh；日常纪律 --set=dev）
3. **金标数字比对**：判分前载金标数字集，锚点数字必须出现且无冲突（万/千分位/单位归一化）；**规则外置可调**（首跑后微调不动架构）
4. 六分制 + 8 态 + 中间档三类判分（top3 容差/缺口方向/舆情要素），照 trap_check 模式函数+正反例单测进 smoke
5. 条件题通用化：tasks.json `requires` 字段 + 探测 skip 不计分母；PTC 两题挂 requires:web
6. web 录制回放 fixture（照 tikhub-fixtures 模板，PTC 两题）
7. per-题超时（AbortSignal.timeout）
8. 成本台账：每题 token/时长落 eval-report
9. 舆情保质期（**待拍板①**：A=PRISM_FAKE_TODAY env 固定"今天"=快照 as_of，荐 / B=金标相对窗口）
10. query_sales month 债（实现或删描述）+ **多轮 runner 基建**（turns schema + session 续跑 + 逐轮/终轮判分）
11. **【M4】eval 期 web 禁用总开关**：默认禁 web 工具（env 或 per-task `requires:web` 放行）——60 题中 50+ 库内题防偷懒搜网，保可复现+红线#9；v3.4.3"评测期禁用"首次落地
12. **【M2】eval-report 运行元数据头**：run_id/日期/题库 git hash/snapshot_id/agent release/runner 版本——跨版本对比与 langfuse eval_run_id 的本地对应物
13. **【M7】开放项**：导出/行为题判分形态（xlsx 产物存在性/内容抽查规则）——随 L1-5 行为题草稿定，设计预留判分函数插槽
- **验收**：smoke 扩全绿（新单测 ≥15）+ --only=trap 8/8 + 判分 dry-run 抽样人工核对 + **库内题全程零 web 调用**（trajectory 抽查）

## Block C · 验证器/观测补全

verifyNames token 分类器（普通词 vs 维度名，不动 8 case 阈值）+ mapEvent auto_retry 事件。
- 验收：R1-deep 复现样本（"销量/口碑"句）零误报 + 8 case 全保。

## Block D · 门槛接线

stats.py ↔ ci.sh 接线（四条件真跑入口）+ 保留集=frozen 落 EVAL_STATUS + Pass^k k=3 基建（frozen×3 + 一致闸 verdict/8态/分差≤1）+ ci.sh 陈旧文案清理。
另并 4 件（10-14 用户质询后补扫）：
1. **【M1】工具×题目覆盖矩阵脚本**：trajectory 工具调用统计 → 矩阵落档（首跑后分析的工程化）
2. **【M3】runner 并行锁（R4 根治）**：多 runner 互踩防护——Pass^k×3 并行的前置
3. **【M6】金标重算链路 dry-run 演练**：snapshot create → _gen 重跑 → diff 生成全链走一遍（SOP 的工程验收）
4. 【M8 可选】批跑报告自动追加 EVAL_STATUS 摘要行
- **验收**：dry-run 数据上四条件全链可算出结果；--gate 模式回归 9/9；**金标重算演练 diff 为空或全部可解释**；并行 2 runner 无串题

## 依赖与施工编排

A 独立先行（半天）；B 最大（2-3 天，可拆 B1 判分规则/B2 runner 基建两个子代理并行）；C 独立（1 天）；D 依赖 B 判分产物（1-2 天）。Step5 建议派单：A 一个、B1/B2 并行、C+D 一个或主线。**批跑纪律不变：本 change 完工前不跑正式首跑**（轻量单题验证除外，如 Block A 联调）。

## 用户拍板（不阻塞 Step3 设计）

①舆情保质期 A/B（荐 A）②Docker Desktop 自启 ③首跑改基建后（工期约 1 周）是否接受
