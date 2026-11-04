#!/usr/bin/env bash
# 校验共享口令轮换：旧 666666 应 401，新口令应 200
set -u
echo "old=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"admin","password":"CHANGE_ME_OLD_PW"}')"
echo "new=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"admin","password":"CHANGE_ME_ADMIN_PW"}')"
echo "cookie=$(curl -s -c /tmp/ck2.txt -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1/auth/login \
  -H 'Content-Type: application/json' -d '{"username":"admin","password":"CHANGE_ME_ADMIN_PW"}')"
curl -s -b /tmp/ck2.txt http://127.0.0.1/auth/me; echo
