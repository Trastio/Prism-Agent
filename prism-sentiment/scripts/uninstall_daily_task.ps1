# uninstall_daily_task.ps1 —— 注销 PrismSentimentDaily 计划任务（T5 交付，2026-10-16）
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall_daily_task.ps1
$ErrorActionPreference = "Stop"

$TaskName = "PrismSentimentDaily"
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[DONE] 任务已注销: $TaskName"
} else {
    Write-Host "[SKIP] 任务不存在（可能未注册）: $TaskName"
}
