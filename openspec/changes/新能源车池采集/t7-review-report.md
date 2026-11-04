# T7 隔离审查报告 · change「新能源车池采集」

- 审查人：Step7 隔离审查子代理（未读任何 change 设计文档，仅对代码实证）
- 日期：2026-10-18
- 测试：`python -m pytest tests/ -q`（工作目录 prism-dashboards）→ **183 passed in 1.32s**
- 生产库 data/autohome.db 全程只读，未设 PRISM_COLLECT_LIVE，未跑真实采集
- 实证数据：data/nev_pool.json（universe=289，deep=71，其中 **8 个 series_id 各出现 2 次**：8171/5964/7578/7588/7864/7674/8176/8459，均为共壳双 sales 名双双 tier=deep）；nev_pool_rulings.json 无任何程序消费方（全库 grep 证实）

## 结论

**P0：无。P1：4 项。P2：14 项。**

---

## P1（4 项）

### P1-1 deep 名单含 8 个重复 series_id，采集管线不去重 → 单轮双跑 + 进度覆盖可致终态劣化
- 位置：`prism-dashboards/scripts/recollect_koubei_with_full.py:126-155`（`load_pool_series_ids` 原样返回不去重）、`:499-501`（`pending` 推导不去重）、`:453-454`（`done_map` 仅启动时快照一次）
- 问题：nev_pool.json 的 deep 层有 8 个共壳 sid 各出现 2 次（如 5964 = 秦PLUS DM-i + 秦PLUS EV 双双 tier=deep）。live 单轮内每个重复 sid 全流程跑两遍：列表页 + 逐条详情页 + LLM 打标全部双倍（cap=300 时约 8×300≈2400 次多余请求/打标调用）。更糟：循环中途 `append_progress` 不回写内存 `done_map`，第二遍照跑；若第二遍遇限流截断（只采到 20 条），delete+insert 覆盖第一遍的 300 条，progress last-write-wins 记 done collected=20 → 终态数据反而比第一遍差。dry-run 的 `estimate_requests`/`total_requests` 同样重复计数（预估虚高）。
- 实证：`python` 读 data/nev_pool.json 统计 deep 层 Counter（见上 8 个 sid）；读源码确认无任何去重点。
- 修法：`load_pool_series_ids` 保序去重一行即可（或在 `recollect_all` 入口去重）。

### P1-2 delete+insert 非原子：插入批任一行失败 → 该车系口碑被清零且重跑反复清零
- 位置：`scripts/recollect_koubei_with_full.py:346-347`（delete 后立即 `s.commit()`）、`:398-400`（逐条 add 后第二次 `s.commit()`）；`src/storage/db.py:148-158`（session_scope 异常只回滚当前事务）
- 问题：删除已独立提交；其后插入若遇 IntegrityError（review_id 是**全局**主键，跨 model_id 撞车即触发——本次的同页去重只防了同批内一种成因；或 NOT NULL 等），整批插入回滚而删除不可逆 → 车系清零。except 记 failed，重跑（failed 不在跳过名单）先删 0 行再撞同一毒行，车系持续为 0，仅 T0 备份可恢复。本 change 红线是"删掉不该删的"，这里是"删了之后补不回去"。
- 实证：代码结构 + session_scope 语义；未跑真实删除（生产库只读纪律）。

### P1-3 fetch_koubei_page 失败形态与自然尽头不可区分：限流一次 → "empty/done" 终态永久跳过
- 位置：`scripts/recollect_koubei_with_full.py:295-296`（`if not data: break`）、`:520-527`（空结果记 status="empty" 终态）、`:499-501`（done/empty 重跑即跳）；`src/api/autohome_api.py:1122-1131`（空文本 200 / JSON 解析失败 / 缺 result 均返回 None；`_get_text` 只重试 httpx 异常，反爬空响应体不重试）
- 问题：①第 1 页即 None → results=[] → 记 "empty" 终态，后续重跑永久跳过，真实有口碑的车系被当成无口碑；②中间页 None → 截断结果 delete+insert 后记 "done"，断点续跑不再补齐。71 系批量跑中一次瞬时限流即造成永久数据缺口；唯一恢复手段 `--force` 会重跑全部车系（含 63 个健康系）。`--series-delay` 只降概率不消除。
- 实证：源码路径推演；docstring 自证作者已知该失效模式（"防持续请求触发限流空响应"）但未在结果分类上区分 None（失败）与合法空。

### P1-4 覆盖率口径修改漏改"同口径"第三处：compute_insights 提及率分母未补全文 → T5 一跑即复发 >100% 类异常
- 位置：`src/insights/compute_insights.py:444-450`（tg_stmt 仅 best/worst 短文本条件，注释却声称"与 _batch_tag_coverage / _tag_coverage_for_series 同口径"）；对照本次修改 `src/tools/reviews.py:181-190`（`_has_text_filter` 补入 best/worst_full_text）、`src/api/dashboard_routes.py:85-95`
- 问题：本 change 的 T5（`backfill_tags_pool.py:111-117` pick_tag_input 短文本空回退全文）专门给 full-text-only 老数据打标签 → 这些口碑进 compute_insights 提及率的**分子**（rt_stmt 按 review_tags 计数）而**分母**（tg_stmt）不含 → 提及率可 >100%，正是本次在两处修掉的同类异常在姊妹指标复发。注释声称的口径不变量被本次修改打破。
- 实证：grep `best_full_text` 在 compute_insights.py 零命中 + 三处源码对比。

