@echo off
rem B1b challenger stack - dashboards-eval :8110 (snapshot snap-20261012-1222)
cd /d C:\Users\<you>\Desktop\Prism-Agent\prism-dashboards
set DASH_PORT=8110
set DATABASE_URL=sqlite:///C:/Users/<you>/Desktop/Prism-Agent/eval/snapshots/snap-20261012-1222/autohome.db
"C:\Users\<you>\Anaconda3\python.exe" app.py > C:\Users\<you>\Desktop\Prism-Agent\logs\b1b-dashboards.log 2>&1
