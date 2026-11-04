#!/bin/bash
# Let's Encrypt DNS-01 清理钩子：仅记录，TXT 记录由人工在云解析删除
echo "cleanup: ${CERTBOT_DOMAIN} ${CERTBOT_VALIDATION}" >> /root/prism/deploy/acme_cleanup.log
exit 0
