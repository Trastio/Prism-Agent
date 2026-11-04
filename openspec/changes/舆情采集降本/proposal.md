# 舆情采集降本 change · Step 2 proposal

> 日期：2026-10-15 · 依据：方案 v2.2（R1-R42）+ 本 change explore.md · 5 项待拍已按用户"继续"按推荐锁定（R43）

## WHY

采集费用月 1.1-1.5 万（分层实跑口径）过高；方案已经过 13 轮拍板收敛（R1-R43），全部方向层/参数层裁决完毕，本 change 把它变成代码。

## WHAT（一句话）

15 台 active 每日自动跑：6 词搜索 + 评论 top10×2页+负面追加 + 内嵌 30 天窗刷新 + 指数 2 次，单车 ≈96-98 次（−82%）；30 天物理清理（paused 豁免）；日预算护栏；评论极性直出；新闻/微博/快手停采；`--all` 全量无频率跳过。

## 已锁定的 8 个决策（R43 批）

| # | 决策 | 值 |
|---|---|---|
| D1 | 社媒词数 | 15→**6**（核心1+双关键词2+缺陷 top3）——需修 `_build_collection_keywords` 拼序（见 design） |
| D2 | 评论 | top10×2 页 + 负面追加 10/平台（负面词表预筛） |
| D3 | initial 首采 | **6 词**（同 D1 通道）+ 窗 30 天（`INITIAL_WINDOW_DAYS`） |
| D4 | P1 缺陷词轮换 | **进本 change**：top3 缺陷词按 `DEFECT_ROTATE_DAYS=2` 逐日轮换（确定性算法） |
| D5 | 护栏初值 | `TIKHUB_DAILY_BUDGET=2200`（15×98×1.5，账单到后调） |
| D6 | 计划任务 | 凌晨 3 点（避开互动刷新等待窗口；15 车约 75min 跑完） |
| D7 | 清理 | `POST_RETENTION_DAYS=30` + paused 豁免 + 首次清理 dry-run 先行 |
| D8 | 极性直出 | 新列 `comment_polarity`（不迁移老数据，读侧新列优先/老列回退推导，切换日=口径 stamp 断点） |

## explore 两个"待核实"的结论（修正方案前提，已回写方案 R43）

1. **"周日全 15 词轮扫"不存在于代码**——词数由 `platform_strategy.max_keywords`（每平台同值）决定、逐日相同；频率分层（frequency.py）只决定"哪台车今天跑"。R30 的"删周轮"=零代码动作；真正的词数改动 = max_keywords 15→6。
2. **互动刷新是采集流程内嵌**（api/routes/collection.py:133 采集完自动 refreshing），现状=每天全刷 30 天窗。R39 维持现状=零代码；L3 净改动仅 `_TOP_N` 30→15。

## 影响范围

- prism-sentiment：scheduler.py / platform_strategy.py / batch_runner.py / post_utils.py / local_absa.py / tikhub_collector.py / collection.py / daily_update.py + 新文件 cleanup_posts.py
- 不碰：agent 6 工具与端点、出口闸（仅验收回归）、帖子 GLM 15 维链、车质网、analyzer 维度常量、derive 链的老数据
- 上线顺序约束：**清理任务必须在 9 词对照实验与首次 dry-run 之后**才能真删（防误删+保基线）

## 风险

| 风险 | 缓解 |
|---|---|
| 极性直出后翻车帖判定失效 | 新列+读侧回退双轨；验收含 pos2neg/neg2pos 回归 |
| 清理误删 | paused 豁免断言 + 首次 dry-run 清单人工过目 + 库备份先行 |
| 护栏误伤 | 1.5 倍余量 + budget_capped 次日自动补（增量窗机制天然补） |
| 切换首日窗宽（停摆 ≈10 天） | 首日调用量偏高已在护栏余量内；基线实验独立跑不受影响 |
| 6 词+轮换后缺陷检出下滑 | §3.7 两周校准 + 9 词对照实验基线 + 回退=top6（env 可逆） |

## 验收（=explore §四 10 项，不赘引）

## 不做边界

微博/快手/新闻 collector 代码不删（配置层摘除归档）；agent 侧 stale 文案消费（skipped_vehicles 的用户可见层）留 change 2；前端一切归 change 2；免费 API 替代本地模型的两步验证独立排期（本 change 后）。
