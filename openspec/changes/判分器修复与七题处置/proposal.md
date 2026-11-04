# proposal · 判分器修复与七题处置（G-2，伞计划收官 P1）

## WHY

1. **v1.2 真 badcase 7 题中 5.5 题经两跑对照实证为判分器假阴**（explore §一）——按"先查评测系统再动 agent"纪律，先修判分器再谈提示词；修复后 v1.3 基线（P2 repeat=3）才立在干净判分上。
2. **判分逻辑双源漂移已实锤**：runner 与 rescore.mjs 各自实现越界判定（后者 reasons 字符串逐字重放），同一行为两个分——必须单源化。
3. **今晨工作树有一批无归档半成品**（NEG_RE 扩词/否定豁免/elements/blind 重切，explore §三）——与本题同域，吸收进来补测试走完流程，不留悬空 diff。

## WHAT（八件，explore 已核落点）

| # | 交付 | 落点 | 量级 |
|---|---|---|---|
| 1 | 越界判定单源化：trap_check.mjs 导出 `checkOverreach(reply)` 纯函数（正则+NEG_RE 豁免同体），runner:340 与 rescore.mjs:55 改调；NEG_RE 补"不把…归因"形态 | trap_check/runner/rescore | ~25 行 |
| 2 | expect_gap 词表补"上一轮/分析记录/没有上一轮/确认对象/新对话"形态（multi-10 修复） | tasks.json multi-10 | 词表 |
| 3 | cross-09 锚重放核验（"SUV/广汽丰田"命中；若仍缺查归一化 bug） | 重放验证 | 0 行或修 bug |
| 4 | sales-07 摘 46.15% 派生比例锚（2047 保留，占比说明进 judge_rubric）+ scoring-rules pp 条目清理 | tasks.json + scoring-rules.json | ~4 行 |
| 5 | sentiment-06 摘 12.8% 锚（TTL 窗漂移系统性不稳，rubric 要素主导） | tasks.json | ~2 行 |
| 6 | multi-12 abort 残留修：网关 abort 成功后向会话注入中止标记（主案；pi 接口不支持则降级 SYSTEM.md 提示词一句并留痕） | pi_gateway.mjs 或 SYSTEM.md | ~20 行 |
| 7 | 吸收今晨半成品（§三六件）+ 每处红绿测试补齐 | eval/*.test.mjs | ≥10 例 |
| 8 | 离线重放全量验证：两份报告 73 题重放，六题按预期、其余零回归（忠实度铁闸模式）+ multi-12 E2E 实跑 | 新 eval/replay_check.mjs 或扩展 rescore | ~60 行 |

## 决策（授权模式下自主拍板，留痕待复审）

1. **摘锚而非扩容差**（sales-07 46.15% / sentiment-06 12.8%）：派生比例非记忆点，agent 给原始数即合格；窗口漂移不可容差。
2. **multi-12 主案网关标记注入**：执行层优先于提示词（红线#5 同精神）；pi 会话接口约束在 Step5 探明后落地，降级路径留痕。
3. **今晨半成品并入本 change**：同文件同测试域，拆分审查反而失焦；commit message 分项注明吸收清单。
4. **blind 口径维持**：判据校准史核验（explore §三）blind 12 题未参与回调，"从未参与调参"成立。
5. config-06"说明产品力'值'"概率性措辞不修提示词——复跑未再现，判分器修复后观察 repeat=3 中的发生率再定。

## 影响面

- 改：eval/{tasks.json,scoring-rules.json,trap_check.mjs+test,truth_check.mjs+test,rubric_check.mjs+test,runner.mjs,rescore.mjs}、prism-api/pi_gateway.mjs（或 SYSTEM.md）、新增重放验证脚本
- 不动：判分主干架构（verdict 优先链）、生产网关行为语义（multi-12 若走网关=abort 路径行为增强，生产同步受益且属正确行为）、快照、blind 12 题消耗
- 依赖：快照 snap-20261012-1222（E2E multi-12）；eval 栈（prism.py eval start）

## 验收

1. 红绿测试全绿（新增 ≥10 例：越界免责 3 形态/词表 4 形态/摘锚后无 truth 不崩/单源函数 runner+rescore 同分）；
2. 离线重放：rescored 报告六题 → 预期分（cross-02/config-06/sales-07/cross-09/multi-10/sentiment-06），其余 67 题零变化；15:23 复跑重放同口径零回归；
3. multi-12 E2E 实跑：t2 含 16,879 且无 E5/B10/MG4X 名称或数字 → ≥4 分；
4. smoke:verify 全绿 + prompt-gate 绿；
5. calibration_log 新增 2 条（sales-07/sentiment-06 摘锚）六字段齐全；
6. 今晨半成品全部入测试与归档说明。

## 不做边界

舆情 TTL 窗根治（窗口锚定库内 max(date)，愿望单另立）；越界措辞的提示词加固（等 repeat=3 发生率数据）；blind 消耗；快照轮换；题库新增（badcase 转题留 G-2 后续轮）。
