# proposal-mini · 质量层 LLM 评审（G-5，伞计划收官 P4）

> mini-proposal（授权模式）：设计拍板件，拍板后走轻量施工。依据=教材 trajectory-verifier 三层（质量层 LLM + confidence<0.75 不进学习信号）+ 读书映射 §4.4（异源评判+防长度偏差）+ 教材笔记"评估用 LLM-judge 但判分器需验证"。

## WHY

判分器现只有结果层+过程层（代码判定），**质量维度（"答案好不好"）是盲区**：锚点全中但写成表格墙/没回答 PM 真正问的/语气敷衍——机器照打 5 分。现由人工 annotate.mjs 顶替，不可规模化。

## 设计要点

1. **载体**：`eval/quality_judge.mjs`——后置重放式（读既有报告 reply_full 判质量，零 agent 重跑，与 replay_check 同模式）。对 P2 报告即可直接跑一轮。
2. **裁判异源**：agent=DeepSeek → 裁判=GLM（智谱）或 Kimi；**前置依赖：GLM/Kimi 的 API key**（用户现用 GLM 跑 Claude Code，但程序化 API key 是否在手待确认——这是本件唯一外部依赖）。
3. **rubric 六维**（每维 0-2 分，总分 12 映射 0-5）：直接回答了用户问题 / 结构与可读性 / 口径与 caveats 叙述质量 / **冗长度（显式惩罚，防长度偏差）** / 专业语气（PM 职业语言，无内部术语泄漏）/ 可操作性（结论可被 PM 直接采用）。
4. **防病三件**：①judge prompt 固定版本+指纹入报告（同 prompt_files_hash 范式）；②confidence<0.75 或维度间自相矛盾 → 该题质量分弃用（null 不计均值）；③红绿校准集——人工挑 8 题（4 好 4 坏）钉住：judge 分与人工排序 Spearman≥0.7 才准用，否则调 rubric 不准上线。
5. **不进及格线**：质量分为独立观测维度（langfuse 第三 score 名 `quality-score`，挂同 traceId），不并入主判分——LLM 裁判噪声不得污染红线判分（教材同款纪律）。

## 验收

1. 校准集 8 题 Spearman≥0.7（红绿报告留档）；
2. 对 v1.3 报告全量跑通，质量分入 langfuse（environment=eval）；
3. 低质量高主分的题清单（"对但不好"候选）≥可读产出；
4. runner 主链零改动（后置脚本形态）。

## 成本

GLM-4.7-flash 级：219 条回复×~1.5K token 输入 ≈ 0.4M tokens/轮 ≈ ¥1-3。可反复跑。

## 不做边界

不替代主判分；不做裁判微调；多裁判共识（GLM+Kimi 双评）留二期（先单裁判+校准集）。
