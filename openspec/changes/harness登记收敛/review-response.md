# review-response · harness 登记收敛（Step8）

- 审查：2026-10-13 隔离子代理（代码内嵌法）。报告：**0 P0 + 2 P1 + 7 P2**。

## 处置总表

| 编号 | 发现 | 核实 | 处置 |
|---|---|---|---|
| P1-1 | _truth 分支剥离后仍整包 generic walk，total/page/elapsed_ms 等响应元数据以 kind='truth' 入账，与 harvestTruth 选择性收割自相矛盾（实质放宽出口闸） | 成立（且 harvestTruth 未收 diff 段金额，config_adv 引用会误拒） | ✅ 修：harvestTruth 增加 diff 段收割（columns.amount/items.amount/config_adv/flat_adv）；_truth 分支删除 genericVals 整包 walk；单测×2 |
| P1-2 | LEADING_NUM 只取首段：区间价"11.98-14.98万"丢右端（误拒真引用）、千分位"1,234"断章成"1"（错数入账） | 成立 | ✅ 修：pushNum 去逗号 + matchAll 全数值段；单测 |
| P2-1 | res.json() 未包 try → 200+非JSON 以异常收场 | **不成立**：execute 全体在 try/catch 内，json 抛出落外层 catch 返回同款 unavailable 信封（审查者未见 try 开头） | 📝 裁决不成立 |
| P2-2 | resolve 喂源对空 series_key 无守卫 | 成立（防御性） | ✅ 修：skResolved 非空守卫 |
| P2-3 | selfCheckReported 只在 drift 非空置位 → 每轮重扫 | **不成立**：:1046 已无条件置位（审查者所见摘录缺该行——摘录责任在主会话） | 📝 裁决不成立 |
| P2-4 | 真值发射方 ⊆ business 无自检（新工具忘进 business 集→两闸全盲） | 成立（结构性） | ✅ 修：truthEmitters 集合 + collectRegistrationDrift 第五参；单测 |
| P2-5 | load_skill 描述注册时求值 vs 自检现算，目录中途变更两处口径分裂 | 成立但部署态目录静态，dev-only | 📝 记录不修 |
| P2-6 | 过滤前缀 '[完成验证器' 偏宽，用户粘贴通知原文时气泡被吞 | 成立（纯 UI 边缘） | 📝 记录不修（收紧含 ']' 会撞 M2 前缀断裂老账） |
| P2-7 | 截断前全量 JSON 往返放大 | 成立但服务端响应有界、既有形态（M1 同款） | 📝 记录不修 |

## 修复后验证

- smoke:verify **107 pass / 0 fail**（104+3 新回归：diff 收割/区间千分位/发射方漂移）；smoke:guard 15/0；tsc 零新增
- 网关重启后金额题 E2E：9 次工具调用、compare 1 次成功、正文零内部名、金额齐全（"风云T7 便宜 1.19 万、配置还多值 4,260 元，拉平后领先约 1.62 万"）

## 教训

①给隔离审查者的代码摘录要含完整 try 边界——两处"裁决不成立"都是摘录截断造成的误报（审查者按所给代码推导没错，错在摘录不全）；②收割函数的"选择性"与既有"整包兜底"同文件并存时，审查者抓到的自相矛盾是真问题——设计时该在注释里写明谁覆盖谁。
