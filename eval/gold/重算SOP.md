# 金标重算 SOP（快照 → 金标 → diff → 用户过目）

> 对应方案 `设计图总览/Prism-Agent-评估体系完整方案.md` **§10.0.1 L2-7 数据运营 SOP**
> （v3.4.5）："新批导入→snapshot.py create→_gen_user_gold.py 重跑（裁决覆盖层自动保拍板）→
> **diff 报用户过目**→锚点更新→EVAL_STATUS 记档（谁跑=AI，谁审=用户）"。
> 本 SOP 是该行的可执行展开；机制演练脚本 = 同目录 `dryrun_regen.py`（2026-10-14 已全链跑通）。

## 触发条件（每月，或数据侧变更时）

- CAM 月末批导入（import_sales_excel.py + market_source.json，见既有 CAM SOP）
- 舆情库周同步后若核心数字（好评率/负面帖计数）漂移
- 快照轮换：`python eval/snapshot.py` 建新快照

## 步骤

1. **建快照**：`python eval/snapshot.py`（新快照目录 `eval/snapshots/snap-<ts>/`）
2. **演练重算**：`python eval/gold/dryrun_regen.py`
   - 自动完成：复制现快照为演练体 → `_gen_user_gold.py` 重跑（输出指向演练目录，
     **生产金标不被覆写**）→ diff 新旧 gold → 演练快照上 131 断言 → 清理
   - 脚本内路径覆写：`_gen` 用 argv[1] 输出参数、`_verify` 用 `PRISM_GOLD_FILE` /
     `PRISM_GOLD_SNAP` env（两者缺省=生产路径，行为不变）
3. **diff 判定**（脚本输出即结论，人工过目）：
   - `无差异` → 重跑幂等坐实，金标无需动，直接跳第 6 步记档
   - 有差异 → 逐项区分：
     - **裁决覆盖层产物**（`_gen` 尾部 `_ov(...)` 段的字段：judge_rubric /
       expected_evidence / fail_closed / gold.numbers 改名）→ 预期内，确认后接受
     - **数字漂移**（gold.numbers 主锚变化）= 新数据真实变动 → 走第 4 步
4. **锚点更新**：数字漂移项按新快照只读 SQL 实测改 `_gen_user_gold.py` 字面量
   （生成器=实测记录的固化，不是查询引擎——重算时必须先对新快照重测再改字面量），
   同步核对 `_verify_user_gold.py` 断言与 tasks.json `truth.anchors`
5. **用户过目**：diff 摘要报用户（月度参与点，方案 §10.0.1 轮 2 用户参与点），
   拍板后 `python eval/gold/_gen_user_gold.py`（无参=写生产金标）+
   `python eval/gold/_verify_user_gold.py` 全绿
6. **记档**：EVAL_STATUS.md 记一行（谁跑=AI，谁审=用户，diff 结论）；stats.py
   门槛判定时已自动记批跑行（D6）

## 已知边界

- `_gen_user_gold.py` 为**字面量生成器**（38 题数字来自 snap-20261012-1222 只读 SQL
  实测的固化）：换新快照后直接重跑必然"无差异"（不会自动跟数据走）——这正是演练
  要暴露的事实：数据变动必须走第 4 步人工重测更新字面量，防止金标静默过期
- 演练不碰：生产金标 `user-20261013.json`（mtime+sha 前后断言）、生产快照本体
- 演练体 ~380MB（快照全量复制），演练完自动清理；`--keep` 可保留排查
