import os
import logging
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from src.models.orm import Base, REVIEW_TAGS_UQ_NAME

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None

# 绝对路径，避免服务从非项目根目录启动时误连空库（P3-37）
DEFAULT_DB_URL = f"sqlite:///{Path(__file__).resolve().parent.parent.parent / 'data' / 'autohome.db'}"


def _set_sqlite_wal(dbapi_connection, connection_record):
    """Enable WAL mode for better concurrent read/write performance."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def init_db(db_url: str = ""):
    global _engine, _SessionLocal
    url = db_url or os.environ.get("DATABASE_URL", DEFAULT_DB_URL)
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    _engine = create_engine(url, echo=False, connect_args=connect_args)
    if url.startswith("sqlite"):
        event.listen(_engine, "connect", _set_sqlite_wal)
        logger.info("SQLite WAL mode enabled")
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)
    _migrate_new_columns(_engine)
    _migrate_review_tag_unique(_engine)
    _migrate_owner_reviews_index(_engine)


_MIGRATIONS = {
    "owner_reviews": [
        ("post_date", "TEXT"),
        ("exinfo", "JSON"),
        ("best_full_text", "TEXT"),   # dashboards-tri-polish
        ("worst_full_text", "TEXT"),  # dashboards-tri-polish
    ],
    "series_summaries": [
        ("onsell_review_count", "INTEGER"),
        ("level_rank", "INTEGER"),
        ("level_series_count", "INTEGER"),
        ("powertype", "INTEGER"),
        ("consumption_battery", "TEXT"),
    ],
    # dashboard-v10 Task 1.1：config_snapshots 加 decode_hit_rate 列（字体解码命中率）
    "config_snapshots": [
        ("decode_hit_rate", "REAL"),
    ],
}


def _migrate_new_columns(engine):
    """Add missing columns to existing SQLite tables."""
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.connect() as conn:
        for table_name, columns in _MIGRATIONS.items():
            try:
                result = conn.execute(
                    text(f"PRAGMA table_info({table_name})")
                )
                existing = {row[1] for row in result.fetchall()}
            except Exception:
                continue
            for col_name, col_type in columns:
                if col_name not in existing:
                    try:
                        conn.execute(
                            text(
                                f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"
                            )
                        )
                        conn.commit()
                        logger.info(f"Migration: added {table_name}.{col_name}")
                    except Exception as e:
                        logger.warning(f"Migration {table_name}.{col_name} failed: {e}")


_UQ_INDEX_NAME = REVIEW_TAGS_UQ_NAME  # 单源：与 orm.py 建表索引同名，两路径收敛


def _migrate_review_tag_unique(engine):
    """review_tags (review_id, tag_name, sentiment) 唯一性迁移（一次性、幂等）。

    存量库可能已有重复行：先按组去重保留 MIN(id)（首次提取为准，与"不重打"决策一致），
    再建唯一索引。门控：索引已存在则直接返回，避免每次启动全表扫描。
    新库由 ORM 建同名唯一 Index（create_all 即创建），门控命中后跳过——两路径收敛到同一索引。
    失败即中止（engine.begin() 抛异常整体回滚），下次启动重试——fail-loud 是有意为之，不做 warn-and-continue。
    """
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as conn:
        has_index = conn.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name=:n"
        ), {"n": _UQ_INDEX_NAME}).fetchone()
        if has_index:
            return
        deleted = conn.execute(text(
            "DELETE FROM review_tags WHERE id NOT IN "
            "(SELECT MIN(id) FROM review_tags GROUP BY review_id, tag_name, sentiment)"
        )).rowcount
        if deleted:
            logger.info(f"Migration: review_tags 去重删除 {deleted} 行重复标签")
        conn.execute(text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {_UQ_INDEX_NAME} "
            "ON review_tags(review_id, tag_name, sentiment)"
        ))
        logger.info(f"Migration: created unique index {_UQ_INDEX_NAME}")


def _migrate_owner_reviews_index(engine):
    """owner_reviews 覆盖索引 (model_id, post_date, fetched_at)（P1-7：口碑列表首屏加速）。
    口碑看板 GROUP BY model_id 聚合 COUNT/MAX(post_date)/MAX(fetched_at) 全部走覆盖索引，
    避免全表扫 123K 行 TEXT 列（5.5s → <0.1s）。门控：索引已存在则跳过。"""
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as conn:
        has_index = conn.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_owner_reviews_model_post'"
        )).fetchone()
        if has_index:
            return
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_owner_reviews_model_post "
            "ON owner_reviews(model_id, post_date, fetched_at)"
        ))
        logger.info("Migration: created covering index idx_owner_reviews_model_post")


def get_session() -> Session:
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _SessionLocal()


@contextmanager
def session_scope():
    """Context manager that commits on success, rolls back on exception, always closes."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
