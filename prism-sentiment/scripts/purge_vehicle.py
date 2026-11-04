#!/usr/bin/env python
"""硬删除指定车系的全部数据（vehicle 记录 + 所有关联表）。

破坏性、不可逆操作：执行前自动按时间戳备份 data/vehicle_sentiment.db，
删除在单个事务内完成（异常自动回滚）。

关联表（均按 vehicle_id 直接关联，dialog_messages 经 conversation_id 间接）:
  collection_status / raw_posts / analyzed_posts / heat_metrics / reports
  dialog_conversations / post_comments / event_groups / vehicles

用法:
    python scripts/purge_vehicle.py <vehicle_id>
"""
import datetime
import os
import shutil
import sqlite3
import sys

VID = sys.argv[1] if len(sys.argv) > 1 else None
if not VID:
    sys.exit("用法: python scripts/purge_vehicle.py <vehicle_id>")

DB = os.getenv("DB_PATH", "data/vehicle_sentiment.db")

# 1) 删除前备份
ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
bak = f"{DB}.bak.{ts}-prepurge"
shutil.copy2(DB, bak)
print(f"[backup] {bak}")

con = sqlite3.connect(DB, timeout=10)
con.execute("PRAGMA busy_timeout=5000")  # 与服务进程写锁冲突时等待最多 5s
cur = con.cursor()

# 2) 校验目标存在
row = cur.execute("SELECT name, status FROM vehicles WHERE id=?", (VID,)).fetchone()
if not row:
    sys.exit(f"[error] vehicle {VID} 不存在")
print(f"[target] {row[0]} (status={row[1]}, id={VID})")

# 3) 直接 vehicle_id 关联的表
TABLES = [
    "collection_status", "raw_posts", "analyzed_posts", "heat_metrics",
    "reports", "dialog_conversations", "post_comments", "event_groups",
]

# 4) 删除前统计
before = {t: cur.execute(f"SELECT COUNT(*) FROM {t} WHERE vehicle_id=?", (VID,)).fetchone()[0] for t in TABLES}
before["dialog_messages(indirect)"] = cur.execute(
    "SELECT COUNT(*) FROM dialog_messages WHERE conversation_id IN "
    "(SELECT id FROM dialog_conversations WHERE vehicle_id=?)", (VID,)
).fetchone()[0]
print("[before]", before)

# 5) 事务删除（with con: 成功 commit / 异常 rollback）
try:
    with con:
        dm = cur.execute(
            "DELETE FROM dialog_messages WHERE conversation_id IN "
            "(SELECT id FROM dialog_conversations WHERE vehicle_id=?)", (VID,)
        ).rowcount
        for t in TABLES:
            cur.execute(f"DELETE FROM {t} WHERE vehicle_id=?", (VID,))
        cur.execute("DELETE FROM vehicles WHERE id=?", (VID,))
    print(f"[deleted] dialog_messages={dm} (+ 8 direct tables + vehicles)")
except Exception as e:
    sys.exit(f"[rollback] 删除失败已回滚: {e}")

# 6) 验证：目标清零
leak = []
for t in TABLES:
    n = cur.execute(f"SELECT COUNT(*) FROM {t} WHERE vehicle_id=?", (VID,)).fetchone()[0]
    if n:
        leak.append(f"{t}={n}")
v_left = cur.execute("SELECT COUNT(*) FROM vehicles WHERE id=?", (VID,)).fetchone()[0]
print(f"[verify] vehicles 剩余 {v_left} (期望 0)" + (f"  [WARN] 残留: {leak}" if leak else "  [OK] 关联表全清"))

# 7) 全局完整性：确认其他车系未受影响
others = cur.execute(
    "SELECT name, (SELECT COUNT(*) FROM raw_posts WHERE vehicle_id=v.id) "
    "FROM vehicles v ORDER BY name"
).fetchall()
print("[other vehicles intact]")
for name, posts in others:
    print(f"    {name}: raw_posts={posts}")
con.close()
print("[done]")
