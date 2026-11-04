# 舆情工具层跟进 · 归档（2026-10-20，轻量十步走完 ✅）

## 一句话

舆情三连改（采集降本/前端收敛/缺陷簇闭环）后的工具层跟进：修复 16 台 paused 车（含银河E5/零跑D19）舆情查询误报"未收录"的红线#1 口径失真，新增 sentiment_defects 第 7 个舆情工具（缺陷话题簇=PM 高价值信号），出口闸登记新引用表。harness 主体（护栏/验证/出口闸协议）经核验不受影响，未动。

## 交付清单

1. **T1 两级解析**：resolveVehicleId（fleet-overview active 快路径 → Prism 侧新端点 /sentiment/vehicles-all 全量含 status）；paused 车照查+对象响应顶层注入 _prism_frozen_note 冻结声明；inactive/未收录 unavailable 文案区分；空串 fail-closed（P1-1 修）
2. **T2 sentiment_defects**：调 /defect-themes/{id}（生产版端点 10-20 闭环改造后统一 30 天权威窗+24h TTL+LLM 失败保旧，工具零特例通用路径）；KNOWN/TRUNCATABLE/tool_matrix/GATE_DESC/出口闸提示全链登记
3. **T3 trend 口径注记**：描述补 30 天保留线
4. **T4 出口闸源登记**：main.py _SENTIMENT_TABLES +sentiment_defects
5. 测试：sentiment_tools.test.ts（新，4 case）+ verify_claim_api +3 case + tool_call 断言 23；smoke:verify 挂载
6. E2E 验收脚本 e2e_check.py（两问+verdict 竞态兜底，UTC 窗口过滤）

## 关键裁决（3）

1. **fallback 数据源走 Prism 侧新端点而非改舆情**：舆情所有名单端点都筛 active（施工测试抓出，explore 漏核）——身份映射（车名→UUID+status）本就是 Prism 适配层职责，/sentiment/vehicles-all 只读直查舆情库与 /verify/claim 同模式；顺带纠正 proposal 初稿"零接触 prism-sentiment"的边界表述（该约束属于旧仓库 Agent项目/，prism-sentiment 已内化为 Prism 子服务）
2. **"工具传 30 天窗防 TTL 互踩"设计作废**：那是基于旧仓库代码（v1 explore 弯路）的结论——生产版端点 start/end 已完全退役、TTL 不比对窗，通用路径即正确。教训：跨项目对接面核验先确认生产目录是哪个
3. **paused 声明"对象顶层注入+数组跳过"而非整体包装**：collectNameTruth 按顶层字段收名称真值（grounding.ts:86），包装整个响应会藏掉锚点；数组端点（top-posts）数据自带日期自明，声明缺位记为已知限制

## 验证终态

smoke:all 全绿（verify 128/0/trap 31/0/rubric/truth/value_diff/prompt）；tsc 11=基线；活端点 26 台全量+T7 缺陷簇 TTL 命中 3 簇；E2E 两问双过闸（E5 冻结声明如实转述/T7 缺陷簇高质量交付+抖音 URL 溯源）；服务重启 8002+9200（带 PRISM_AUTO_APPROVE_UI=1），**eval 网关 9201 未动**（工具面隔离防快照上烧 LLM）

## 留下一轮

- P2-3 fuzzy 多候选静默选车（"风云"→T9）：有 resolve_series 前置防线兜底，独立小改候选（多候选→ask-user）
- P2-8 REF_RE 不含 sentiment_ 前缀（保底③提取面，改需独立验证）
- 评论极性三端点（comment-sentiment-*）未接：可选跟进
- eval 网关 9201 下次重启后工具面将带上 sentiment_defects——届时 eval 快照上 agent 若调用会在快照库重算+烧 GLM（TTL 过期必触发），放 defect 题前需先处理（如 PRISM_FAKE_TODAY 固定窗+预计算缓存行）
- 铂智3X paused：后续给 3X 补舆情侧预期须用冻结口径

## 面试三讲

1. **解决什么**：数据源收缩（车池 23→8）在消费侧留下静默失真——16 台停更车被工具误报"未收录"，违反"数据真实性"红线却不报错不崩，是最难发现的那类 bug。核验路径=从对接面（7 个端点）逐个对生产代码+生产库实测，发现两次"我以为"（旧仓库弯路/名单端点全筛 active），都被测试和实跑抓回。
2. **关键裁决与我的角色**：fallback 走 Prism 新端点而非改舆情源（身份映射是消费侧职责，数据源不该为消费侧需求扩 API）；隔离审查抓到空串静默选错车（includes('') 恒真）——这类边界我自己测不到，是"审查者不带设计者盲区"的又一次实证；首派子代理 NO-TOOLS 守卫零成本退出、重派命中，重试制流程按设计运转。
3. **面试官会追问**：为什么不直接让舆情端点返回全量？→ 舆情域的名单语义是"运营中的车"，Prism 的解析需求是"库内所有车+状态"——两个域的语义边界不同，把消费侧口径塞给数据源会造成接口为单一消费者腐化；paused 车"照查+声明"而不是拒答，因为冻结存量仍是可溯源数据，PM 需要的是"知道数据停在何时"，不是"没有数据"。
