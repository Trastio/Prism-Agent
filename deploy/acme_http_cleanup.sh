#!/bin/bash
# Let's Encrypt HTTP-01 清理钩子：删除本次挑战文件
rm -f "/root/prism/deploy/acme/.well-known/acme-challenge/${CERTBOT_TOKEN}"
exit 0
