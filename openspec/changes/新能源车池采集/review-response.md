# review-response · Step7 隔离审查处置（2026-10-18）

审查者：Step7 隔离审查子代理（第三次派发；纯代码实证，未读设计文档，生产库只读）。
报告：`t7-review-report.md`。回归：`pytest tests/ -q` = **183 passed**（修复后）。

## P1 ×4 —— 全部核实成立、全部已修

| # | 发现（核实✅） | 修复 |
|---|---|---|
| P1-1 | deep 名单 8 个重复 sid（共壳双 sales 名双双 deep），load_pool_series_ids 不去重 → 单轮双跑+终态可劣化 | recollect_all 入口保序去重 `list(dict.fromkeys(...))` |
| P1-2 | delete 后中途 commit：插入批任一行失败 → 车系清零且重跑反复清零 | 去掉中途 commit，delete+insert 同事务，失败整体回滚（旧数据原封不动） |
| P1-3 | fetch None 与自然尽头不可区分：限流一次 → empty 永久跳过 / 中间页截断记 done | 冷却 20s 重试一次，仍空**抛错走 failures**（可断点重扫），不再静默记 empty/截断；与 P1-2 组合=「要么整系完整落库，要么原数据不动」 |
| P1-4 | compute_insights 提及率分母漏全文口径（"同口径"第三处漏改）——T5 给全文老数据打标后提及率可 >100% | tg_stmt 补 best/worst_full_text 四字段口径，注释同步 |

修复后行为语义：**单系采集要么完整成功、要么整体不动并记 failed（可重扫）**；限流空响应在批内自动冷却重试一次。

## P2 ×14 —— 逐条裁决

| # | 裁决 | 说明 |
|---|---|---|
| 1 | 记录 | 覆盖率口径零测试 → 月度滚动 change 补测 |
| 2 | 记录 | pool deep 空回退 legacy 与 docstring 不符 → 月度滚动改 |
| 3 | 记录 | insert 后 append 前被杀 → 守卫拦截需手工删 progress 行（今晚已实际演练过该方法，有效） |
| 4 | 记录 | load_progress 非 dict 行启动崩 → 低概率，defer |
| 5 | 记录 | 无单实例锁 → 月度滚动 change 加 |
| 6 | 记录 | _parse_args 未知 flag 静默 → defer |
| 7 | 记录 | backfill_pool_base 覆盖回显 sid（fail-open）→ 该路径不再运行；月度滚动改 |
| 8 | 记录 | 两脚本 sentiment 校验不一致 → defer |
| 9 | 记录 | dry-run 的 init_db DDL/WAL → 无数据风险，defer |
| 10 | 记录 | prev 损坏 fail-open（有 WARN）→ defer |
| 11 | 记录 | 封顶 1.0 掩盖 sid 错配信号 → 注释已注明；超限日志 defer |
| 12 | 记录 | _get_all_reviews 只 SELECT 短文本（与 P1-4 同族）→ 下钻页部分行判定受影响，完整修列月度滚动 |
| 13 | **处理** | 工作树混入非本 change UI 改动 → **Step10 提交时按文件分离：本 change 文件单独 commit** |
| 14 | 记录 | 两处 join 的 model_id 匹配条件不一致（构造上不触发）→ 统一列月度滚动 |

## 审查员确认干净的部分
--force 不绕守卫 / SQL 全参数化 / nev_pool 消费方（除 P1-1）/ rulings 无程序消费方 / 覆盖率 join 无性能退化 / 四个测试文件真实无摆设。

## 遗留汇总（月度滚动 change 清单）
覆盖率口径补测试、P2-2/4/5/6/7/8/12/14、增量采集模式、口径拍板（单月 vs 3 月合计）、看板分级徽标、FK pragma 根治、rulings 接入生成器、无价带守卫、onsell_review_count 分母弃用。
