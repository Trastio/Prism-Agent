#!/usr/bin/env bash
# Prism 云端每日备份（SQLite 在线备份 API，容器运行中也可安全备份）
# 安装：crontab -e 加入  0 3 * * * /root/prism/deploy/backup.sh >> /root/prism/logs/backup.log 2>&1
set -u

DATA=/root/prism/data
BK=/root/prism/backup
KEEP=7
STAMP=$(date +%Y%m%d)
mkdir -p "$BK" /root/prism/logs

python3 - "$DATA" "$BK" "$STAMP" <<'PY'
import sqlite3
import sys
from pathlib import Path

data, bk, stamp = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
targets = ['autohome.db', 'vehicle_sentiment.db', 'prism_events.db', 'api/users.json']
for name in targets:
    src = data / name
    if not src.exists():
        print(f'skip(missing) {name}')
        continue
    if name.endswith('.json'):
        import shutil
        dst = bk / f'{src.stem}-{stamp}.json'
        shutil.copy2(src, dst)
        print(f'json {dst.name}')
        continue
    dst = bk / f'{Path(name).stem}-{stamp}.db'
    con_src = sqlite3.connect(f'file:{src}?mode=ro', uri=True)
    con_dst = sqlite3.connect(dst)
    with con_dst:
        con_src.backup(con_dst)
    con_dst.close()
    con_src.close()
    print(f'db {dst.name} {dst.stat().st_size} bytes')
PY

# 清理超过 KEEP 天的旧备份
find "$BK" -maxdepth 1 -type f \( -name '*.db' -o -name '*.json' \) -mtime +$KEEP -delete
echo "[$(date '+%F %T')] backup done, kept last $KEEP days, dir=$(du -sh "$BK" | cut -f1)"
