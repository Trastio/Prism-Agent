"""platform 命名迁移脚本测试（主题 B Task4）。

scripts/ 非包（无 __init__.py），用 importlib 按文件路径加载脚本模块。
"""
import importlib.util
import sqlite3
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "migrate_platform_names.py"
_spec = importlib.util.spec_from_file_location("migrate_platform_names", _SCRIPT)
_migrate_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migrate_mod)
migrate = _migrate_mod.migrate
TABLES = _migrate_mod.TABLES


def _make_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    for t in TABLES:
        con.execute(f"CREATE TABLE {t} (id TEXT PRIMARY KEY, platform TEXT)")
    return con


def test_migrates_abbreviations_to_full():
    con = _make_db()
    con.executemany(
        "INSERT INTO raw_posts (id, platform) VALUES (?, ?)",
        [("r1", "dy"), ("r2", "douyin"), ("r3", "xhs")],
    )
    con.executemany(
        "INSERT INTO post_comments (id, platform) VALUES (?, ?)",
        [("c1", "wb"), ("c2", "ks")],
    )
    con.commit()

    updated = migrate(con)

    raws = [r[0] for r in con.execute("SELECT platform FROM raw_posts ORDER BY id").fetchall()]
    cmts = [r[0] for r in con.execute("SELECT platform FROM post_comments ORDER BY id").fetchall()]
    # dy→douyin，douyin 不变，xhs→xiaohongshu；wb→weibo，ks→kuaishou
    assert raws == ["douyin", "douyin", "xiaohongshu"]
    assert cmts == ["weibo", "kuaishou"]
    assert updated == 4  # dy, xhs + wb, ks


def test_idempotent_when_no_abbreviations():
    con = _make_db()
    con.executemany(
        "INSERT INTO raw_posts (id, platform) VALUES (?, ?)",
        [("r1", "douyin"), ("r2", "weibo")],
    )
    con.commit()
    assert migrate(con) == 0


def test_dry_run_does_not_persist():
    con = _make_db()
    con.execute("INSERT INTO raw_posts (id, platform) VALUES ('r1', 'dy')")
    con.commit()
    assert migrate(con, dry_run=True) == 1
    plat = con.execute("SELECT platform FROM raw_posts WHERE id='r1'").fetchone()[0]
    assert plat == "dy"  # dry-run 回滚，未持久化


def test_running_twice_is_noop():
    con = _make_db()
    con.executemany(
        "INSERT INTO post_comments (id, platform) VALUES (?, ?)",
        [("c1", "xhs"), ("c2", "dy")],
    )
    con.commit()
    migrate(con)
    assert migrate(con) == 0  # 第二次跑：已无缩写


def test_unknown_platforms_untouched():
    con = _make_db()
    con.execute("INSERT INTO raw_posts (id, platform) VALUES ('r1', 'news'),('r2','foobar')")
    con.commit()
    assert migrate(con) == 0
    plats = sorted(r[0] for r in con.execute("SELECT platform FROM raw_posts").fetchall())
    assert plats == ["foobar", "news"]
