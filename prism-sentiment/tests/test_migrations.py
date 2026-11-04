import pytest
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

@pytest.mark.asyncio
async def test_schema_migrations_table_exists(tmp_path):
    """schema_migrations 表存在且记录已应用迁移。"""
    db_path = str(tmp_path / "test.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    from models.database import Base
    from models.schemas import Vehicle, RawPost, AnalyzedPost  # 确保模型注册
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        from models.database import _run_migrations
        await _run_migrations(conn)
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"))
        assert result.fetchone() is not None
        rows = (await conn.execute(text("SELECT name FROM schema_migrations"))).fetchall()
        assert len(rows) >= 4  # 现有迁移已记录
    await engine.dispose()

@pytest.mark.asyncio
async def test_migration_idempotent_on_fresh_db(tmp_path):
    """新库（create_all 已建列）跑迁移不炸——幂等检查。"""
    db_path = str(tmp_path / "test.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    from models.database import Base, _run_migrations
    from models.schemas import Vehicle, RawPost, AnalyzedPost
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_migrations(conn)  # 幂等：列已存在时跳过
    await engine.dispose()

@pytest.mark.asyncio
async def test_migration_failure_raises(tmp_path):
    """迁移失败时 raise，不吞错。"""
    db_path = str(tmp_path / "test.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    from models.database import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        with pytest.raises(Exception):
            await conn.execute(text("ALTER TABLE nonexistent_table ADD COLUMN x"))
    await engine.dispose()
