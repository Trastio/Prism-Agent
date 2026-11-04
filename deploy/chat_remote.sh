#!/usr/bin/env bash
# 云端端到端对话冒烟（完整留存 SSE 流，便于校验数字）
set -u
USER_ID="${1:-cloud-smoke}"
cd /root/prism/deploy || exit 1

curl -s -o /dev/null -c /tmp/prism_cookie.txt \
  -X POST http://127.0.0.1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"CHANGE_ME_ADMIN_PW"}'

START=$(date +%s)
curl -sN --max-time 300 -b /tmp/prism_cookie.txt \
  -X POST http://127.0.0.1/chat/stream -H 'Content-Type: application/json' \
  -d "{\"message\":\"银河E5 2026年9月销量多少\",\"user_id\":\"${USER_ID}\"}" \
  > /tmp/chat_full.log
END=$(date +%s)

echo "user=${USER_ID} elapsed=$((END-START))s bytes=$(wc -c < /tmp/chat_full.log)"
echo "settled=$(grep -c 'settled' /tmp/chat_full.log || true)"
echo "tool_call=$(grep -c 'tool_call' /tmp/chat_full.log || true)"
echo "命中数字："
grep -o '3,355\|3355\|24\.4\|-67\.7\|10\.64' /tmp/chat_full.log | sort | uniq -c || true
echo "回答尾部："
python3 - <<'PY'
import json
texts = []
for line in open('/tmp/chat_full.log', encoding='utf-8', errors='ignore'):
    line = line.strip()
    if not line or not line.startswith('{'):
        continue
    try:
        ev = json.loads(line)
    except Exception:
        continue
    if ev.get('type') == 'text_delta':
        texts.append(ev.get('data', {}).get('text', ''))
full = ''.join(texts)
print(full[-900:] if full else '(无 text_delta)')
PY
