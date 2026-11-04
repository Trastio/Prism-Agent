import asyncio
import os
import pytest
import pytest_asyncio

TEST_DB_PATH = "data/test_vehicle_sentiment.db"


@pytest.fixture(autouse=True)
def _no_real_collector_keys(monkeypatch):
    """隔离真实采集凭证：删 env key + 打空 load_dotenv。

    保证任何测试里 TikHubClient 构造后都处于未配置态（is_available=False），
    杜绝真实 .env 的 TIKHUB_KEY 撞出真网络路径。需要可用 collector 的测试
    自行 patch is_available 或注入假 client。
    """
    monkeypatch.delenv("TIKHUB_KEY", raising=False)
    monkeypatch.setattr("pipeline.collectors.tikhub_collector.load_dotenv",
                        lambda *a, **k: False)


@pytest.fixture(autouse=True)
def _budget_counter_tmp_db(monkeypatch, tmp_path):
    """预算计数器隔离（2026-10-15 T2）：_send 现在会写 tikhub_daily_usage，
    任何走到 TikHubClient._send 的既有测试（MockTransport 类）都会计数——
    不隔离会把计数行写进生产库 data/vehicle_sentiment.db。逐测试指到临时库
    （budget._db_path 每次读 env，monkeypatch 即时生效）。"""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "budget_counter_test.db"))


# F-9：event_loop fixture 已移除（pytest_asyncio 新版自带，原写法触发 DeprecationWarning）


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    os.makedirs("data", exist_ok=True)
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(f"sqlite+aiosqlite:///{TEST_DB_PATH}", echo=False)

    from models.schemas import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


@pytest_asyncio.fixture
async def db_session(db_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()

@pytest.fixture(autouse=True)
def _tag_gate_open():
    """TAG_IN_SERVICE 恒开（B 决策门）：测试环境不受服务内打标关闭影响。

    POLARITY_ENGINE 钉 local（2026-10-20 引擎切换）：存量打标测试走本地
    路径（mock 模型），不碰 DeepSeek 网络；deepseek 路径由
    test_deepseek_polarity.py 显式 setenv 覆盖。"""
    os.environ["TAG_IN_SERVICE"] = "1"
    os.environ["POLARITY_ENGINE"] = "local"
    yield
    os.environ.pop("TAG_IN_SERVICE", None)
    os.environ.pop("POLARITY_ENGINE", None)
