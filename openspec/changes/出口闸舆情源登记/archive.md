# Archive · 出口闸舆情源登记（2026-10-11 归档）

## 一句话

出口闸 supported_by 源注册表补齐舆情族（sentiment_* 七种引用格式，/verify/claim 直读 vehicle_sentiment.db 只读校验），带数字的舆情结论从"必拒→必保底重试"变为"首查过闸"；附带 verifyNames 前缀放行（风云→风云T7）、名称真值采集扩至 resolve_series+sentiment_*（G1）、舆情工具身份引导、前端重试文案去故障感。

## 变更清单

- `prism-api/main.py`：SENTIMENT_DB 常量 + _is_uuidish + _sent_vehicle_exists + _check_sentiment_ref + verify_claim 重构（条件开连接 G3，sentiment 库不可达仅拒 sentiment_* 引用）
- `.pi/extensions/prism-guardrails/index.ts`：6 舆情工具描述（引用格式+身份引导）、submit_conclusion 描述与拒绝提示补舆情格式、tool_result 名称真值采集范围扩展（G1，_meta 校验仍仅 query_*）
- `src/verify/grounding.ts`：verifyNames 纯 CJK 前缀放行；collectNameTruth NAME_FIELDS +4（canonical_name/dim/event_tag/platform）
- `src/verify/grounding.test.ts`：+4 case（23/23）
- `tests/verify_claim_api.test.ts`：新建（活服务 5 断言）
- `package.json`：smoke:verify 挂入新测试（50→55）
- `prism-web/src/components/ChatView.tsx`：重试轮免责文案

## 关键设计事实（勿重复推导）

- 舆情维度引用必须用**库源原始维度名**（续航里程/价格/性价比/智能化/车机），缩写"续航"拒——红线#6，E2E 实证
- dim_sentiment JSON 键是 ABSA 原始词表，非看板展示名
- sentiment_posts/events 参数双形态：uuid 精确查行；车系名查 vehicles 存在（对齐工具自身参数语义）
- 舆情轮名称真值锚点 = canonical_name（resolve_series）+ dim/event_tag/platform（sentiment 结果）——此前只采 query_* 导致首轮无锚

## 验收

smoke:all 55/55 · tsc 零新增 · 两轮 E2E 过闸零保底（第二轮 resolve_series 前置）· fail-closed 双向验证（假 uuid 拒 / 转写维度拒）

## 留下一轮

- R1-deep：verifyNames 散文普通词误报（销量/口碑 vs 2 字维度名，d<3 恒命中）→ 同轮自纠 1~3 次，用户不可见但耗 token；修阈值会破 8 case 张冠李戴检测，需 token 分类器方案
- E2E 会话目录 e2e_sentrail_*/e2e_sent2_* 可清理
- 舆情工具结果 as_of 随行声明（现靠模型自填日期）——sentiment 工具 envelope 无 _meta，后续可补


## 2026-10-12 补流程（大 change 标准）

- Step5 独立验收 + Step7 独立审查：子代理无本地工具均告失败；曾出现的"1P1+5P2"审查通知经核验为虚构（引用代码不存在）作废 → 主会话代行审查（独立性受限）+ 代行验收，全部实证记录在 review-response.md 补流程记录节
- 加固：grounding 边界 case +2、engines 声明；smoke 终值 **57/57**
- **流程教训（入记忆）**：①派审查类子代理前先确认其工具面含 Read/Bash，否则空转；②无工具会话的行号级报告必须 grep 验证再采信；③tasks 勾选必须事后勾
