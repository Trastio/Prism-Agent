# tasks · 新能源车池采集

十步映射：Step1 explore✅ → Step2 proposal✅ → Step3 本件 → Step3.5 self-check✅ → **Step5 施工 T1-T5** → Step6 simplify → Step7 隔离审查（子代理）→ Step8 review-response → Step9 verification → Step10 archive。

## T0 安全前置（主会话运维件，施工前必须完成）

- [ ] sqlite backup API 全量快照 → `prism-dashboards/data/backups/autohome-pre-nevpool-<ts>.db`
- [ ] 四表基线行数 + 存量有口碑车系逐系行数台账 → 本目录 `t0-backup-baseline.md`
- 验收：台账在案、快照文件可打开 count 一致

## T1 名单生成器 + ID 绑定器（fork 子代理施工）

- [ ] `prism-dashboards/scripts/gen_nev_pool.py`：从 sales_trim 程序化生成 289 池（窗口=库内最新 3 个月末批，**不得硬编码年月**；过滤条件=方案 §3.1）
- [ ] 双断言：能源构成（纯电/插混/增程三类 >0 且合计=盘子数）+ 盘子环比（读上一份 nev_pool.json，|Δ|>10% 拦截，--force 豁免留痕）
- [ ] ID 绑定：build_series_index 精确名 → search_series 兜底 → 歧义/失败进 manual_review 清单（**禁止子串静默绑定**）；绑定后共壳检测（一 series_id 对多 sales 名 → 人工复核清单）
- [ ] `--skip-binding` 离线模式（不出网只出名单）；绑定结果缓存避免重复打 API
- [ ] 产出 `prism-dashboards/data/nev_pool.json`（生成前旧文件转 .prev）：sales名/series_id/绑定方式/tier(deep|longtail|existing)/metadata(maker/energy_type/level，取自 sales_trim)/源站口碑量
- [ ] 单测 `prism-dashboards/tests/test_gen_nev_pool.py`（过滤/断言/绑定逻辑，fixture 库，不出网）
- 验收：断言通过；nev_pool.json 生成；deep=77±、longtail=190±（对方案 §附A 快照）；异常名单=manual_review 清单在案

## T2 底座批：壳+配置（子代理施工+执行）

- [ ] 289 车系缺失项补齐：壳 get_series_summary → series_summaries；配置 collect_snapshots(series_ids=缺失名单, metadata_map←sales_trim 的 manufacturer/energy_type/level)
- [ ] PRISM_COLLECT_LIVE 门控 + dry-run 默认（打印将采清单与预估）；逐车系 progress/断点续跑；失败进例外清单不中断
- 验收：289 壳+配置齐（缺项=例外清单在案）；config_snapshots fetched_at 更新

## T3 深采改造 + 3 车系试跑（子代理施工）

- [ ] recollect_koubei_with_full.py 加单车系 cap（max_reviews，页粒度向上取整）+ `--series-ids` 名单文件入参
- [ ] 启动守卫：名单与存量分析池 22 车系交集校验，非空 fail-closed；delete+insert 仅作用于名单内车系
- [ ] PRISM_COLLECT_LIVE 门控（默认 dry-run 打印预估请求量）
- [ ] 试跑 3 车系（建议：铂智3X/深蓝S05 纯电/零跑 C10 纯电——已有壳与配置、源站量 300+）实测耗时/请求量/打标质量，报告落本目录
- 验收：试跑车系口碑= min(300,可得)、打标覆盖 ≥70%、数字可复算；耗时实测写入 T4 排程

## T4 深采批全量（两晚，按试跑参数执行）

- [ ] 第一晚：月销>1万 27 车系；第二晚：3000-1万 50 车系
- [ ] 逐车系 progress + 例外清单；缺口（可得<300）如实记录
- 验收：77 车系口碑=min(300,可得) 或缺口声明；打标 ≥70% 者进分析池口径

## T5 打标补账（子代理施工+执行）

- [ ] tag-only 路径（get_tagger 对存量未打标口碑补跑，**不走重采不删数据**）：元UP/海狮05 EV/海狮06 DM-i/海狮06 EV/风云T11 CEM
- 验收：5 车系打标覆盖 ≥70%；owner_reviews 行数前后不变（对 T0 台账）

## T6 验收（主会话）

- [ ] 抽查 5 个新深采车系：三看板数字与库可复算一致 + as_of 逐系正确
- [ ] 存量 22 车系行数与 T0 台账一致（零扰动证明）
- [ ] 绑定率台账 + 例外清单归档；pytest + smoke 全绿；E2E：任一新深采车系 resolve→query→结论→submit_conclusion 过闸

## Step6-10

- [ ] Step6 simplify（子代理代码回看）→ [ ] Step7 隔离审查（fork 子代理，不给设计结论，实证复现）→ [ ] Step8 review-response → [ ] Step9 verification → [ ] Step10 archive
