#!/bin/bash
# Let's Encrypt HTTP-01 授权钩子：写入挑战文件，并轮询公网确认内容已生效
# 用 CERTBOT_DOMAIN 拼自检地址，兼容多个域名（如 203.0.113.10.nip.io）
TOKEN="${CERTBOT_TOKEN}"
VALIDATION="${CERTBOT_VALIDATION}"
DIR="/root/prism/deploy/acme/.well-known/acme-challenge"
mkdir -p "${DIR}"
printf '%s' "${VALIDATION}" > "${DIR}/${TOKEN}"
chmod 644 "${DIR}/${TOKEN}"
echo "已写入挑战文件：${DIR}/${TOKEN}（域名 ${CERTBOT_DOMAIN}）"
for i in $(seq 1 60); do
  got=$(curl -s --max-time 5 "http://${CERTBOT_DOMAIN}/.well-known/acme-challenge/${TOKEN}" 2>/dev/null || true)
  if [ "${got}" = "${VALIDATION}" ]; then
    echo "HTTP01_OK after $i checks"
    exit 0
  fi
  sleep 5
done
echo "HTTP01_TIMEOUT：5 分钟内公网未读到正确挑战内容"
exit 1
