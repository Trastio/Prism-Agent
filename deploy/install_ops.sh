#!/usr/bin/env bash
# 云端运维安装：1) 每日备份 cron  2) 证书续期 cron（有域名后自动生效）
set -u

# ── 1. 每日备份（03:10）──
TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v 'backup.sh' | grep -v 'certbot renew' > "$TMP" || true
echo '10 3 * * * /root/prism/deploy/backup.sh >> /root/prism/logs/backup.log 2>&1' >> "$TMP"
# 证书续期（有证书时才有意义；无证书时 certbot renew 直接返回 0）
echo '20 3 * * * /usr/bin/certbot renew --quiet --deploy-hook "docker exec prism-prism-nginx-1 nginx -s reload" >> /root/prism/logs/renew.log 2>&1' >> "$TMP"
crontab "$TMP"
rm -f "$TMP"
echo '== crontab =='
crontab -l
