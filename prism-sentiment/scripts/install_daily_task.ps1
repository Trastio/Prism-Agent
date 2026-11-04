# install_daily_task.ps1 —— 注册 PrismSentimentDaily 计划任务（每日 03:00 全量日更）
#
# ⚠️ 依赖（T5 交付，2026-10-16，舆情降本 change R22/D6）：
#   1. 本任务只调 daily_update.py --all；它依赖舆情服务 :8000 存活
#      （start.py supervisor / prism.py start 先起）——服务未起时脚本
#      退出码 2，当日无更新，靠次日自愈或手动补跑一次。
#   2. daily_update 退出码：0 全成功 / 1 部分失败或备份失败 / 2 服务不可达 /
#      3 无待更新车。计划任务不自动重试失败轮。
#   3. 03:00 的选择：避开互动刷新等待窗（P2-4 refreshing 语义），15 台
#      ×约 5 分钟串行预计 03:00-04:15 跑完，不与白天使用撞车。
#   4. 用 Register-ScheduledTask（而非 schtasks.exe）：需要 WorkingDirectory
#      ——清理/备份的 data/ 路径相对 cwd，工作目录必须钉在项目根。
#
# 用法（管理员不必需，注册当前用户任务即可）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_daily_task.ps1
#
# 注册后验证：Get-ScheduledTask -TaskName PrismSentimentDaily
$ErrorActionPreference = "Stop"

$TaskName = "PrismSentimentDaily"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir   # prism-sentiment 根（工作目录）

# ── Anaconda Python 探测：Get-Command 命中 anaconda 路径 → 常见安装位 → 失败报错 ──
$Python = $null
$cmd = Get-Command python -ErrorAction SilentlyContinue
if ($cmd -and $cmd.Source -match "anaconda") {
    $Python = $cmd.Source
}
if (-not $Python) {
    $candidates = @(
        "$env:USERPROFILE\anaconda3\python.exe",
        "C:\ProgramData\Anaconda3\python.exe",
        "C:\Anaconda3\python.exe",
        "$env:USERPROFILE\miniconda3\python.exe"   # miniconda 同池兼容（回退位）
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { $Python = $p; break }
    }
}
if (-not $Python) {
    throw "未找到 Anaconda Python（已试 Get-Command + 常见安装位：$($candidates -join ' ; ')）。请先激活 Anaconda 环境或手工指定。"
}
Write-Host "[OK] Python: $Python"
Write-Host "[OK] 工作目录: $ProjectDir"

# ── 任务定义 ──
$Action = New-ScheduledTaskAction -Execute $Python `
    -Argument "`"$ProjectDir\scripts\daily_update.py`" --all" `
    -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -Daily -At 3:00AM
# S4U：无须登录、不存密码（本机 HTTP 调用无网络凭据需求）
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Principal $Principal -Settings $Settings -Force | Out-Null

$t = Get-ScheduledTask -TaskName $TaskName
Write-Host "[DONE] 任务已注册: $($t.TaskName) / State=$($t.State)"
Write-Host "       下次触发: 每日 03:00（错过自动补跑 StartWhenAvailable）"
Write-Host "       手动试跑: Start-ScheduledTask -TaskName $TaskName"
