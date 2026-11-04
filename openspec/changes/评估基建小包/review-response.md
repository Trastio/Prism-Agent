# Step7 隔离审查处置记录（评估基建小包 · 2026-10-15）

> 审查者：eval-infra-review 子代理（代码磁盘提取内嵌，无设计自评）｜ 结论：P0=0 / P1=4 / P2=7
> 处置：修 8 / 裁决 1 / 记录 2 ｜ 修后 node --test 16/16 绿；离线重渲染样张对账一致（60题/54满分/6低分逐题吻合）

## P1 处置

| # | 发现 | 处置 |
|---|---|---|
| P1-1 | deriveBoundary 构成可能失真（--set 过滤下 total≠实际行数；conditionalSkipped 元素结构疑虑） | **修**：构成改 results 行驱动（deriveBoundary 加 rows 参数，runner 传 results，离线渲染同源）；元素结构疑虑经主会话核实**不成立**（runner:501/506 确为 `{task,...}` 对象）。补测 rows 驱动+回退两分支 |
| P1-2 | render_report tasks.json 加载失败静默降级（set 列空/恢复表消失零警告） | **修**：catch 出 warn + s3 note 如实标注"tasks 未加载" |
| P1-3 | aggregateDecay 非末轮分支（t<n，本包核心新逻辑）零测试 | **修**：补双轮 fixture 测（t1 命中/缺锚、t2 终轮 truth 分支全断言） |
| P1-4 | _calibration_policy 新顶层键在严格白名单解析下 P0 级 | **裁决降级**：主会话核实 truth_check.mjs 按键取值无键白名单（宽松解析）；该键随 Step9 smoke 实跑确认（批跑收尾会真实读写该文件） |

## P2 处置

| # | 发现 | 处置 |
|---|---|---|
| P2-1 | perTurnTruth 缺 turn → Math.min 产 NaN | **修**：filter 加 Number.isInteger(t?.turn) 守卫 + 补测 |
| P2-2 | 越界按行计入每轮 / repeat 同题重复计 | **记录为注记**：s2 note 声明口径（题数=行数、越界按行计）——不改结构，多轮题入库后如需按题去重再议 |
| P2-3 | timeout+score0 误归"附和" | **修**：timeout 先行返回"未完成（基础设施）"+ 补测 |
| P2-4 | calibration_log 第 1 条日期事实性（容差表是 10-13 B3 设计决策非 10-14 校准事件） | **修**：date 改 2026-10-13，change 标注"（B3 设计决策，回填记录非校准事件）"；后三条与史实吻合确认 |
| P2-5 | manifest 存绝对路径跨机不可复算 | **修**：artifacts 记 rel 相对路径（runner/render_report 两侧） |
| P2-6 | render_xlsx gbk errors=ignore 对 emoji 列宽低估 | **记录不修**（列宽仅观感；待真实产物出现乱窄列再修） |
| P2-7 | 零回归实证缺位（单测只测派生层） | **并入 Step9**：离线渲染对账已过（本次修复后重跑，60/54/6 一致）；判分零回归由 Step9 smoke + 60 题 dry-run 收口 |

## 教训沉淀

审查包内嵌代码与磁盘原文的微小差异导致一次 Edit 未命中（s2/s3 段）——再次坐实"审查/修复前以磁盘原文为准，上下文记忆的代码不可直接当 Edit 底稿"。
