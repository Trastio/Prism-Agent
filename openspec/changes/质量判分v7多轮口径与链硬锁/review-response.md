# review-response · Step8 处置（审查：P0×0 / P1×1 / P2×8）

> 审查报告：审查报告.md（general-purpose 隔离审查，磁盘自读，不给施工结论）。
> 处置人：主会话。修 P1×1 + P2×3（①⑦⑧），记 P2×5（②③④⑤⑥，其中③④以注释澄清入码）。

## P1-1 后置只读不校验指纹 → **修**
- 采纳理由：与写路径"指纹变更清空 by_judge"（上轮 P1-1）不对偶——读路径只认槽键，v6 限流夜窗
  单模型链的槽键与 v7 资格槽逐字撞名时，--post 会把 v6 口径分打 v7 标签入库。
  现状 fail-closed 是运气（磁盘两 sidecar 恰不撞名）不是设计。
- 修法：collectScoredRowsFromSidecar 前置指纹闸——sidecar 缺失/指纹不匹配/槽缺失三态全部
  slotMissing=true + why 说明（CLI 层 exit 1 打印 why）。测试：撞名+过期指纹用例断言拒读与
  /指纹过期/ 理由；既有链键用例补指纹字段（指纹匹配前提下专测链键闸）。

## P2 处置

| # | 摘要 | 处置 |
|---|---|---|
| ① | BACKOFF_CAP_S=300 恒不可达（min(240,300) 恒 240） | **修**：阶梯补 300（[15,30,60,120,240,300]），末位=cap，稳态 300s 循环，与 proposal 封顶语义一致 |
| ② | 限流预算耗尽 null_reason 归粗桶 | **记**：粗桶只存在于当跑 console 输出（null 行不进 sidecar 缓存），预算耗尽本就有独立 [judge] 日志行可辨——事后取证靠日志不靠 sidecar，不改返回契约 |
| ③ | 解析重试新开预算窗口，单题最坏 ~2×行预算 | **记+注释澄清**：callJudgeOnce 头注明确"预算按传输调用计、judgeTask 解析重试另开窗"，语义仍是等待不降级，只收敛窗口口径不值改代码 |
| ④ | 预算检查在 sleep 后生效，墙钟可越界一个退避段 | **记+注释澄清**：越界上界 300s 有界无害（多等一段再判死） |
| ⑤ | --judge 缺值/--judge --post 解析边角 | **记**：pre-existing 解析行为且 fail-closed（探测不到候选即退出），不属本 change 引入 |
| ⑥ | 非 report JSON 晦涩崩溃 | **记**：pre-existing，不属本 change |
| ⑦ | 测试 env 恢复把 undefined key 写成 "undefined" 字符串 | **修**：setEnv 卫生helper（undefined→delete），硬锁测试恢复改用之 |
| ⑧ | "单轮模板=v6 不动"承诺无测试钉死 | **修**：归档测试补两行最强断言——现行 USER_TEMPLATE ≡ PROMPT_ARCHIVE.v6.user_template、JUDGE_SYSTEM_PROMPT ≡ v6.system（逐字） |

## 修复验证
- `node --test eval/quality_judge.test.mjs` → 29/29 全绿（指纹闸/模板钉死断言并入既有用例）。
- 施工报告六偏离项复核：全部认可（末轮行格式、{turns} 注入面≈0、只读槽键保守、last_run 恒 full、旧 ops 脚本兼容——均已留痕）。

## 工程小插曲（如实）
Step8 编辑中自造一坑：`const撞名`（const 后无空格直接中文）被词法分析吞成单个标识符——
中文是合法标识符字符，`const` 关键字被并进变量名，严格模式直接 ReferenceError。
教训：变量名别贴着关键字起，改 fpClash 后绿。
