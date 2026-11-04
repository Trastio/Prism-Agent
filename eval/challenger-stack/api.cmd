@echo off
rem B1b challenger stack - challenger api :8004 (PI_SERVER->9202, snapshot DBs, PRISM_EVAL_STACK=1 north-star isolation)
cd /d C:\Users\<you>\Desktop\Prism-Agent\prism-api
set AUTOHOME_DB_PATH=C:/Users/<you>/Desktop/Prism-Agent/eval/snapshots/snap-20261012-1222/autohome.db
set PRISM_SENTIMENT_DB=C:/Users/<you>/Desktop/Prism-Agent/eval/snapshots/snap-20261012-1222/vehicle_sentiment.db
set PI_SERVER=http://127.0.0.1:9202
set SENTIMENT_BOARD=http://127.0.0.1:8100
set PRISM_DASHBOARDS=http://127.0.0.1:8110
set PRISM_DASHBOARDS_HTTP=http://127.0.0.1:8110
set PRISM_AUTOHOME_CACHE_TTL=0
set PRISM_EVAL_STACK=1
"C:\Users\<you>\Anaconda3\python.exe" -m uvicorn main:app --port 8004 > C:\Users\<you>\Desktop\Prism-Agent\logs\b1b-api.log 2>&1
