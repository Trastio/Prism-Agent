# Step9 verification · 验收对照（2026-10-13）

对照 proposal 验收标准 7 条：

| # | 验收标准 | 结果 | 证据 |
|---|---|---|---|
| 1 | ts 修复可复算 | ✅ | TestClient 端点值 = 独立 SQL 对账 **ALL MATCH**（脚本留档于会话）；旧口径 35→精确 32 即修复实证；写入端全 UTC 坐实（tracker.ts:48 / main.py:135） |
| 2 | 7 指标渲染真数据 | ✅ | tabbit 实测 KPI 7 个：看板 DAU 3 / 对话 1 / 总 3 / 周结论 32 / 采纳率 0.0% / 人均 3.56 / 轮时长中位 23 秒 P90 74 秒——与后端返回逐项一致 |
| 3 | 四象限=手工对账 + 终轮归一 + 抽屉回放 | ✅ | quadrant 对账 ALL MATCH（pass_clean 6 / fail_clean 1）；终轮归一 7 session；抽屉 2000 字结论 + 工具清单（submit_conclusion×16/get_config_detail×15/resolve_series×5）+ verdict（events 终轮）与表格一致 |
| 4 | 空态三情况不崩 | ✅ | trends 全 0（tag"区间无数据"，10-10 全零日实测渲染）；items 空（"近14天无终轮会话"文案路径）；latency null（fmtMs '—'，NaN 防护）。tsc/build 绿 |
| 5 | 60s 兜底 flush | ✅（10-13 补实测） | **浏览器实测 PASS**：页面加载产生 1 条不满批 page_view（local_id=usr_hist_test），库行 id 基线轮询，入队→落库可见 **60s 整**（60s 定时器精确生效）；代码级证据：FLUSH_INTERVAL_MS=60000 + initTracker 返回清理函数（App useEffect 接线）+ 既有 beforeunload/pagehide/visibilitychange flush 保留 |
| 6 | smoke 全绿 + tsc + build | ✅ | smoke:all 全过（12+31+15 passed / 0 failed）；root tsc 11=历史基线零新增；web build 2.86s |
| 7 | UI 走查 | ✅ | tabbit 两轮+修复复验：侧栏入口可达、视图保活（切对话再切回 KPI 7 个保持）、30s 轮询配置生效、手动刷新按钮、时间本地化 |

## Step5 施工复核（10-13 补合规位，claude 型子代理独立执行）

用户拍板"主会话代行施工不合规"后补：fork 型（claude 型）施工复核子代理独立核验 11 项（详见 step5-recheck.md，87 行）：**10 PASS / 1 FAIL**。FAIL=eval/badcases.md 落在 prism-web/eval/（cwd 漂移事故），已移回根 eval/ 并删空目录。后端验收重跑值：total_dau=3 / latency n=23 excluded=10 / quadrant 四键齐全（数据随新会话自然增长）。备忘偏差（不计 FAIL）：T1.1 `_ts_ok` helper 未抽公共函数（julianday 以内联 win24/win7/win7s 实现，目标已达成）。

## 流程合规

- 十步全走：explore→proposal→tasks→self-check→施工→simplify→**隔离审查子代理（代码内嵌法）**→receiving-review（13 条逐条核实）→verification→archive
- **Step5 施工位合规补救**：施工时主会话代行（当时默认型子代理证实无文件工具），后经用户裁决不合规 → 探针打通 fork 型（claude 型有 Bash+Read）→ 派施工复核子代理补位（上节）
- 并行会话协议：跑前查 logs/ 重启记录（发现对方 13:22 全栈重启）→ 避开 8010 → 仅单服务重启 8002 两次（各 ~8s 窗口）
- 施工中自抓 2 个集成 bug（viewMetrics 嵌套错位 / CSS id 规则缺失），tabbit 诊断定位后修复

## 留 v2

- trajectories 读取 mtime 缓存（P2-7）；adoption session 级配对（P2-4）；unknown verdict 独立计数（P2-2）
- 上云清单新增：ECS 时区 Asia/Shanghai（localtime 分桶依赖）；/trajectory+/badcases 鉴权收口（P2-9）
- 弹窗两问/周访谈/种子群（提纲阶段⑤）；langfuse 接线（独立 change 方案已定稿）
