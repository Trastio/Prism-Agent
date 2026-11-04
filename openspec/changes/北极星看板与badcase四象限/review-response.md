# Step8 receiving-review · 审查处置表（2026-10-13）

> 审查方：隔离子代理（代码内嵌法，~30KB 离线审）。审查报告 1P0+2P1+10P2。
> 处置纪律：逐条核实再修，不盲改。**核实工具：grep/TestClient/走查实证/tabbit。**

| # | 审查发现 | 核实结论 | 处置 |
|---|---|---|---|
| P0-1 | trends `_s` 未定义 NameError | **误报**——main.py:240 函数内 `import sqlite3 as _s` 在盘。**根因是我组装审查包时漏贴 import 行**（凭上下文记忆拼装而非磁盘提取），审查者基于残缺代码正确地报了错 | 关闭。**教训入库：内嵌审查包必须从磁盘提取，或拼装后与磁盘 diff 校验** |
| P1-1 | ts 双格式时区 8h 偏移 | **降级关闭**——两个写入端全 UTC（tracker.ts:48 `toISOString()` + main.py:135 `utcnow()`），julianday 解析一致无偏移；仅 4 行手造测试数据无 Z（页脚已声明含测试数据）。残留：`date(...,'localtime')` 依赖部署机 OS 时区 | 记入上云清单：**ECS 时区必须 Asia/Shanghai**，否则逐日分桶口径漂移 |
| P1-2 | /trajectory 端点存在性 | **误报**——explore 已核实（main.py:605-623），走查实证抽屉 2000 字结论。附带建议（错误分支）并入 P2-1 修 | 关闭 |
| P2-1 | 错误态全吞 | 成立 | **已修**：jfetch 统一 `!r.ok throw`（三 query + 抽屉）+ 页面错误横幅（"接口异常：stats/trends —— 30s 自动重试"）+ 抽屉 isError 分支 |
| P2-2 | verdict 非 pass 归 fail | 疑——value 域实测 pass/fail 二值（ChatView track `verdict \|\| 'unknown'` 理论有第三值） | 不修：docstring 已声明口径（非 pass 归 fail 侧）。留观察 |
| P2-3 | feedback 无时间窗 vs finals 14 天窗 | 成立（口径债） | **已修**：fb 查询加同窗 `julianday(ts) >= julianday('now','-14 day')` + docstring 同步 |
| P2-4 | adoption 分子分母非同集可 >100% | 成立（D4 设计口径未声明后果） | **已修**（声明法）：页脚补"同一会话多次点赞/点踩分别累计"。改 session 级配对留 v2 |
| P2-5 | items 字符串排序 + ROW_NUMBER 并列不确定 | 成立 | **已修**：python 侧 `_ts_key`（fromisoformat 数值排序）+ 窗口函数加 `, rowid DESC` 次级键 |
| P2-6 | last_ts 原样 UTC 展示 | 成立（走查实证 01:25 实为 09:25） | **已修**：fmtLocal（带 Z/带+按原解析，naive 补 Z 按 UTC），走查复验 10/13 09:25 ✅ |
| P2-7 | trajectories 全量逐行读 + 30s 轮询 | 现状 990 行无压力；append/读并发半行已被 except 跳过 | 不修：留 v2（mtime 键 lru_cache 方案记档） |
| P2-8 | 60s flush 关页丢尾部 | **误报**——既有 beforeunload/pagehide flush + visibilitychange(hidden) flush 都在（tracker.ts:74-86），审查者只见改动段 | 关闭 |
| P2-9 | 无鉴权数据暴露 | 已知边界（proposal R3/不做边界） | 记录：上云前收口清单（与 user_id 鉴权同项） |
| P2-10 | 抽屉终轮与 events 终轮两套定义 | 成立（events 与 trajectories 落盘不同步时可自相矛盾） | **已修**：BadCaseDrawer 收 `verdict` prop（表格 events 终轮传入），头部行标"verdict（events 终轮）"，走查复验表格/抽屉一致 ✅ |

## 修复合计

修 6（P2-1/3/4/5/6/10）· 关闭 4（P0-1、P1-1 降级、P1-2、P2-8 误报）· 记录不修 3（P2-2 观察 / P2-7 v2 / P2-9 上云清单）。

## 复验

- TestClient 三端点全 200 且值不变（32/latency n=23 excl=9/quadrant 6-0-1-0）
- web build 2.86s 绿（含 tsc --noEmit）；root tsc 11=历史基线
- 8002 已重启加载修复；tabbit 复验：时间本地化生效（09:25）、抽屉 verdict（events 终轮）与表格一致
