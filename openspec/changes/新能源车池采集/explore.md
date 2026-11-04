# explore · 新能源车池采集

日期：2026-10-16 · 上游方案：`设计图总览/Prism-Agent-新能源车池扩容方案-v1.md`
范围：仅采集侧（名单生成+ID绑定 / 底座批 / 深采批 / 打标补账）。看板分级徽标、月度滚动扫描**不在本 change**。

## 1. 现成资产核验（读码结论）

| 资产 | 能力 | 直接可用性 |
|---|---|---|
| `scripts/collect_config_snapshots.py` | `collect_snapshots(series_ids=[...], fetch_func, max_age_days)` 可导入、显式传名单；fetched_at 断点续采；delay+concurrency 限速 | ✅ 直接复用 |
| 同上 `--from-docs` 路径 | 新系首采需 maker/energy/level metadata_map（源是 docs 扫描 JSON） | 🔧 需自建 metadata_map（从 sales_trim 取 maker/energy/level，替代 docs JSON） |
| `scripts/recollect_koubei_with_full.py` | `recollect_all(series_ids=[...])` 显式传车系；口碑翻页+详情页原文（best/worst_full_text）+内联打标（src/nlp/tagger.py get_tagger） | ✅ 复用 |
| 同上 **缺口** | **无单车上限**：while True 翻到 pagecount 为止——汉EV 源站 1.2 万条会采 600 页，"300 条/车系"目标无法达成 | 🔧 **必改**：加 --max-pages / max_reviews 参数（新 diff 代码） |
| 同上 **行为注意** | 每车系 **delete+insert**（先删旧 owner_reviews，CASCADE 删 review_tags 再插新） | ⚠️ 只允许用于深采批新车系（本地 ≤100 条）；**禁跑在 22 个存量分析池车系上** |
| ID 绑定数据源 | `autohome_api.build_series_index()`（按字母全量索引）+ `search_series(keyword)` | ✅ 绑定器数据源 |

## 2. 请求量修正（方案 §5.2 的 1,150 页是低估）

每条口碑除列表页外还要抓 1 次详情页（best_full_text 来源）。深采批 77 车系 × 300 条：
**77 × (15 页列表 + 300 详情) ≈ 2.4 万请求**。限速下 ≈ 7~13 小时 → 深采批按**两晚**排（月销>1万 27 个一晚，3000~1万 50 个一晚），第一批先试跑 3 车系实测耗时再定并发参数。

## 3. 生产库写入风险（T3 事故前置约束）

1. **T0 备份**：批跑前 sqlite backup API 全量快照 + 基线行数记录（owner_reviews/review_tags/series_summaries/config_snapshots 四表），无备份不得开跑；
2. 深采 delete+insert 范围硬约束：脚本只接受显式 series_ids，且启动时校验名单与"存量分析池 22 车系"交集为空，交集非空 fail-closed；
3. dry-run 模式默认开（只打印将采名单与预估量），PRISM_COLLECT_LIVE=1 才真采——沿用舆情 cleanup 的 env 门控形态；
4. 断点续跑：逐车系落 progress（车系粒度幂等，重跑只补未完成车系）；
5. 失败语义：单车系失败记 exceptions 清单继续跑，不中断整批；采不满 cap 数如实记录（方案 §5.4）。

## 4. 名单与绑定（红线#6）

- 生成器从 sales_trim 程序化产出 289 池（deep 77 / long-tail 190 + tail 边界 3000），带**能源构成断言**（三类>0 且合计=盘子）+**盘子数环比断言**（对上次生成件，差值>±10% 拦截）；
- ID 绑定：build_series_index 精确名匹配优先 → search_series 兜底 → 歧义/绑不上进 manual_review 清单 fail-closed；绑定件落 `nev_pool.json`（含 sales名/series_id/绑定方式/tier/metadata）；
- 共壳陷阱复验：绑定后按 series_id 反查 owner_reviews/series_summaries，同一 series_id 出现在多个 sales 名下 → 人工复核（秦PLUS DM-i/EV 案例）。

## 5. 打标补账（5 车系）

补账=只补 review_tags，**不走 delete+insert 重采**。tag-only 路径：get_tagger 直接对存量未打标口碑跑（recollect 脚本内联逻辑的抽取复用），完成度 = 打标覆盖 ≥70%。

## 6. 验收锚点（继承方案 §9）

绑定率（深采批 100% 精确绑定或例外在案）/ 抽查 5 新车系看板数字与库一致 / as_of / pytest+smoke 绿 / 补账 5 车系 ≥70% / 备份与基线在案。
