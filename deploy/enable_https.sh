#!/usr/bin/env bash
# 一键开启 HTTPS：生成 tls.d/prism-tls.conf + 证书落位 + nginx 重载
# 用法：bash enable_https.sh <域名> <证书pem路径> <私钥key路径>
# 例：  bash enable_https.sh prism-agent.example.com /root/prism/deploy/certs/prism.crt /root/prism/deploy/certs/prism.key
set -eu

DOMAIN=${1:?需要域名}
CRT=$(readlink -f "${2:?需要证书 pem}")
KEY=$(readlink -f "${3:?需要私钥 key}")
DEPLOY=/root/prism/deploy

mkdir -p "$DEPLOY/nginx/certs"
cp "$CRT" "$DEPLOY/nginx/certs/prism.crt"
cp "$KEY" "$DEPLOY/nginx/certs/prism.key"
chmod 644 "$DEPLOY/nginx/certs/prism.crt" "$DEPLOY/nginx/certs/prism.key"

cat > "$DEPLOY/nginx/tls.d/prism-tls.conf" <<EOF
# 由 enable_https.sh 生成：443 主站 + 80 跳转（domain=$DOMAIN）
server {
  listen 443 ssl;
  http2 on;
  server_name $DOMAIN;

  ssl_certificate     /etc/nginx/certs/prism.crt;
  ssl_certificate_key /etc/nginx/certs/prism.key;
  ssl_protocols       TLSv1.2 TLSv1.3;
  ssl_ciphers         HIGH:!aNULL:!MD5;
  ssl_session_cache   shared:SSL:10m;
  ssl_session_timeout 10m;

  root  /usr/share/nginx/html;
  index index.html;

  proxy_http_version 1.1;
  proxy_set_header Host              \$host;
  proxy_set_header X-Real-IP         \$remote_addr;
  proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto \$scheme;

  include /etc/nginx/locations.inc;
}

server {
  listen 80;
  server_name $DOMAIN;
  return 301 https://\$host\$request_uri;
}
EOF

cd "$DEPLOY"
docker compose exec -T prism-nginx nginx -t
docker compose exec -T prism-nginx nginx -s reload
echo "== HTTPS 已启用：https://$DOMAIN =="
