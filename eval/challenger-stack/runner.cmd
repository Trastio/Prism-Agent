@echo off
rem B1b challenger arm B full run (63 tasks) - detached, survives session exit
cd /d C:\Users\<you>\Desktop\Prism-Agent
set PRISM_API_BASE=http://127.0.0.1:8004
set PRISM_CHALLENGER_ARM=b
set PRISM_EVAL_WEB=off
set PRISM_EVAL_RUN_ID=challenger-b1b
node eval\runner.mjs --challenger --set=all > C:\Users\<you>\Desktop\Prism-Agent\eval\reports\challenger-b1b-runlog3.txt 2>&1
