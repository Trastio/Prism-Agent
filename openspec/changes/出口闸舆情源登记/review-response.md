# Review Response · Step7/8 自审（本轮无外部审查者）

## S6 simplify 自查

- /verify/claim 重构后 `_split`/`has_sent`/`has_core` 三变量换来条件开连接（G3），无冗余；`_check_sentiment_ref` 单函数承接六族引用，无重复分支。
- grounding.ts 只加一段前缀放行 + 4 个 NAME_FIELDS，无重排。
- extension 只改描述字符串（8 处）+ hook 守卫（1 处）+ makeSentimentTool 描述后缀（1 处）。
- 结论：无可再简化项。

## S7 自审发现与处置

| # | 发现 | 处置 |
|---|---|---|
| 1 | 无冒号/畸形 ref 不进 has_core/has_sent 分组，但表正则会拒（格式错误）——与旧行为一致 | 无需改 |
| 2 | core 分支理论不可达 conn=None（regex 强制冒号；有冒号且非 sentiment 表必进 _split → has_core=True 开连接） | 论证通过，未加防御性判空（加即死码） |
| 3 | dim LIKE 模式含字面双引号；维度名现实词表无引号 | 接受 |
| 4 | `_is_uuidish` 36字4杠粗判，极小概率把车系名当 uuid → raw_posts 查不到 → 拒 | fail-closed 方向安全，接受 |
| 5 | collectNameTruth 新增 4 字段被 smoke:grounding/smoke:verify 覆盖 | 55/55 实测无回归 |
| 6 | verify_claim_api.test.ts 依赖 better-sqlite3 + 舆情库路径（英文路径，避开中文路径坑） | 实测通过；PRISM_SENTIMENT_DB env 可覆盖 |

## E2E 暴露的已知限制（留下一轮，非本 change 缺陷）

- **R1-deep（普通词误报）**：conclusion_text 里"销量/口碑/配置/不到"等普通 CJK 词对上 2 字维度真值名（电耗），findClosest d<3 恒命中 → 出口闸同轮内多 1~3 次自纠提交。用户不可见（tool_result 循环非 UI），但费 token/时延。根因是 verifyNames 对散文逐词比对实体名的设计，需 token 分类器或阈值重设计（改阈值会破 8 case 中的蔚来Z9/一汽丰田GAC，不可轻动）。
- **标识符数字**：series_id 8660 在 resolve_series 之前提交会触发"不在真值集"（自纠）。v1.4 排除的是 identifier key 非 value，可留。
- E2E 第二轮曾现 sentiment 工具整批重调一次（模型自纠行为），无害。


---

# 补流程记录（2026-10-12，用户拍板"走大 change 标准补完流程"）

## 子代理补课结果（如实）

- 派出 2 个子代理（独立代码审查 + 独立验收）。**两者会话均无本地文件/命令工具**（仅网页类工具）：验收者如实报"0 PASS/0 FAIL 未完成"；审查者最终报告"未读到任何代码，拒绝编造发现"。
- **重要更正**：补课期间曾出现一份"1 P1 + 5 P2"的审查结果通知——经 grep 核验，其 P1 引用的 `ORDER BY cols[sort_by]` 代码在 main.py 中**不存在**，属无工具会话的虚构报告，**作废不采信**。教训：无工具会话产出的行号级报告必须先验证再采信（红线#1 精神同样适用于审查报告本身）。
- 结论：当前 harness 下子代理不具备本地审查能力 → **独立审查未达成，由主会话代行**（独立性受限已如实记录）。

## 主会话代行审查（逐项实证）

| 审查项 | 结论 | 证据 |
|---|---|---|
| verify_claim 双连接泄漏 | ✅ 无 | finally L889-893 条件关 conn+sent_conn，异常路径同覆 |
| SQL 注入（supported_by 自由文本） | ✅ 全参数绑定 | _sent_vehicle_exists/_check_sentiment_ref 均 ? 绑定+LIKE 转义+ESCAPE；注入探针 `风云T7'; DROP TABLE...` 实测无害（拒+库完好 25 行） |
| dim_esc 实际使用 | ✅ | f'%"{dim_esc}"%'（L871） |
| fail-closed 隔离 | ✅ | sent_unreachable 仅 sentiment 分支引用，core 分支无耦合（结构性隔离） |
| hook _meta 行为保持 | ✅ | isQueryTool 门控，query_* 路径与原逻辑逐行一致 |
| 前缀放行不放过 8 case | ✅ | 25/25（8 旧 + 6 新增） |

## 代行审查后的加固（已施工）

- grounding.test.ts +2 边界 case（token 恰等于真值 / 余部符号开头变体）
- package.json +engines node>=20（describe 顶层 await 依赖）

## 验收（主会话重跑验收者的 4 项矩阵）

smoke:all **57/57**（50 基线 + grounding 6 + verify_claim 1 suite）· /verify/claim 4 组手测全 PASS（舆情 5 格式过 / fail-closed 3 拒 / 三维度回归过 / 注入无害）· /health ok · 注入后库完整性抽查通过
