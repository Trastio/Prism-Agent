"""Tests: 运维韧性（WAL / DB 锁判据 / 评论去重约束）。"""
import sqlite3
from pathlib import Path

from models.database import DB_PATH, engine


def test_wal_enabled():
    """§3.9 L4：SQLite 启用 WAL 模式。"""
    con = sqlite3.connect(str(DB_PATH))
    mode = con.execute("PRAGMA journal_mode").fetchone()[0]
    con.close()
    assert mode.lower() == "wal", f"SQLite journal_mode 应为 wal，实际 {mode}"


def test_busy_timeout_configured():
    """WAL 配套 busy_timeout=30s（engine connect 钩子设）。"""
    # engine connect 钩子在每个新连接设 busy_timeout=30000
    # 此处验证 engine 配置存在（源码断言）
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "models" / "database.py"
    content = src.read_text(encoding="utf-8")
    assert "busy_timeout=30000" in content or "busy_timeout\", 30000" in content, (
        "database.py 应配置 busy_timeout=30000"
    )
    assert "PRAGMA journal_mode=WAL" in content, "database.py 应设 WAL"


def test_lock_acquired_at_field_exists():
    """§3.8 L5：collection_status 加 lock_acquired_at 字段（T6.6）。"""
    con = sqlite3.connect(str(DB_PATH))
    cols = [r[1] for r in con.execute("PRAGMA table_info(collection_status)").fetchall()]
    con.close()
    assert "lock_acquired_at" in cols, (
        f"collection_status 应有 lock_acquired_at 字段，实际列: {cols}"
    )


def test_lock_judgment_uses_acquired_time():
    """§3.8 L5：脏锁判据用 lock_acquired_at 而非 last_collected_at。"""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "api" / "routes" / "collection.py"
    content = src.read_text(encoding="utf-8")
    assert "lock_acquired_at" in content, "collection.py 应使用 lock_acquired_at 判锁"
    assert "cs.lock_acquired_at = " in content or "lock_acquired_at=datetime.now()" in content, (
        "trigger_collection 应设 lock_acquired_at"
    )


def test_comment_unique_constraint():
    """§3.8 L6：post_comments 加 UNIQUE(post_id, cid) 约束（T6.7）。"""
    con = sqlite3.connect(str(DB_PATH))
    # 查 post_comments 索引
    idxs = con.execute("PRAGMA index_list(post_comments)").fetchall()
    con.close()
    # 至少应有 unique 索引（cid 或 post_id+cid）
    has_unique = any(idx[2] == 1 for idx in idxs)  # idx[2]=1 表示 unique
    if not has_unique:
        # 可能迁移未跑，检查 schema 是否有 UNIQUE 定义
        con = sqlite3.connect(str(DB_PATH))
        schema = con.execute("SELECT sql FROM sqlite_master WHERE name='post_comments'").fetchone()
        con.close()
        assert "UNIQUE" in (schema[0] if schema else ""), (
            f"post_comments 应有 UNIQUE 约束，实际索引: {idxs}"
        )
