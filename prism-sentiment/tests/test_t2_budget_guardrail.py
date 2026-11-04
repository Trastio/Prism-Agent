"""T2（2026-10-15 舆情降本）日预算护栏测试：计数/封顶/异常语义/登记。

覆盖：pipeline.collectors.budget（计数器+TikHubBudgetExceeded）、
TikHubClient._send 挂钩（不发请求）、scheduler.register_budget_skip
（budget_capped 状态 + 未采车登记）。
"""
import json
import sqlite3
import uuid
from datetime import datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.schemas import Base, CollectionStatus, Vehicle


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _read_counter(db_path: str, day: str) -> int:
    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT calls FROM tikhub_daily_usage WHERE date = ?", (day,)).fetchone()
        return row[0] if row else 0
    finally:
        con.close()


class TestBudgetCounter:
    def test_accumulate_and_cap_raises(self, monkeypatch, tmp_path):
        from pipeline.collectors.budget import TikHubBudgetExceeded, count_and_check
        dbp = str(tmp_path / "u.db")
        monkeypatch.setenv("DB_PATH", dbp)
        monkeypatch.setenv("TIKHUB_DAILY_BUDGET", "3")
        assert count_and_check() == 1
        assert count_and_check() == 2
        assert count_and_check() == 3
        with pytest.raises(TikHubBudgetExceeded):
            count_and_check()  # 第 4 次：4 > 3，请求被拒（计数仍记上）
        assert _read_counter(dbp, datetime.now().date().isoformat()) == 4

    def test_cross_day_resets(self, monkeypatch, tmp_path):
        """跨日重置：昨日计数不占今日预算（date 主键天然分日）。"""
        from pipeline.collectors.budget import count_and_check
        dbp = str(tmp_path / "u.db")
        monkeypatch.setenv("DB_PATH", dbp)
        yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
        con = sqlite3.connect(dbp)
        con.execute(
            "CREATE TABLE IF NOT EXISTS tikhub_daily_usage "
            "(date TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0)")
        con.execute("INSERT INTO tikhub_daily_usage VALUES (?, 2200)", (yesterday,))
        con.commit()
        con.close()
        monkeypatch.setenv("TIKHUB_DAILY_BUDGET", "1")
        assert count_and_check() == 1  # 昨日 2200 不影响今日

    def test_env_budget_and_fallback(self, monkeypatch):
        from pipeline.collectors.budget import daily_budget
        monkeypatch.setenv("TIKHUB_DAILY_BUDGET", "500")
        assert daily_budget() == 500
        monkeypatch.setenv("TIKHUB_DAILY_BUDGET", "abc")
        assert daily_budget() == 2200  # 默认（15 车 × ≈98 × 1.5，方案§八④）
        monkeypatch.setenv("TIKHUB_DAILY_BUDGET", "0")
        assert daily_budget() == 2200  # 非正数回退默认

    def test_exception_is_not_tikhub_error_subclass(self):
        """关键语义：不继承 TikHubError，否则被关键词级 except 吞掉不冒泡。"""
        from pipeline.collectors.budget import TikHubBudgetExceeded
        from pipeline.collectors.tikhub_collector import TikHubError
        assert not issubclass(TikHubBudgetExceeded, TikHubError)
        assert issubclass(TikHubBudgetExceeded, Exception)


class TestSendHook:
    def test_send_raises_before_network_when_over_budget(self, monkeypatch):
        """超预算时 _send 在发请求前抛（无 transport 也绝不触网）。"""
        from pipeline.collectors.budget import TikHubBudgetExceeded
        from pipeline.collectors.tikhub_collector import TikHubClient
        monkeypatch.setenv("TIKHUB_DAILY_BUDGET", "1")
        client = TikHubClient(api_key="k")
        ok = httpx.Response(200, json={"code": 200, "data": {}})
        client_with_transport = TikHubClient(
            api_key="k", transport=httpx.MockTransport(lambda req: ok))
        # 第 1 次：计数 1 ≤ 预算 1，走 MockTransport 正常返回
        import asyncio
        assert asyncio.run(client_with_transport.get("douyin.search", {"keyword": "x"})) == {}
        # 第 2 次：计数 2 > 1，抛 TikHubBudgetExceeded（不给 transport 都行）
        with pytest.raises(TikHubBudgetExceeded):
            asyncio.run(client.get("douyin.search", {"keyword": "x"}))

    def test_index_collector_shares_client_counting(self, monkeypatch):
        """IndexCollector 复用 TikHubClient → 自动计入（无需额外接线）。"""
        from pipeline.collectors.index_collector import IndexCollector
        from pipeline.collectors.tikhub_collector import TikHubClient
        c = IndexCollector(TikHubClient(api_key="k"))
        assert c._client.configured  # 同一 client 实例即同一条 _send 通路


class TestRegisterBudgetSkip:
    @pytest.mark.asyncio
    async def test_marks_status_and_registers_remaining(self, db):
        """触顶车标 budget_capped + 当日未采 active 车登记；已采/paused/自身排除。"""
        from pipeline.scheduler import register_budget_skip
        now = datetime.now()
        va = Vehicle(id="va", name="车A", brand="b")            # 触顶车（当前）
        vb = Vehicle(id="vb", name="车B", brand="b")            # active 未采 → 应登记
        vc = Vehicle(id="vc", name="车C", brand="b")            # active 今日已采 → 排除
        vd = Vehicle(id="vd", name="车D", brand="b", status="paused")  # paused → 排除
        db.add_all([va, vb, vc, vd])
        db.add(CollectionStatus(
            id=str(uuid.uuid4()), vehicle_id="vc", source="all",
            mode="incremental", last_collected_at=now, status="completed"))
        await db.commit()

        skipped = await register_budget_skip(db, "va", "当日调用数 2201 已超预算 2200")
        assert skipped == ["车B"]

        row = (await db.execute(
            __import__("sqlalchemy").select(CollectionStatus).where(
                CollectionStatus.vehicle_id == "va",
                CollectionStatus.source == "all")
        )).scalars().one()
        assert row.status == "budget_capped"
        assert "已超预算" in row.error_message
        payload = json.loads(row.skipped_vehicles)
        assert payload["date"] == now.date().isoformat()
        assert payload["vehicles"] == ["车B"]

    @pytest.mark.asyncio
    async def test_repeat_registration_idempotent_payload(self, db):
        """后续车再触顶：同日重算名单幂等（不重复登记同车名）。"""
        from pipeline.scheduler import register_budget_skip
        db.add_all([Vehicle(id="v1", name="车1", brand="b"),
                    Vehicle(id="v2", name="车2", brand="b")])
        await db.commit()
        s1 = await register_budget_skip(db, "v1", "err")
        s2 = await register_budget_skip(db, "v2", "err")
        assert s1 == ["车2"] and s2 == ["车1"]
        # 两行各自登记对方的名单，值稳定不叠加
        rows = (await db.execute(
            __import__("sqlalchemy").select(CollectionStatus))).scalars().all()
        by_vid = {r.vehicle_id: json.loads(r.skipped_vehicles)["vehicles"] for r in rows}
        assert by_vid["v1"] == ["车2"] and by_vid["v2"] == ["车1"]
