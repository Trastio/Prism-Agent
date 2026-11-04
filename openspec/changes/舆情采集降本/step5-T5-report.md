# Step5 · T5 施工报告（全量日更 + 计划任务脚本）

> 子代理：t5-schedule（fork 型）· 2026-10-16 · 依据 design.md D6 + tasks.md T5
> 红线遵守：未 git commit、未重启服务、未注册计划任务、零付费 API 调用

## 一、改动清单

| 文件 | 改动 |
|---|---|
| scripts/daily_update.py | ① `--all` 频率分层跳过**删除**（R22）：`_select_by_frequency` 包装函数 + `pipeline.frequency` 导入块 + `[FREQ]` 分支整段移除；`--all` 与缺省同义（全量 active），留作计划任务显式旗标；`--vehicle` 子串过滤两态通用（空=全部 active）② 死引用清理：`sqlite3`/`timedelta`/`date` import（counts 早已移居 frequency.py，本文件再无直查）③ docstring 重写（用法行 + R22 说明块 + 收尾三件套描述）④ `--all` argparse help 同步 |
| scripts/install_daily_task.ps1（新） | `Register-ScheduledTask` 注册 `PrismSentimentDaily`：每日 03:00、Execute=Anaconda python、Argument=`daily_update.py --all`、**WorkingDirectory=prism-sentiment 根**（清理/备份的 data/ 路径相对 cwd，schtasks.exe 不支持工作目录故不用它）；Anaconda 探测=Get-Command(含 anaconda 路径)→常见安装位（anaconda3/ProgramData/miniconda3 回退）→明确报错；Principal=S4U（无须登录不存密码，本机 HTTP 无网络凭据需求）；Settings=StartWhenAvailable（错过补跑）+电池允许+4h 时限；头注释含 :8000 服务依赖/退出码语义/03:00 理由（避开 refreshing 等待窗，15 车约 75min） |
| scripts/uninstall_daily_task.ps1（新） | 存在性检查 + Unregister，两态友好输出 |
| tests/test_daily_update.py | +3 用例：`test_all_targets_all_15_active`（镜像车池 15a+6p+4i，断言 15 collect 全落 active、无 `[FREQ]`）/`test_all_equals_default_semantics`（旗标同义）/`test_vehicle_substring_filter_still_works`；公共脚手架 `_run_main_with`（mock 三件套收尾+外呼，沿用 T3 事故补丁模式） |

**未注册任务**（留 T6 用户点头）；frequency.py 模块保留未动（展示排序消费方仍在）。

## 二、自验证据

- `pytest tests/test_daily_update.py` → **6 passed**（3 存量 + 3 新增）
- **T5 邻域回归面 58 passed**（daily_update/frequency/engagement_refresh/cleanup/T1/T2）——frequency 模块保留后其 12 用例全绿
- **PS1 语法**：Language.Parser 解析双 OK。**坑记录**：PS1 含中文注释必须 **UTF-8 with BOM**——无 BOM 时 PowerShell 5.1 按 ANSI 读、中文字节吞引号致假语法错（首轮 [OK] 标记报错即此），已补 BOM 修复
- 导入冒烟：`_select_by_frequency` 已不存在、ACTIVE_PHASES 完整；grep 频率/sqlite3/timedelta/[FREQ] 零残留
- **全量套件：875 passed / 9 failed——8 个失败全在 `test_t4_polarity_direct.py` + `test_batch_runner.py`（run_comment_analysis 系），系并行施工中的 T4 极性直出在途状态（其测试文件已在盘、源码改造未完），非 T5 回归**；第 9 个为 T1 已证的存量 `test_cache_bust`。T5 文件面与失败集零交集

## 三、偏差与决策记录

1. `--all` 与缺省语义合并后，原"--all 时忽略 --vehicle"的行为变为"--vehicle 两态通用"（空串=全部，等价旧缺省）；计划任务只传 `--all` 不受影响
2. 用 Register-ScheduledTask 而非 design 未指定的 schtasks.exe——工作目录刚需决定（见上）；S4U/StartWhenAvailable 为稳健性自选，报告留档可调
3. miniconda3 列为探测回退位（任务书写 Anaconda；实际只求"带 pipeline 依赖的 python"，miniconda 同池）

## 四、移交 T6

- 注册执行：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_daily_task.ps1`（人工运行）→ `Start-ScheduledTask -TaskName PrismSentimentDaily` 试跑一轮 → 连续两日观察退出码
- 与 T4 收尾后合跑全量套件，确认 8 个在途失败归零
- daily_update 打印文案中"待更新 N 车"即覆盖车数断言来源（日志可直接核对=15）
