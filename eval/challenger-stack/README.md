# challenger-stack · 挑战者栈启动器（B 系列运行资产，2026-10-27 归档）

起序（全部 `powershell Start-Process -WindowStyle Hidden cmd -ArgumentList '/c','<本目录><脚本>'` 脱离会话执行，防会话结束连带杀跑批）：

1. `sentiment.cmd` — 舆情 eval :8100（快照 snap-20261012-1222，与 A 臂共用）
2. `dashboards.cmd` — 看板 eval :8110（同快照）
3. `api.cmd` — 挑战者 api :8004（PI_SERVER→9202，PRISM_EVAL_STACK=1 北极星隔离）
4. `gateway.cmd` — 挑战者网关 :9202（PRISM_PI_EXTENSION 显式加载 extensions-available/challenger-b1 + PRISM_PI_CWD 空目录双保险；无轨迹/无 langfuse env）
5. `runner.cmd` — B1b 全量批（PRISM_CHALLENGER_ARM=b；B1a 把 ARM 改 a）

纪律：
- **批处理文件必须 ASCII+CRLF**（UTF-8 中文注释+LF 会被 cmd 按 GBK 误析吞行——dashboards 的 cd 曾被吞）
- 点火前先跑 1 题冒烟验臂纯度（env 不进网关横幅，只有 runner 臂纯度检查能抓 env 丢失）
- 快照活性戳：`python prism.py eval start` 会写 ACTIVE_SNAPSHOT.txt；挑战者栈共用该快照
