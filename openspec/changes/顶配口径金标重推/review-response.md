# review-response · 顶配口径金标重推 Step8 处置（对 审查报告.md 的 0P0/0P1/5P2）

| 项 | 处置 | 落点 |
|---|---|---|
| P2-1 multi-08 禁词收窄残留 | **修** | text_forbid 追加 明显虚标/涉嫌虚标/数据虚标/是虚标（审查实测 0 命中的裸断言变形）；红绿：4 形态命中+既有断言形态仍拦 |
| P2-2 lookbehind 不对称 | **修** | cross-05/06 forbid[0] 补 并非/不是 豁免、forbid[1] 补 不是（整体重写两条正则源，fromCharCode 构造绕开 shell 转义链——字符串手术两次被 \n 转义咬，教训入档）；红绿 7 形态（3 豁免 ✓ + 3 真越界 ✓ + 维度边界 ✓） |
| P2-3 空断言死代码 | **修** | 删恒真行（`=== false \|\| true`），注释留痕 |
| P2-4 cross-01 rubric 文本陈旧 | **修** | judge_rubric 改"配置 2024/2026 全系无侧窗隔音、2027 仅中高配前排（库真值 SQL 坐实）"——LLM judge 层输入对齐 |
| P2-5 sales-05 金标源分叉 | **记（入档）** | 本 change 归档条目声明：tasks.json 已摘 76.8% 派生锚，eval/gold/user-20261013.json 原文保留（人工金标历史件不改写，分叉以 calibration_log 为准绳）——同 sales-07 先例 |

验证：truth 20/20 + rubric/replay 47/47 绿；replay v13 报告 diff 稳定 8 行向上（P2 修复零意外变化）；55 基建行按 P2-2（G-2 修）跳过单列。

**附带教训**：跨 bash/JS 的正则字符串手术不可靠（`\\n` 转义两次被吃出现真实换行入字符类）——批量 JSON 正则改写应走临时脚本文件+fromCharCode 构造，改后必须红绿自测。
