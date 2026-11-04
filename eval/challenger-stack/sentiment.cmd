@echo off
rem B1b challenger stack - sentiment-eval :8100 (snapshot snap-20261012-1222, shared with A arm)
cd /d C:\Users\<you>\Desktop\Prism-Agent\prism-sentiment
set DB_PATH=C:/Users/<you>/Desktop/Prism-Agent/eval/snapshots/snap-20261012-1222/vehicle_sentiment.db
"C:\Users\<you>\Anaconda3\python.exe" -m uvicorn api.main:app --port 8100 > C:\Users\<you>\Desktop\Prism-Agent\logs\b1b-sentiment.log 2>&1
