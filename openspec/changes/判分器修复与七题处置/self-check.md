# self-check · 判分器修复与七题处置（Step6+Step9 验证记录）

> 主会话独立复跑（不采信施工自报）+ Step8 修复后全量。全部命令可复现。

## 判分器单测（Step8 后）
```
node --test eval/{trap_check,truth_check,rubric_check,replay_check,prompt_gate,report_lib}.test.mjs
→ tests 129 / pass 129 / fail 0
```

## 验证层 + abort 测试
```
node --test --import tsx src/verify/completion.test.ts tests/abort_api.test.ts → pass 9 / fail 0
（含新增回归锁："不把销量下滑归因到产品力"不判越界）
```

## 真违规方向抽查（窗口延伸不放松闸门）
- 销量下滑印证了产品力 → 判越界 ✓；销量大跌说明配置不行 → ✓；市场表现佐证产品力失误 → ✓

## 离线重放（两份 v1.2 报告，Step8 后复跑）
- rescored 73 题：diff 15（六题预期 + 15:23 无的 9 笔已归因）；其余 58 零回归
- 15:23 73 题：diff 6 全预期；其余 67 零回归
- 预期六题：cross-02 1→5 / config-06 1→5 / sales-07 1→2（事故余波留痕）/15:23→5 / cross-09 2→5 / multi-10 2→5 / sentiment-06 2→5

## E2E 实跑（Step9，eval 栈 snap-20261012-1222）
```
PRISM_API_BASE=http://127.0.0.1:8003 ... node eval/runner.mjs --only=multi-12
→ multi-12: score=5 | trap abort_residue 被拦截 | truth 锚点全中(16,879) | 轨迹覆盖 1/1
→ langfuse 挂链 1 成功（run=eval-2026-10-27T04-52-17-204Z-*）
```
两跑 0 分的真 badcase → 修复后单跑 5 分。**注意：本修复是提示级软保证，单跑通过≠稳定通过——P2 全量 repeat=3 给统计口径。**

## 全量门禁
- smoke:verify → pass 127 / fail 0 / skipped 8（e2e 门控项，按机制 skip）

## 诚实声明
1. v1.2 "rescored 修正基线 4.63" 含既有虚高（rescore 规则表缺口：config-07/10 rubric cap 被掩盖、multi-07/08 前轮封顶未复刻）——工作树判分器下重放 avg 4.59（rescored 回复）/4.53（15:23 回复）。正式新基线以 P2 repeat=3（新判分器直跑）为准。
2. rescore.mjs 忠实度闸对旧报告 mismatch 属预期（判分器已演进）；对新报告恢复可用（P1-2 修复后）。
3. 审查 P2-1/P2-4 两条"记"项依赖"当前题库无触发形态"——触发形态入库前必须先更新 replay 边界注释。
