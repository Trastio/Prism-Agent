import os
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event, text

DB_PATH = os.getenv("DB_PATH", "data/vehicle_sentiment.db")
# §3.9 L4：启用 WAL 模式，缓解后台采集写 + 前端读并发的 database is locked
# （2026-10-06 并发跑两个 daily_update 实测触发锁冲突）
engine = create_async_engine(
    f"sqlite+aiosqlite:///{DB_PATH}",
    echo=False,
    connect_args={"timeout": 30},  # 写锁等待 30s 而非立即报错
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    """每个新连接设 WAL + busy_timeout，避免并发读写锁冲突。"""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")  # 30s
    cur.close()


async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Schema migrations
# ---------------------------------------------------------------------------
# 版本化迁移注册表，替代旧的 try/except 吞错模式。
# 每个迁移带 check_column 幂等检查：列已存在（新库 create_all 已建，或老库已跑过）
# 时跳过 ALTER 只记版本；列缺失时执行 ALTER，失败则 raise（不吞错）。
MIGRATIONS = [
    {
        "version": 1,
        "name": "keywords_expanded_at",
        "sql": "ALTER TABLE vehicles ADD COLUMN keywords_expanded_at DATETIME",
        "check_column": {"table": "vehicles", "column": "keywords_expanded_at"},
    },
    {
        "version": 2,
        "name": "relevance_score",
        "sql": "ALTER TABLE raw_posts ADD COLUMN relevance_score FLOAT",
        "check_column": {"table": "raw_posts", "column": "relevance_score"},
    },
    {
        "version": 3,
        "name": "subject",
        "sql": "ALTER TABLE analyzed_posts ADD COLUMN subject VARCHAR",
        "check_column": {"table": "analyzed_posts", "column": "subject"},
    },
    {
        "version": 4,
        "name": "subject_name",
        "sql": "ALTER TABLE analyzed_posts ADD COLUMN subject_name VARCHAR DEFAULT ''",
        "check_column": {"table": "analyzed_posts", "column": "subject_name"},
    },
    {
        "version": 5,
        "name": "comment_dim_sentiment",
        "sql": "ALTER TABLE post_comments ADD COLUMN dim_sentiment TEXT",
        "check_column": {"table": "post_comments", "column": "dim_sentiment"},
    },
    {
        "version": 6,
        "name": "event_source",
        "sql": "ALTER TABLE event_groups ADD COLUMN source VARCHAR DEFAULT 'social'",
        "check_column": {"table": "event_groups", "column": "source"},
    },
    {
        "version": 7,
        "name": "comment_cid",
        "sql": "ALTER TABLE post_comments ADD COLUMN cid VARCHAR",
        "check_column": {"table": "post_comments", "column": "cid"},
    },
    {
        "version": 8,
        "name": "author_type",
        "sql": "ALTER TABLE raw_posts ADD COLUMN author_type VARCHAR DEFAULT 'organic'",
        "check_column": {"table": "raw_posts", "column": "author_type"},
    },
    {
        # v9: 缺陷话题簇落库表（Phase 9 结果持久化 + 端点 TTL 读库）。
        # 全新表——CREATE TABLE IF NOT EXISTS 幂等，无需 check_column（新表不存在
        # 时不冲突；create_all 已为新建内存库建表，老库跑此迁移补建）。
        "version": 9,
        "name": "defect_themes_table",
        "sql": "CREATE TABLE IF NOT EXISTS defect_themes (id TEXT PRIMARY KEY, vehicle_id TEXT NOT NULL, payload TEXT NOT NULL, computed_at DATETIME DEFAULT CURRENT_TIMESTAMP)",
    },
    {
        # v10: is_promo 导流号标记（D-3）。只对 auto_media 帖判信号词；
        # 车评号保留，导流号口径排除。
        "version": 10,
        "name": "is_promo",
        "sql": "ALTER TABLE raw_posts ADD COLUMN is_promo BOOLEAN DEFAULT 0",
        "check_column": {"table": "raw_posts", "column": "is_promo"},
    },
    {
        # v11: defect_themes 窗口列（code-review #1：缓存需区分时间窗）
        "version": 11,
        "name": "defect_window_cols",
        "sql": "ALTER TABLE defect_themes ADD COLUMN window_start TEXT",
        "check_column": {"table": "defect_themes", "column": "window_start"},
    },
    {
        # v12: defect_themes window_end 列（v11 漏加，code-review #1 补全）
        "version": 12,
        "name": "defect_window_end",
        "sql": "ALTER TABLE defect_themes ADD COLUMN window_end TEXT",
        "check_column": {"table": "defect_themes", "column": "window_end"},
    },
    {
        # v13: collection_status is_running 并发锁（F-1）
        "version": 13,
        "name": "collection_is_running",
        "sql": "ALTER TABLE collection_status ADD COLUMN is_running BOOLEAN DEFAULT 0",
        "check_column": {"table": "collection_status", "column": "is_running"},
    },
    {
        # v14: expansion_status 区分扩展成功/失败（audit Phase 1 T1.2）
        # v3 报告 §8.2：LLM 失败 return base_keywords 当成功，scheduler 无条件
        # 落库 + 置 keywords_expanded_at=now，7 天内不再重试 → 采集窄化无人知
        "version": 14,
        "name": "expansion_status",
        "sql": "ALTER TABLE vehicles ADD COLUMN expansion_status VARCHAR DEFAULT 'pending'",
        "check_column": {"table": "vehicles", "column": "expansion_status"},
    },
    {
        # v15: lock_acquired_at 加锁时刻（audit Phase 6 T6.6）
        # §3.8 L5：脏锁判据改用加锁时刻，last_collected_at 只在完成时更新无法区分
        "version": 15,
        "name": "lock_acquired_at",
        "sql": "ALTER TABLE collection_status ADD COLUMN lock_acquired_at DATETIME",
        "check_column": {"table": "collection_status", "column": "lock_acquired_at"},
    },
    {
        # v16: post_comments 唯一索引（audit Phase 6 T6.7）
        "version": 16,
        "name": "post_comments_unique_cid",
        "sql": "CREATE UNIQUE INDEX IF NOT EXISTS idx_post_comments_cid ON post_comments(post_id, cid) WHERE cid IS NOT NULL",
        "check_index": {"table": "post_comments", "index": "idx_post_comments_cid"},
    },
    {
        # v17: last_refreshed_at 展示字段（方案 C）
        # last_collected_at 是增量水位线不能用刷新时间覆盖（P0-1 漏采），新增专用展示字段
        "version": 17,
        "name": "last_refreshed_at",
        "sql": "ALTER TABLE collection_status ADD COLUMN last_refreshed_at DATETIME",
        "check_column": {"table": "collection_status", "column": "last_refreshed_at"},
    },
    {
        # v18: 预算护栏未采车登记列（2026-10-15 舆情降本 T2，方案 L6 v2）。
        # tikhub_daily_usage 表不需要迁移——create_all 对老库也会建新表。
        "version": 18,
        "name": "skipped_vehicles",
        "sql": "ALTER TABLE collection_status ADD COLUMN skipped_vehicles TEXT",
        "check_column": {"table": "collection_status", "column": "skipped_vehicles"},
    },
    {
        # v19: 评论极性直出新列（2026-10-16 舆情降本 T4，方案 §4 双轨设计）。
        # 老数据不迁移——读侧 derive_comment_sentiment 新列优先/老列回退。
        "version": 19,
        "name": "comment_polarity",
        "sql": "ALTER TABLE post_comments ADD COLUMN comment_polarity TEXT",
        "check_column": {"table": "post_comments", "column": "comment_polarity"},
    },
]


async def _column_exists(conn, table, column):
    """通过 PRAGMA table_info 查列是否已存在（幂等检查）。"""
    rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
    return any(r[1] == column for r in rows)


async def _index_exists(conn, table, index):
    """通过 PRAGMA index_list 查索引是否已存在（幂等检查）。"""
    rows = (await conn.execute(text(f"PRAGMA index_list({table})"))).fetchall()
    return any(r[1] == index for r in rows)


async def _run_migrations(conn):
    """执行版本化迁移：只跑未应用的，幂等检查列存在性，失败 raise 不吞错。"""
    await conn.execute(text(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    ))
    applied = {
        r[0]
        for r in (await conn.execute(text("SELECT version FROM schema_migrations"))).fetchall()
    }
    now = datetime.now().isoformat()
    for m in MIGRATIONS:
        if m["version"] in applied:
            continue
        # 幂等检查：列已存在（新库 create_all 已建 / 老库已跑过）时跳过 ALTER 只记版本
        if m.get("check_column"):
            t, c = m["check_column"]["table"], m["check_column"]["column"]
            if await _column_exists(conn, t, c):
                await conn.execute(
                    text(
                        "INSERT INTO schema_migrations (version, name, applied_at) "
                        "VALUES (:v, :n, :a)"
                    ),
                    {"v": m["version"], "n": m["name"], "a": now},
                )
                continue
        # 幂等检查：索引已存在时跳过 CREATE 只记版本
        if m.get("check_index"):
            t, idx = m["check_index"]["table"], m["check_index"]["index"]
            if await _index_exists(conn, t, idx):
                await conn.execute(
                    text(
                        "INSERT INTO schema_migrations (version, name, applied_at) "
                        "VALUES (:v, :n, :a)"
                    ),
                    {"v": m["version"], "n": m["name"], "a": now},
                )
                continue
        # 列缺失：执行 ALTER（失败会 raise，不吞错）
        await conn.execute(text(m["sql"]))
        await conn.execute(
            text(
                "INSERT INTO schema_migrations (version, name, applied_at) "
                "VALUES (:v, :n, :a)"
            ),
            {"v": m["version"], "n": m["name"], "a": now},
        )


async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    from models.schemas import Base as SchemaBase  # noqa: F401  确保模型注册
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)
        # D-1：业务索引（IF NOT EXISTS 幂等，随数据增长防线性劣化）
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS idx_raw_posts_vehicle ON raw_posts(vehicle_id)",
            "CREATE INDEX IF NOT EXISTS idx_post_comments_vehicle ON post_comments(vehicle_id)",
            "CREATE INDEX IF NOT EXISTS idx_analyzed_posts_vehicle ON analyzed_posts(vehicle_id)",
            "CREATE INDEX IF NOT EXISTS idx_raw_posts_published ON raw_posts(published_at)",
            "CREATE INDEX IF NOT EXISTS idx_post_comments_post ON post_comments(post_id)",
            # #13：高频 JOIN/过滤键补齐
            "CREATE INDEX IF NOT EXISTS idx_analyzed_posts_post_id ON analyzed_posts(post_id)",
            "CREATE INDEX IF NOT EXISTS idx_analyzed_posts_subject ON analyzed_posts(subject)",
            "CREATE INDEX IF NOT EXISTS idx_raw_posts_author_type ON raw_posts(author_type)",
            "CREATE INDEX IF NOT EXISTS idx_raw_posts_analysis_status ON raw_posts(analysis_status)",
        ]:
            await conn.execute(text(idx_sql))


async def get_session():
    async with async_session() as session:
        yield session
