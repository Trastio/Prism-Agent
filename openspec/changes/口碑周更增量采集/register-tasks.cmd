@echo off
REM register-tasks.cmd - koubei weekly scheduled tasks (no admin required)
REM Task 1: weekly Sunday 04:00 (Interactive, same as PrismSentimentDaily)
schtasks /create /tn "PrismKoubeiWeekly" /tr "cmd /c cd /d C:\Users\<you>\Desktop\Prism-Agent\prism-dashboards && C:\Users\<you>\Anaconda3\python.exe scripts\koubei_weekly_update.py --live >> logs\koubei-weekly.log 2>&1" /sc weekly /d SUN /st 04:00 /f
REM Task 2: logon catchup (schtasks /sc onlogon = ACCESS DENIED unelevated; PowerShell AtLogOn verified 2026-11-01)
powershell -NoProfile -Command "Register-ScheduledTask -TaskName 'PrismKoubeiCatchup' -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME) -Action (New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c cd /d C:\Users\<you>\Desktop\Prism-Agent\prism-dashboards && C:\Users\<you>\Anaconda3\python.exe scripts\koubei_weekly_update.py --catchup >> logs\koubei-weekly.log 2>&1' -WorkingDirectory 'C:\Users\<you>\Desktop\Prism-Agent\prism-dashboards') -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries)"
echo === VERIFY ===
schtasks /query /tn "PrismKoubeiWeekly" | findstr /i "PrismKoubei"
schtasks /query /tn "PrismKoubeiCatchup" | findstr /i "PrismKoubei"
