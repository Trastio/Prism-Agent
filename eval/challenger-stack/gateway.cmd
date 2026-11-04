@echo off
rem B1b challenger stack - challenger gateway :9202 (-e explicit load from extensions-available + PRISM_PI_CWD empty dir double-guard; no trajectory/no langfuse env)
cd /d C:\Users\<you>\Desktop\Prism-Agent
set PRISM_GATEWAY_PORT=9202
set PRISM_PI_EXTENSION=.pi/extensions-available/challenger-b1/index.ts
set PRISM_PI_CWD=C:\Users\<you>\Desktop\Prism-Agent\eval\challenger-cwd
set PRISM_CHALLENGER=1
set PRISM_CHALLENGER_DB=C:/Users/<you>/Desktop/Prism-Agent/eval/snapshots/snap-20261012-1222/autohome.db
set PRISM_AUTO_APPROVE_UI=1
set PRISM_EVAL_UI_SIM=1
set PRISM_FASTAPI=http://127.0.0.1:8004
node prism-api\pi_gateway.mjs > C:\Users\<you>\Desktop\Prism-Agent\logs\b1b-gateway.log 2>&1
