# 夜跑 env 加载修复 + 预算终值（微 change，2026-10-21 直修归档）

## 起因（10-21 夜跑核查发现）

R40 清理夜跑恒 dry-run：`.env` 有 `PRISM_CLEANUP_LIVE=1` 但 03:00 任务日志显示 dry-run（30 天线 72 帖积压、26 事件组引用悬空预警）。

## 根因

`daily_update.py` 是 **HTTP 编排器**：采集经 POST 触发常驻服务进程跑（那边自有 load_dotenv），但收尾的 30 天清理跑在**编排脚本自己的进程**——该进程从未加载 .env，`PRISM_CLEANUP_LIVE` 恒缺 → 真删门恒关。10-20 首次真删成功是手动跑（shell 环境有值），计划任务环境必现 dry-run。

**连带纠错**：任务命令里的 `set TIKHUB_DAILY_BUDGET=4000` 是死值——它只给了编排进程，而编排进程不调 TikHub（F2 同族：env 前缀对服务进程无效）；实际生效的预算始终是服务进程从 .env 读的值（当时 7000）。

## 修复（用户拍板：预算 1500 + 其余按 AI 方案）

| # | 动作 | 文件 |
|---|---|---|
| 1 | main() 首行 load_dotenv()（override=False 不覆盖 monkeypatch 值，测试隔离安全） | scripts/daily_update.py |
| 2 | 钉子测试×2（main 最先加载 .env / override 语义） | tests/test_daily_update_env.py（新） |
| 3 | 预算终值 .env 7000→**1500**（稳态 8 车×~73 次≈600/天 ×2.5 余量熔断线；旧 7000=10-16 污染临时值） | .env（不入 git） |
| 4 | 任务命令去死值 `set TIKHUB_DAILY_BUDGET=4000&&`，改 -WorkingDirectory 直跑（预算单源=.env） | 计划任务（注册表） |
| 5 | S4U 化尝试 | **失败：拒绝访问（需管理员）**——任务仍 Interactive |

## 验证

- pytest 全量 **929 过 / 1 存量挂**（test_cache_bust，非本件）；新增 2 钉子全绿
- .env 解析实测：PRISM_CLEANUP_LIVE='1'、TIKHUB_DAILY_BUDGET 载入正常（dotenv 解析无问题，坐实根因在进程结构）
- 任务 Action 更新后实测回读：`/c "python.EXE" scripts\daily_update.py --all >> logs\daily_task.log`（无 set 段）
- **今晚 03:00 起清理将真删**（进程结构修复后 live=1 生效）——明早看日志 `[CLEANUP]` 无 dry-run 提示即闭环

## 遗留（待用户，一条命令）

S4U 化需管理员权限，用户在**管理员 PowerShell** 跑一次：
`Set-ScheduledTask -TaskName 'PrismSentimentDaily' -Principal (New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited)`
（或管理员跑 scripts/install_daily_task.ps1 重新注册，其 52-53 行本就是 S4U 形态）
在此之前：任务仍"仅登录时运行"——电脑无人登录的夜晚会静默跳过。
