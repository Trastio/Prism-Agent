"""词云停用词注入测试（T1.8 B4/D9）。

实测词云 top 词被车型名（"风云"2340次/"奇瑞"703次）和通稿套话
（"纯电"/"suv"/"全球"）霸屏——基本无信息量。本测试验证：
1. 当前车型名/品牌不出现在词云
2. 全库他车名（对比帖里出现）不出现
3. 通稿套话词不出现
4. 正常有信息量词仍保留（不误伤）
"""

from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.database import get_session
from models.schemas import AnalyzedPost, Base, RawPost, Vehicle


def _post(pid, vid, title, content=None, sentiment="neutral",
          author_type="organic", status="analyzed", likes=10, comments=5):
    p = RawPost(
        id=pid, vehicle_id=vid, source="tikhub", platform="weibo",
        title=title, content=content or title, author="作者" + pid,
        url=f"https://x/{pid}", published_at=datetime(2026, 9, 10),
        likes=likes, comments=comments, shares=0,
        analysis_status=status, relevance_score=1.0, author_type=author_type,
    )
    ap = AnalyzedPost(
        id=f"ap-{pid}", post_id=pid, vehicle_id=vid,
        sentiment=sentiment, model_used="test",
    )
    return p, ap


@pytest_asyncio.fixture
async def env():
    """内存库：当前车=风云T7(奇瑞)，对比帖含他车名 + 通稿套话 + 真实信号词。"""
    from api.main import app
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async with factory() as s:
            # 当前车 + 他车（全库车型名都应被屏蔽）
            s.add(Vehicle(id="v1", name="风云T7", brand="奇瑞"))
            s.add(Vehicle(id="v2", name="星愿", brand="吉利银河"))
            await s.commit()
            # 帖子文本：车型名子串 + 品牌名 + 通稿套话 + 真实信号词
            p, ap = _post(
                "p1", "v1",
                title="奇瑞风云T7纯电suv全球上市实测 续航电池品质高速",
                content="奇瑞风云T7纯电suv全球上市实测续航电池品质高速 "
                        "星愿吉利银河对比 操控舒服油耗低异响投诉",
            )
            s.add(p); s.add(ap)
            await s.commit()
            yield c, s
    app.dependency_overrides.clear()
    await engine.dispose()


class TestWordCloudStopwords:
    @pytest.mark.asyncio
    async def test_vehicle_name_brand_excluded(self, env):
        """当前车名/品牌 + 子串 + 全库他车名不得进词云。"""
        client, _ = env
        words = (await client.get("/api/dashboard/word-cloud/v1?limit=200")).json()
        names = {w["name"] for w in words}
        # 当前车名/品牌 + 子串
        assert "奇瑞" not in names, f"品牌名奇瑞泄漏: {names}"
        assert "风云" not in names, f"车名子串风云泄漏: {names}"
        # 全库他车名/品牌
        assert "星愿" not in names, f"他车名星愿泄漏: {names}"
        assert "吉利" not in names, f"他品牌吉利泄漏: {names}"
        assert "银河" not in names, f"他品牌子串银河泄漏: {names}"

    @pytest.mark.asyncio
    async def test_boilerplate_excluded(self, env):
        """通稿套话高频无信息量词不得进词云。"""
        client, _ = env
        words = (await client.get("/api/dashboard/word-cloud/v1?limit=200")).json()
        names = {w["name"] for w in words}
        for w in ("纯电", "suv", "全球", "上市", "实测", "续航", "电池", "品质", "高速"):
            assert w not in names, f"通稿套话 {w} 泄漏: {names}"

    @pytest.mark.asyncio
    async def test_real_signal_kept(self, env):
        """真实有信息量词不被误伤（操控/油耗/异响/投诉应保留）。"""
        client, _ = env
        words = (await client.get("/api/dashboard/word-cloud/v1?limit=200")).json()
        names = {w["name"] for w in words}
        kept = {"操控", "油耗", "异响", "投诉"} & names
        assert kept, f"真实信号词被误伤全删: {names}"
