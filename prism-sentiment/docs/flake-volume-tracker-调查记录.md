# test_volume_tracker flake 调查记录

> 2026-09-22 立案（2026-09-20~21 双模式看板执行期间 3 次目击，T12 终验 time-box 15 分钟未结案，转长期观察）

## 目击记录

| 时间 | 场景 | 结果 |
|---|---|---|
| 09-20 ~03:00 | 全量（T4 抛光后首跑） | 1 failed, 665 passed |
| 09-20 ~03:00 | 组合 test_points + volume_tracker | 1 failed, 32 passed（当时复现一次） |
| 09-21 ~12:30 | 全量（qual-t6 审查跑 3 次，第 1/2 次炸） | 同树第 3 次 668 全绿 |

## 已排除

- **与双模式改动无关**：受害测试 `TestDetectEventsFromPosts::test_different_topics_form_separate_events` 是纯函数测试（内存 posts，无 DB），与 point_miner/points 端点零共享模块/零共享 import。
- **PYTHONHASHSEED**：固定 seed 0-19 单跑 20 次全过（含 09-20 扫掠与 09-21 qual-t6 复核各 10 个 seed）。
- **隔离/小组合**：单测 20+ 次全过；与 test_points.py 合跑 3/3 过；前后半文件分段合跑过。
- **单段累积**（09-22 T12 二分）：47 文件除 volume_tracker 外分 4 段，各段+目标测试全过（12/12/12/10 文件，146/104/190/223 passed）。
- **当日全量复跑**：09-21 三连（1 炸 2 绿）、09-22 一发 672 全绿——**全量也不稳定复现**（约 2/8 概率）。

## 剩余假设

1. **全量级累积状态**：只有全部 46 文件连续执行才触发的跨文件污染（候选：共享 file-based 测试库 data/test_vehicle_sentiment.db 的行量越过某阈值，影响 detect_events 的某个量敏感分支——但该测试纯内存，污染只能来自 import 侧全局状态如 jieba/networkx 缓存）。
2. **时间敏感**：三次目击都在长会话/高负载时段（多次 pytest 并行子代理活动），CPU 竞争下 time-based 逻辑（事件时间切分用 time.monotonic?）分支摆动——待查 `split_community_by_time`/`detect_events_from_posts` 是否有隐式时钟依赖。
3. **纯低概率随机**：约 25% 失败率的 per-run 随机源（未定位）。

## 下一步（复现时执行）

- 目击时立即：`git stash`（若有工作区改动）→ 连续跑全量 5 次统计失败率 → 失败 run 用 `-p no:cacheprovider` 与 `--tb=long` 留全栈
- 定向：给 detect_events_from_posts 加一次性插桩（打印 G 节点数/边权/partition），对比过/炸两次 run 的中间产物
- 若确认时间敏感：查 event_tracker.py 全文 `time\.` 引用

## 当前处置

不阻塞交付（672 基线以"全量至少一发全绿+受害测试与近期改动无耦合"为准）；CI/终验遇单发失败先重跑一次再判。
