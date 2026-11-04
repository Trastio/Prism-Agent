# self-check · 新能源车池采集（Step3.5）

对 proposal/tasks 逐层审查，8 个 Gap 全部收敛后进施工：

1. **月份窗口硬编码**：方案 §3.1 的 SQL 写死 2026/6-8月末。→ 收敛：生成器动态取库内最新 3 个月末批（`month LIKE '%月末'` 去重排序取 top3），滚动扫描时天然跟 CAM 更新走。
2. **绑定器出网依赖**：build_series_index/search_series 是汽车之家 API，单测不能出网。→ 收敛：单测用 mock；生成器加 `--skip-binding` 离线模式；绑定结果写进 nev_pool.json 作缓存，重跑只补未绑定项。
3. **环比断言的"上一次"从哪来**：→ 收敛：nev_pool.json 生成前自动转存 `.prev`，环比读 .prev；首次生成（无 .prev）跳过环比断言并在台账注明。
4. **cap 语义二义**：T3 的 cap 是"条数 300"不是"页数 15"。→ 收敛：参数名 max_reviews，实现按页粒度向上取整（20 条/页），不足一页停。
5. **补账误走重采**：recollect 是 delete+insert，直接对 5 个补账车系跑会删掉存量口碑再重插（打标反而被 CASCADE 清掉重打，风险无谓放大）。→ 收敛：补账=独立 tag-only 代码路径（复用 tagger，不 import recollect 的删除逻辑），且补账脚本启动校验目标车系口碑行数在批前后不变。
6. **metadata_map 来源**：collect_config_snapshots 的 --from-docs 路径吃 docs JSON；本 change 的 maker/energy/level 直接取 sales_trim（manufacturer/energy_type/level 字段），比别名表 _match_maker 猜测更准。→ 收敛：metadata_map 由生成器产出进 nev_pool.json，T2 直接消费。
7. **T6 存量零扰动的对账口径**：→ 收敛：T0 台账记录"逐系行数（count>0 的全部车系）"，T6 全量比对而非只比对 22 分析池。
8. **子代理派单防线**：→ 收敛：fork 型子代理任务单第 0 步=自报工具清单，无 Bash+Read 立即报 NO-TOOLS 退出（主会话重派）；交付双保险=报告落盘本目录 + 返回文本摘要（fork 会话无 SubagentHandback）。

结论：spec 层无悬空依赖，可进 Step5。
