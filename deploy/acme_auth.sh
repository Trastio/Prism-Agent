#!/bin/bash
# Let's Encrypt DNS-01 授权钩子：把需要添加的 TXT 值落盘，再轮询阿里公共 DNS 直到记录生效
# 说明：境外校验服务器访问大陆 80 端口会被重置，故改用 DNS-01（不依赖入站连接）
DOMAIN="_acme-challenge.${CERTBOT_DOMAIN}"
VALUE="${CERTBOT_VALIDATION}"
echo "${DOMAIN} ${VALUE}" > /root/prism/deploy/acme_txt.txt
echo "请添加 TXT 记录：${DOMAIN} -> ${VALUE}"
for i in $(seq 1 360); do
  out=$(nslookup -type=TXT "${DOMAIN}" 223.5.5.5 2>/dev/null || true)
  if echo "${out}" | grep -q "${VALUE}"; then
    echo "TXT_OK after $i checks"
    exit 0
  fi
  sleep 10
done
echo "TXT_TIMEOUT：15 分钟内未查到 TXT 记录"
exit 1
