#!/usr/bin/env bash
# 验证登录限流（6r/m + burst5）：连续 8 次错误口令，应出现 429
set -u
for i in $(seq 1 8); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1/auth/login \
    -H 'Content-Type: application/json' -d '{"username":"probe","password":"bad"}')
  echo "try$i=$code"
done
