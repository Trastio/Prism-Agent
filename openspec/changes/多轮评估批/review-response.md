# review-response（Step8 处置）· 多轮评估批 · 2026-10-25

隔离审查：**0 P0 / 2 P1 / 6 P2**（详见 审查报告.md）。处置如下，全部落账：

## P1（两条全修）

### P1-1 multi-02#t2 差价锚假阴 → **修：宽容差 rel=10% + calibration_log**
- `eval/scoring-rules.json`：tolerance_overrides 增 `multi-02#t2: {rel: 0.1}`（30,000±10%=27,000-33,000，覆盖三窗：8月末 30,000/上半年 29,000/全年 33,000）+ calibration_log 追加六字段条目（_calibration_policy 铁律）
- 不改题面/不换锚（卷册已审，改锚=改题）；宽容差是校准层动作，账随规则走

### P1-2 快照前置断言未实装 → **修：活性戳+漂移闸（主会话施工，量级 ~40 行）**
- `prism.py` eval start 写 `eval/snapshots/ACTIVE_SNAPSHOT.txt`（快照活性戳）
- `eval/multi_turn.mjs` 新增纯函数 `checkSnapshotDrift`（无多轮题跳过/无戳 fail-closed/有戳比对列 mismatch）
- `eval/runner.mjs` 装载后接闸：不一致拒跑，`--allow-snapshot-drift` 显式放行留痕
- 测试 +4（multi_turn.test.mjs），端到端三态实测：无戳拒跑 → eval 重启写戳 → dry-run 放行（banner snapshot=snap-20261012-1222 与题库一致）

## P2（2 执行 / 4 记录）

| # | 处置 |
|---|---|
| P2-1 EVAL_STATUS.md 混 10-20 尾巴 | **执行**：本 change 提交排除该文件（归档追加时按 hunk 分离） |
| P2-2 prism.py 混并行会话 PRISM_NO_BROWSER hunk | **执行**：提交按 hunk 分离（本 change 仅 PRISM_EVAL_UI_SIM 注入+活性戳两处） |
| P2-3 multi-08 t1 机器锚弱 | 记录：首跑后视情况补锚（53.5%/CLTC 三档现靠 judge_rubric） |
| P2-4 multi-02 t1 机器未锚 | 记录：间接防线已证（t1 答错车→t2 锚 26,000≠30,000 缺锚封顶） |
| P2-5 multi-06 t2 编数带缺口词边角 | 记录：出口闸 verdict fail 兜底，观察项 |
| P2-6 branch_on 零题使用 | 记录：与 self-check Gap3 一致（单测覆盖防死代码疑云），题库演进时用 |

## 施工"如实项"6 条的处置

①ui_strategy 匹配路径未被冒烟激活 → **留 v1.2 批跑实证**（skill-03 首跑若自然触发问询弹窗即真验；机制与默认代答路径 34 弹窗零挂死已证）；②回放零回归不可行（v1.1 无 reply_full）→ 接受三件套替代（单测契约+单轮路径 diff 未动+skill-03 实跑对照）；③eval-report.json 主副本被冒烟覆盖 → **恢复 HEAD（v1.1 基线态），冒烟报告留 eval/reports/ 5 份**；④prism.py 混行 → 同 P2-2 分离；⑤EVAL_STATUS 混行 → 同 P2-1；⑥Step6-10 未做 → 本文件+后续归档即 Step8-10。

## 验证态（处置后）

- 判分四套 84/84（含新闸 4 例）；scoring-rules JSON 合法；prism.py py_compile 过
- 漂移闸端到端三态实测过（拒跑→写戳→放行）
- 验收 8 条：7 过 + 1 半过（skill-03 问询路径留 v1.2，与审查结论一致）
