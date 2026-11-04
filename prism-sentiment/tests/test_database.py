"""T1.2 Tests: Database Schema — all 9 tables."""
import pytest
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession


async def test_all_tables_created(db_engine):
    expected = [
        "vehicles", "collection_status", "raw_posts", "analyzed_posts",
        "heat_metrics", "reports",
        "dialog_conversations", "dialog_messages",
    ]
    async with db_engine.connect() as conn:
        result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        existing = {row[0] for row in result.fetchall()}
    for t in expected:
        assert t in existing, f"Missing table: {t}"


async def test_vehicle_crud(db_session: AsyncSession):
    from models.schemas import Vehicle
    v = Vehicle(id="v01", name="海豹", brand="比亚迪", status="active")
    db_session.add(v)
    await db_session.commit()
    result = await db_session.execute(select(Vehicle).where(Vehicle.id == "v01"))
    found = result.scalar_one()
    assert found.name == "海豹"
    assert found.brand == "比亚迪"


async def test_raw_post(db_session: AsyncSession):
    from models.schemas import RawPost
    p = RawPost(id="rp01", vehicle_id="v01", source="media", platform="xhs",
                title="测试", content="内容", likes=100, comments=20)
    db_session.add(p)
    await db_session.commit()
    result = await db_session.execute(select(RawPost).where(RawPost.id == "rp01"))
    found = result.scalar_one()
    assert found.analysis_status == "pending"
    assert found.likes == 100


async def test_analyzed_post(db_session: AsyncSession):
    from models.schemas import AnalyzedPost
    a = AnalyzedPost(id="ap01", post_id="rp01", vehicle_id="v01",
                     sentiment="positive", event_tags='["新车上市"]',
                     opinion_tags='["颜值高"]', confidence=0.92, model_used="deepseek")
    db_session.add(a)
    await db_session.commit()
    result = await db_session.execute(select(AnalyzedPost).where(AnalyzedPost.id == "ap01"))
    assert result.scalar_one().confidence == 0.92


async def test_heat_metric(db_session: AsyncSession):
    from datetime import date
    from models.schemas import HeatMetric
    m = HeatMetric(id="hm01", vehicle_id="v01", date=date(2026,5,20),
                   attention_index=8500.0, discussion_volume=120, media_volume=35,
                   interaction_intensity=67.5)
    db_session.add(m)
    await db_session.commit()
    result = await db_session.execute(select(HeatMetric).where(HeatMetric.id == "hm01"))
    assert result.scalar_one().discussion_volume == 120


# AnomalyEvent removed in 2026-06 analysis redesign


async def test_report(db_session: AsyncSession):
    from datetime import date
    from models.schemas import Report
    r = Report(id="rpt01", vehicle_id="v01", type="brief",
               title="简报", content="内容",
               time_range_start=date(2026,5,20), time_range_end=date(2026,5,20))
    db_session.add(r)
    await db_session.commit()
    result = await db_session.execute(select(Report).where(Report.id == "rpt01"))
    assert result.scalar_one().type == "brief"


async def test_dialog_tables(db_session: AsyncSession):
    from models.schemas import DialogConversation, DialogMessage
    c = DialogConversation(id="conv01", vehicle_id="v01", anchor_type="trend",
                           anchor_data='{"date":"2026-05-20"}')
    db_session.add(c)
    await db_session.flush()
    m = DialogMessage(id="msg01", conversation_id="conv01",
                      role="assistant", content="分析结果")
    db_session.add(m)
    await db_session.commit()
    result = await db_session.execute(
        select(DialogMessage).where(DialogMessage.conversation_id == "conv01"))
    assert result.scalar_one().role == "assistant"
