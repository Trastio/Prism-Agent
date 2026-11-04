#!/usr/bin/env bash
# Prism 云端全链路 smoke（E1，2026-11-02）
# 覆盖：容器 / /health / 未登录 401 / 登录 / 四看板 / 巡检报告 / 埋点探针 / 对话
# 用法（在 ECS 本机）：
#   PRISM_SMOKE_USER=admin PRISM_SMOKE_PASS='***' bash /root/prism/deploy/smoke_remote.sh
# 说明：口令只从环境变量读取，不写入脚本；探针事件 event_type=smoke_probe，由 ops 侧排除。
set -u

BASE="${PRISM_SMOKE_BASE:-https://127.0.0.1}"
HOSTHDR="${PRISM_SMOKE_HOST:-prism-agent.example.com}"
USER="${PRISM_SMOKE_USER:-admin}"
PASS="${PRISM_SMOKE_PASS:-}"
COOKIE=$(mktemp)
FAIL=0

ok()  { echo "PASS  $1"; }
bad() { echo "FAIL  $1"; FAIL=$((FAIL + 1)); }

# 1. 容器状态（5 个常驻）
N=$(docker ps --format '{{.Status}}' | grep -cE 'healthy|Up')
[ "$N" -ge 5 ] && ok "containers $N/5" || bad "containers $N/5"

# 2. /health 必须是 JSON（不是 SPA HTML）
H=$(curl -s -k -m 8 -H "Host: $HOSTHDR" "$BASE/health")
echo "$H" | grep -q '"status":"ok"' && ok "/health json" || bad "/health -> ${H:0:120}"

# 3. 未登录受保护路由必须 401
C=$(curl -s -k -o /dev/null -w '%{http_code}' -m 10 -H "Host: $HOSTHDR" "$BASE/identity")
[ "$C" = "401" ] && ok "unauth 401" || bad "unauth -> $C"

# 4. 登录
if [ -n "$PASS" ]; then
  C=$(curl -s -k -o /dev/null -w '%{http_code}' -m 15 -c "$COOKIE" -X POST \
      -H "Host: $HOSTHDR" -H 'Content-Type: application/json' \
      -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" "$BASE/auth/login")
  [ "$C" = "200" ] && ok "login" || bad "login -> $C"
else
  bad "login skipped (PRISM_SMOKE_PASS empty)"
fi

# 5. 四个看板（配置/口碑/销量/舆情）
for p in /dash/config /dash/koubei /dash/market; do
  R=$(curl -s -k -b "$COOKIE" -o /tmp/smoke_body -w '%{http_code}' -m 25 -H "Host: $HOSTHDR" "$BASE$p")
  SZ=$(wc -c < /tmp/smoke_body)
  if [ "$R" = "200" ] && [ "$SZ" -gt 5000 ]; then ok "board $p ($SZ)"; else bad "board $p -> $R ($SZ)"; fi
done
R=$(curl -s -k -b "$COOKIE" -o /tmp/smoke_body -w '%{http_code}' -m 25 -H "Host: $HOSTHDR" \
    "$BASE/sentiment-board/api/dashboard/fleet-overview")
SZ=$(wc -c < /tmp/smoke_body)
if [ "$R" = "200" ] && [ "$SZ" -gt 1000 ]; then ok "board sentiment ($SZ)"; else bad "board sentiment -> $R ($SZ)"; fi

# 6. 每日巡检报告（登录后 200）
R=$(curl -s -k -b "$COOKIE" -o /tmp/smoke_hr -w '%{http_code}' -m 10 -H "Host: $HOSTHDR" "$BASE/health/report")
[ "$R" = "200" ] && ok "health report" || bad "health report -> $R"

# 7. 埋点探针（写入后由 ops 按 event_type 排除）
R=$(curl -s -k -b "$COOKIE" -o /tmp/smoke_ev -w '%{http_code}' -m 10 -X POST \
    -H "Host: $HOSTHDR" -H 'Content-Type: application/json' \
    -d '{"events":[{"event_type":"smoke_probe","value":"e1"}]}' "$BASE/events")
if grep -q '"inserted":1' /tmp/smoke_ev; then ok "events probe"; else bad "events probe -> $R $(cat /tmp/smoke_ev)"; fi

# 8. 对话（流式：至少 1 个 text_delta + 1 个 settled）
R=$(curl -s -k -N -b "$COOKIE" -m 150 -X POST -H "Host: $HOSTHDR" -H 'Content-Type: application/json' \
    -d '{"message":"你好，一句话说明你能做什么"}' "$BASE/chat/stream" -o /tmp/smoke_chat -w '%{http_code}')
TD=$(grep -c '"type":"text_delta"' /tmp/smoke_chat || true)
ST=$(grep -c '"type":"settled"' /tmp/smoke_chat || true)
if [ "$R" = "200" ] && [ "$TD" -gt 0 ] && [ "$ST" -gt 0 ]; then
  ok "chat (delta=$TD settled=$ST)"
else
  bad "chat -> $R delta=$TD settled=$ST"
fi

rm -f "$COOKIE" /tmp/smoke_body /tmp/smoke_hr /tmp/smoke_ev /tmp/smoke_chat
echo "----"
if [ "$FAIL" -eq 0 ]; then echo "SMOKE PASS"; exit 0; else echo "SMOKE FAIL($FAIL)"; exit 1; fi
