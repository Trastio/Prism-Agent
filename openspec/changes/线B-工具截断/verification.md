# 线B-工具截断 · verification（2026-10-12）

## V1 单测
`node --test tests/truncate.test.ts`：**11/11 全绿**（含 3 个真实缺陷回归用例：dist 基数防护 / 预算记账 / 收敛循环）

## V2 smoke
`npm run smoke:all`：**87 tests，86 pass + 1 skip，0 fail**

## V3 端点级（重启后 Python urllib 实测）
| 验收点 | 结果 |
|---|---|
| sentiment_trend 带 start/end | 200（5.3KB）——422 修复 |
| /tikhub/status | 200，含 daily_usage；非 200 时写 error 的盲区修复就位（本轮窗口恰好 200 未触发，代码路径 3 行） |

## V4 真实对话（两轮，经 /chat/stream 全链路）
**第一轮**（三靶点并测，63s，verdict=pass）：
- `search_cars`：100KB → **914 字符**（keyword=海豹 命中 9 条，含 total_matched=9 / total_library=1149 / _meta）
- `sentiment_trend`：4,955 字符正常返回（不再 422）
- `get_review_analysis`：38KB → 12,190 字符——**抓到 P0 缺陷**（预算不记账 → headTail 丢 JSON 结构），修复后复测 ↓

**第二轮**（修复后，36s，verdict=pass）：
- `get_review_analysis`：37.9KB → **19,488 字符、JSON 合法**、`_truncated.arrays=[{provinces 30→23},{stream.rows 10→3}]`、`full_output_path: true`
- 全部工具结果条目 ≤19,963 字符且 JSON 合法；旁路文件 2 个（37,958 / 25,979 字节）与被截工具一一对应
- **verdict=pass = 台账完整性经出口闸实战验证**（截断后 submit 的数字仍全部可溯源）

## V5 门禁
`node eval/runner.mjs --gate`：**E1-E9 9/9 全绿**（EXIT=0）
- 注：前两轮 0/9 为环境碰撞（并行会话两次重启网关 + eval_cross 批跑占池，网关日志 02:13:32/02:17:04 重启记录实锤），非代码问题——V4 的 verdict=pass 与第三轮 9/9 共同佐证

## 静态
- 根 tsc：11 条 = 历史基线，零新增（truncate.ts 一处 `string|undefined` 类型放宽已修）
- `py_compile main.py` ✓；extension tsx import ✓（simplify 清理后复验 11/11 + EXT_OK）

## 施工中抓到并修复的缺陷（全部有回归用例把守）
1. dist 无基数上限（高基数键自身膨胀超预算）→ top-20 降级
2. **预算不记账**（多数组独立放行、总和逃逸 → headTail 丢结构）→ 累计记账 + 收敛循环
3. 标量 JSON 的 spread 爆炸路径 → 对象守卫

## 追加：隔离审查轮修复后复验（2026-10-12）
- 隔离子代理审查（无锚定）：P0 零 / P1×2 / P2×9；红线三重核实成立
- 修复（P1-1 顶层数组丢 full_output_path / P1-2 单测进门禁 / P2-1 异常兜底 / P2-2 文件名碰撞）后复验：
  - `node --test tests/truncate.test.ts` 11/11（含顶层数组 bypassPath 回归）
  - 根 tsc 11 = 基线零新增
  - `npm run smoke:verify` **98 tests，0 fail**（truncate 套件已纳入清单）
  - 重启后真实对话 sentiment_posts（顶层数组）verdict=pass（当前数据 14.8K<帽未触发截断——数组形态注入路径由单测把守，对象形态端到端已实证）