---

## P2（14 项）

1. **覆盖率三处修改零测试**：prism-dashboards/tests 无任何用例触及 `_tag_coverage_for_series`/`_batch_tag_coverage`/`collection_coverage`；本次口径修改（join 交集/分子交集/封顶）的全部行为断言只存在于 docstring。（reviews.py:169-177、routes:85-101、data:613）
2. **pool 文件存在但 deep 为空 → 静默回退 legacy 全量名单**：`recollect_all` `if not series_ids` 分支（:444-449）对"显式名单解析出 0 项"与"未指定"不加区分（如 --skip-binding 生成的 pool tier 全空），live 下可能触发全量非预期采集；docstring 只承诺"文件缺失"才回退。
3. **插入 commit 后、append_progress 前进程被杀**：库内 ≥100 行且无 progress 记录 → 守卫永久拦截该名单，需手工编辑 progress 解锁（fail-closed 但 pipeline 变砖）。（:528-538 顺序）
4. **load_progress 只容 JSONDecodeError**：损坏行若恰为合法非 dict JSON（如 `123`）→ `rec.get` AttributeError 启动即崩。（:253-261）
5. **无单实例锁**：两个 live 进程并发 → progress jsonl 交错写 + 同 sid 双 delete+insert 竞态；append_progress 无文件锁。（:264-269）
6. **_parse_args 未知 flag 静默忽略**：`--max-review 300`（少个 s）静默丢弃 → cap 失效全额采集，CLI footgun。（:560-591）
7. **backfill_pool_base.py:223 `cols["series_id"] = sid` 无条件覆盖 API 回显 id**：源站重定向/合并返回他系数据时会把 B 系数据写到 A 系 id 下（注释自认"应一致"但不校验），fail-open，与红线#7 fail-closed 精神相悖。
8. **sentiment 校验不一致**：backfill_tags_pool.insert_tags 严格过滤 pro/con（:202-204）；recollect 写 ReviewTag 时 `tag.get("sentiment", "pro")` 不校验（:419）——第三种 sentiment 值可经 recollect 路径落入 pro/con 二值字段。
9. **dry-run 非构造上零写**：recollect:443 / backfill_tags_pool:298 入口即 init_db()（create_all+迁移 DDL+PRAGMA WAL），当前 schema 下 no-op，但对旧/新库会写 schema，与 docstring"零写入"承诺不符。
10. **gen_nev_pool.load_prev_doc 损坏 prev fail-open**（:439-450）：旧件读不了 → 环比断言跳过照跑（有 WARN 打印），±10% 防线可被绕过。
11. **collection_coverage 封顶 1.0 掩盖异常信号**（data:613、routes:214-216）：库内远超源站标注本是 sid 错配/源站坏数据的症状，封顶后这些系显示"完美覆盖"，建议至少留超限计数或日志。
12. **`_get_all_reviews_for_model`（reviews.py:365-395）契约破裂**：只 SELECT best/worst 短文本列，但 `_has_text_filter` 已放行 full-text-only 行 → 返回的"有文本"集合里出现空文本、`_has_text=False` 的条目（LLM 提取候选集被污染/浪费调用）。
13. **工作树混入非本 change 改动**：dash_market.html 价格段散点筛选、dash_series.html Tab 默认互换等 UI 改动与 nevpool 管线同处未提交工作树，一并提交会夹带无关 diff（提交卫生）。
14. **两处 join 的 model_id 匹配条件不一致**：reviews.py:171 join 仅按 review_id，routes:93 join 要求 `o.model_id=t.model_id`——tag 行 model_id 漂移的病态数据下两视图口径分叉；按当前两条写路径构造上不会发生，提示统一。

## 测试质量评估（攻击面 f）

- 四个新测试文件真实覆盖所声称行为，断言行为锚定（cap 页码序列、守卫精确对账豁免/外部变动拦截、翻页去重保首现、insert 幂等重放、空返回熔断 12 条、locked 重试次数、metadata 共壳冲突首见落库）。无摆设测试。
- 缺口：本次 scope 第 5 项（dashboard 覆盖率口径）零测试；`_save_series_reviews`（全 change 最危险的写路径）无测试；`load_pool_series_ids` 无去重故也无去重测试（P1-1 相关村）。

## 检查过且干净的攻击面

- **b. --force × 守卫**：force 不绕守卫——`guard_conflicts` 在 live/dry/force 分支之前统一执行（:458-464）；豁免要求 progress 终态 + 库内行数与记录精确相等，外部变动仍拦。正确。
- **d. SQL 注入/参数化**：全部参数化（含 IN 占位符展开）；routes 的 text() 拼接仅静态常量；表名硬编码。路径遍历：CLI 入参为本地操作员工具路径，不构成攻击面。干净。
- **g. nev_pool/rulings 消费方**：backfill_pool_base `compute_gaps` 对共壳 sid 去重；tier 过滤天然排除 manual_review 降级项（assign_tiers 只认 BOUND_KINDS，共壳降级项 series_id 残留但进不了任何消费名单）；rulings 无程序消费方。除 P1-1 外干净。
- **h. 覆盖率 join 性能**：两条 GROUP BY + 既有索引（idx_owner_reviews_model_post、review_tags.model_id index、owner_reviews.review_id PK），批量替代逐系 ~650 次 COUNT，无性能退化。
