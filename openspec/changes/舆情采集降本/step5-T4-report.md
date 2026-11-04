# Step5 · T4 施工报告（评论极性直出 · 双轨）

> 子代理：t4-polarity（fork 型）· 日期：2026-10-16 · 依据 design.md D4 + 空极性口径补丁
> 红线遵守：未 git commit、未重启服务、未跑真实模型（全 mock）、零付费 API、生产库仅 ALTER 加列（幂等迁移）
> ⚠️ 验证状态：新增 19 测全绿；4 个既有 run_comment_analysis 测试对齐后全绿；**全量套件+生产库加列在后台执行中，结果见文末补记**

## 一、改动清单（源码 6 文件）

| 文件 | 改动 |
|---|---|
| models/schemas.py:246-251 | `PostComment.comment_polarity Text` 新列（注释含双轨语义与 "none" 哨兵说明） |
| models/database.py:165-172 | 迁移 **v19**（check_column 幂等 + ALTER TABLE post_comments ADD COLUMN comment_polarity TEXT），照 v18 写法 |
| pipeline/analysis/local_absa.py | ① `POLARITY_SYSTEM_PROMPT`（只判 1/0/-1，/no_think）② `parse_polarity_output()`——think 块剥离+取首个合法词元，**不可解析返回 None（不伪造中性）** ③ `predict_batch/predict_single/_generate_batch` 增 `polarity=False` 参数：prompt/解析分轨；极性模式 max_new_tokens 48→8；**未加载时极性模式返回 [None]*n**（不写库防伪中性——维度模式保持 #22 neutral 占位不变） |
| pipeline/collectors/post_utils.py:210-243 | `derive_comment_sentiment(dim_sentiment, comment_polarity=None)` 双轨：极性列有效（"1"/"0"/"-1"）直接映射；否则老逻辑维度均值推导（`_derive_overall_sentiment` 阈值路径原样） |
| pipeline/analysis/batch_runner.py:392-470 | `run_comment_analysis` 双轨：队列改 **comment_polarity 与 dim_sentiment 两列皆空才入选**（老评论永不重标）；极性模式（env `COMMENT_POLARITY_DIRECT` **默认开**，调用时读取——T3 教训）写 comment_polarity、**不写 dim**；解析失败/空内容写哨兵 **"none"**（对齐维度模式 "{}" 的已处理语义，防队列死循环）；env 关=回退既有维度逻辑 |
| api/routes/dashboard.py:508-535, 550-585 | overview/trend 两端点 select 加 comment_polarity；循环内极性轨优先（`derive(dim_json, polarity)` 单点保持）、两列皆空（含哨兵）→ unanalyzed/跳过（§9.3 口径延续） |

## 二、测试

- **新增 `tests/test_t4_polarity_direct.py`（19 用例全绿）**：parse_polarity_output 11 参数化（三值/整句/think 块/垃圾/空/+1 非法）；derive 双轨（极性优先覆盖 dim/非法回退/两皆空 neutral）；run_comment_analysis 极性模式（直出不写 dim/哨兵/老评论不重标/env 关回退维度）；迁移 v19 幂等（跑两遍）；overview 端点双轨计数（极性轨+老 dim 轨+unanalyzed 混合）
- **既有 4 测试对齐**（test_batch_runner.py 的 loops_until_empty/handles_empty_content/stops_on_error/does_not_block_event_loop）：它们断言的是**结构行为**（循环清零/哨兵/出错保留/线程池），造数走维度语义——钉 `COMMENT_POLARITY_DIRECT=0` 走回退轨（回滚路径顺带获得覆盖），极性轨由新测试覆盖。对齐后 57 相关测全绿
- 消费方 grep 证据：`derive_comment_sentiment` 调用面=dashboard.py:526/:574 两端点 + 测试；**无绕行直读 dim 的消费方**

## 三、偏差与决策记录

1. **"两皆空返回 None"未照字面执行**：NULL→neutral 是 2026-10-03 spec 钉过的既有口径（docs/superpowers/specs/2026-10-03-comment-absa-full-loop-design.md:27"NULL→neutral 语义保留"），test_analyzer_caliber.py 亦有断言。"跳过未打标"由端点层 unanalyzed 检查承担（两列皆空即不计入）——函数保持字符串契约，docstring 写明。**与设计文本冲突，按"不擅改设计"记录留主会话裁决**（推荐接受本落法）
2. **diff 端点（comment_sentiment_diff :1020）与翻车帖链不吃 derive**：其 `comment_sentiment` 来自 GLM comment_summary 的 `genuine_sentiment`（:1071），与本地 ABSA 完全两条链——设计 §4.3 陷阱 4"翻车帖过滤直接吃 derive"的前提**部分不成立**（app.js:316-322 吃的是 diff 端点输出）。后果：极性切换**不触碰翻车帖链**（减风险）；原计划的"翻车帖判定回归"在本 change 无对应改动面，T6 验收保留一条烟囱测试即可
3. **极性模式默认开**（`COMMENT_POLARITY_DIRECT` 缺省 "1"）：设计意图"切换后新评论全走直出"；env 关=一键回退。若 T6 想显式控制切换时刻，可在恢复日更前关、验收后开
4. **哨兵值选 "none"** 而非 ""（空串会被队列条件 `== ""` 永选）——与维度模式 "{}" 同位的已处理标记，derive 对其回退 dim 轨

## 四、遗留（移交 T6/T7）

- 口径 stamp：切换日=首次夜跑极性模式之日（方案 R43 已载机制，T6 落 CHANGELOG）
- T6 验收补：翻车帖烟囱测试（确认 genuine_sentiment 链不受影响）
- 若主会话裁决偏差 1 不接受（坚持 None 契约）：需同步改两端点+测试，影响面=本函数+2 端点

## 五、验证补记（终值）

- **全量 pytest：902 passed / 1 failed**——唯一失败 `test_cache_bust` 为 T1 报告已证的存量失败，与本 change 无关（本轮新增 19 测 + 对齐 4 测全绿）
- **生产库加列 ✅**：`comment_polarity` 列已存在（迁移台账 schema_migrations 最高 v19）；**老数据零污染**——非空 comment_polarity 行数 = 0；dim_sentiment 有值 73,284 行原样未动
- 插曲（记录）：init_db 异步加列进程两次疑似卡死（模块级 engine + 互等锁疑云），被清理后核验发现**首链其实已成功执行完毕**（台账为证）——最终验证以上述直查为准。教训同 T3："验证输出被截断 ≠ 执行失败，查台账/列存在等落地产物再下结论"
