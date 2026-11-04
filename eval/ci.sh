#!/usr/bin/env bash
# Prism-Agent · 评测门禁 CI 骨架（T-9.3）
# 触发：变更 src/verify/ 或 .pi/extensions/ 后
# 发版门槛 4 条件（D1 接线，2026-10-14 评估迭代基建包）：
#   veto零命中 + Wilcoxon显著(delta>0.1) + 保留集CI下界>0 + 成本CI上界<预算
#   —— 由 eval/stats.py 配对 baseline/candidate 判定（替换原"通过率≥70%"简化逻辑）
set -e
cd "$(dirname "$0")/.."

# P0（2026-10-26）：runner 有 env-guard，未设 PRISM_API_BASE 会拒跑（防漏传打生产栈）。
# CI 必须自带 eval 栈 + 独立轨迹文件；栈由本脚本拉起，退出时回收。
export PRISM_API_BASE=http://127.0.0.1:8003
export PRISM_TRAJECTORY_FILE="$PWD/eval/trajectories/eval-trajectories.jsonl"
mkdir -p eval/trajectories
SNAP=$(ls -d eval/snapshots/snap-* 2>/dev/null | sort | tail -1 | xargs -n1 basename 2>/dev/null || true)
cleanup() { python prism.py eval stop >/dev/null 2>&1 || true; }
trap cleanup EXIT
if [ -n "$SNAP" ]; then
  echo "=== 0. 启动 eval 栈（快照 $SNAP）==="
  python prism.py eval start "$SNAP"
else
  echo "无快照可启（eval/snapshots/snap-*）——runner 将被 env-guard/快照闸拒跑" >&2
  exit 1
fi

echo "=== 1. smoke:all ==="
npm run smoke:all

echo "=== 2. 评估批跑（全量题集：75 静态题 + 动态题）==="
node eval/runner.mjs 2>&1 | tee eval/eval-report.json.txt

echo "=== 2.5 出口闸评估门 E1-E9（不绿不合档）==="
node eval/runner.mjs --gate 2>&1 | tee eval/gate-report.json.txt

echo "=== 3. 发版门槛四条件（stats.py 配对判定）==="
CURRENT_RUN_ID=$(python -c "import json;print(json.load(open('eval/eval-report.json',encoding='utf-8'))['run_id'])")
# baseline = eval/reports/ 下除本次 run 外最新的 eval-*.json（mtime 序）
BASELINE=$(ls -t eval/reports/eval-*.json 2>/dev/null | grep -v "/${CURRENT_RUN_ID}.json$" | head -1 || true)
if [ -z "$BASELINE" ]; then
  echo "首跑豁免：eval/reports/ 无既有基线报告（本次 run 即 v1 基线，四条件自下次批跑起配对）"
else
  echo "baseline = $BASELINE"
  # 2026-10-29：门槛判定已进 runner 主流程（report.release_gate，基线选择含题集重叠≥60% + 判据指纹校验，
  # 比此处 ls -t 取最新更严）。CI 只读判定结果，不再二次跑 stats.py——否则两处可能选到不同基线、
  # 且同一 run 会在 EVAL_STATUS.md 里被记两行。
  python -c "import json;r=json.load(open('eval/reports/${CURRENT_RUN_ID}.json',encoding='utf-8'));g=r.get('release_gate');print('[gate]',json.dumps(g,ensure_ascii=False)) if g else print('[gate] 未判定:',r.get('release_gate_error'))"
fi
