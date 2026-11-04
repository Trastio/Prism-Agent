# 反代 location 集合（对应 prism-web/vite.config.ts proxy 表 16 条）
# HTTP(80) 与 HTTPS(443) 两个 server 共用本文件——改一处即两侧生效，避免双份漂移
# 依赖 server 级：root / proxy_set_header / map $connection_upgrade

# ── 1-13：prism-api:8002 ─────────────────────────────────────────────
# 健康检查：容器 healthcheck 与外部探活共用（A2，2026-11-02）——必须放在 SPA 兜底之前
location = /health { proxy_pass http://prism_api; }
# 每日巡检汇总（需登录；A2，2026-11-02）
location = /health/report { proxy_pass http://prism_api; }
# 登录端点单独限流（30 次/分钟/IP + burst15），避免被刷共享口令；/auth/me 不受此限
location = /auth/login {
  limit_req zone=login_zone burst=15 nodelay;
  proxy_pass http://prism_api;
}
location /auth          { proxy_pass http://prism_api; }

# SSE 流式：必须关缓冲 + 长超时，否则前端收不到逐字输出
# 不加 limit_conn：办公网多人共用一个出口 IP，按 IP 限并发会误伤自己人
location /chat/stream   {
  limit_req  zone=api_zone burst=20 nodelay;
  proxy_pass http://prism_api;
  proxy_buffering off;
  proxy_cache off;
  proxy_read_timeout 3600s;
  proxy_send_timeout 3600s;
  proxy_set_header Connection '';
}
location /chat/abort    { proxy_pass http://prism_api; }
location /dashboard     { proxy_pass http://prism_api; }
location /session       { proxy_pass http://prism_api; }
location /sentiment-board {
  proxy_pass http://prism_api;
  proxy_buffering off;
}
location /dash          { proxy_pass http://prism_api; }
location /ui-response   {
  proxy_pass http://prism_api;
  proxy_buffering off;
  proxy_read_timeout 3600s;
}
location /events        {
  proxy_pass http://prism_api;
  proxy_buffering off;
  proxy_read_timeout 3600s;
}
location /identity      { proxy_pass http://prism_api; }
location /export        { proxy_pass http://prism_api; }
location /tikhub        { proxy_pass http://prism_api; }
location /skills        { proxy_pass http://prism_api; }
# 用户反馈（2026-11-04）：主站右下角入口 → prism-api POST /feedback
location /feedback      { proxy_pass http://prism_api; }

# ── 14：WebSocket（prism-api 内部 ws 通道）
location /ws {
  proxy_pass http://prism_api;
  proxy_set_header Upgrade    $http_upgrade;
  proxy_set_header Connection $connection_upgrade;
  proxy_read_timeout 3600s;
}

# ── 15-16：prism-sentiment:8000（舆情 Board 静态资源与看板接口）
location /static        { proxy_pass http://sentiment_service; }
location /api/dashboard { proxy_pass http://sentiment_service; }

# ── ACME 证书校验路径（Let's Encrypt HTTP-01 用；走 nginx 提供，不必停服务）
location /.well-known/acme-challenge/ {
  root /var/www/acme;
  default_type text/plain;
}

# ── 入口 HTML 不缓存（2026-11-03）：assets 带 hash 可长缓存，但 index.html 必须每次回源，
#    否则部署后浏览器用旧 index 引用已删除的旧资源，出现白屏/旧布局（本次看板塌陷即此类）。
location = /index.html {
  add_header Cache-Control "no-cache, no-store, must-revalidate";
  try_files $uri =404;
}

# ── 前端 SPA 静态兜底
location / {
  try_files $uri $uri/ /index.html;
}
