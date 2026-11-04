# Step 1 · 摸底报告（口碑周更增量采集，2026-11-01）

## 1. 现役机制盘点（全部实测核过代码）

### 1.1 采集器 `prism-dashboards/scripts/recollect_koubei_with_full.py`（628 行）
- **写库模式 = delete+insert 整系重采**（`_save_series_reviews`：先删该车系全部 owner_reviews → CASCADE 级联删 review_tags → 整批插入，单事务原子）。NEV 深采就是它跑的（189 系次 0 失败，progress 留痕）。
- **review_id = `k_{showId}`**（之家详情页 showId，长字符串；Koubeiid 短数字仅 fallback）——**同一条口碑跨次采集 ID 天然稳定**。增量模式保 ID 稳定有物理基础。
- 已有能力（可直接复用）：翻页去重（同 review_id 保首现）、限流空响应冷却 20s 重试→失败入 failures 不静默、单系 cap（--max-reviews 页粒度取整）、名单入参（--series-ids / --pool-file tier=deep）、启动守卫（delete+insert 禁入存量分析池 ≥100，progress 精确对账豁免）、**默认 dry-run 零写入零出网 + PRISM_COLLECT_LIVE=1 门控 + live 前置备份探测**、progress 断点续跑 jsonl、系间冷却 --series-delay。
- 打标在采集流水线内（`_save_series_reviews` 内 tagger.extract_tags，仅对有原文条目）。

### 1.2 口碑 API（`src/api/autohome_api.py`）
- `fetch_koubei_page(series_id, page_index, page_size=20, yearid=0, order=0)`——`order=0` 排序参数现值未用其他值；**翻页非严格稳定排序**（10-16 铂智3X 实证同条口碑相邻页重复）。
- 列表页 item 含 showId/posttime/contents/scoreList → `parse_koubei_item` 全量解析。

### 1.3 打标器 `src/nlp/tagger.py`
- **关键词命中优先零成本，LLM 兜底**（DeepSeek deepseek-chat，TAGGER_* env 可换）——周增量的打标边际成本天然低：新条目先过关键词，未命中才花 LLM。预算帽需盖"新条目数"即近似盖 LLM 调用量。

### 1.4 调度挂载点 `prism.py`
- cmd_* 函数式子命令（eval/start/stop/status/install-autostart），加 `koubei-weekly` 子命令成本低；先例：quality-v7-rejudge.cmd 双击驱动件（Write 直写+正斜杠+ASCII 的教训在册）。

### 1.5 运行环境与并发约束
- 生产库 = `prism-dashboards/data/autohome.db`（SQLite，WAL），**共享库：Atuohome 侧定时刷新会写入**（NEV 验收件原话）；方案 §7 已立"单写者纪律"。
- 采集面不上云（之家反爬对云 IP 不友好，§7 拍板）——周更永远跑工位机，上云后仅"调度换容器 cron"这一句注记。

## 2. 差距清单（周更需要、现役没有的）

| # | 缺口 | 说明 |
|---|---|---|
| 1 | **增量模式** | 现役只有整系重采（delete+insert）。周更必须：只插新、绝不删，已存在 review_id 跳过（insert-skip） |
| 2 | **停止判据（水位）** | API 无"按日期增量"参数；翻页排序非严格稳定 → 水位判据取"**整页全部为已知 review_id → 停**"（对乱序鲁棒），而非"见首条已知即停" |
| 3 | **预算帽** | 无全池新条目总帽；需 budget_capped 早退留痕（照舆情 collection.py 语义） |
| 4 | **调度** | 无任何定时机制；需 prism.py 子命令 + 双击 cmd（任务计划注册可选） |
| 5 | **水位台账 + 看板"更新至"戳** | 无 collection_runs 类运行台账；看板无口碑数据时点展示 |

## 3. 风险与边界

1. **共享库并发写**：Atuohome 侧定时刷新窗口未知（源项目内部，不探）——周更换冷时段（凌晨）+ WAL + 短事务；冲突最坏情况=SQLite busy 重试，不损数据。
2. **ID 稳定性的真实威胁不是我们的增量，是 delete+insert 语义残留**：若周更误用重采模式跑存量系 = 整系重删重插 + cap 截断（300 帽会把老口碑删掉）→ 守卫必须按模式区分（见 proposal）。
3. **翻页漂移**：新口碑很少的周，第 1 页整页已知即停 = 每系每周最少 1 页请求（96 系 ≈ 96 请求打底，温和）。
4. **详情页与打标只对新条目做**（已知 ID 在列表页阶段就跳过，不抓详情）——请求量 ∝ 新增量。

## 4. 口径归属澄清（验收遗留项拆解）

- 验收遗留"增量采集模式、口径（单月 vs 3 月合计）：月度滚动 change"——实为**两件事**：①增量采集模式=本 change（周更，用户 2026-11-01 拍板）；②单月 vs 3月合计=**月度滚动缺口扫描（§8）的分层晋升判据**，随 CAM 月末批触发的月度工作流，不属本 change。
- 本 change 唯一待定口径：周更名单怎么圈（proposal 荐：库内有口碑的车系全集 ≈96 系，不按销量分层）。
