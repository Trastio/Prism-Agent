"""极性引擎切换 DeepSeek（2026-10-20 change）测试。

覆盖：key 解析顺序 / prompt 口径 / _post_one 解析与错误分类 / 重试与耗尽 /
batch_runner deepseek 路径（引擎路由·队列·哨兵·fail-soft·单次上限）/
dashboard 可用性字段引擎化。全 mock，零真实 API、零 GPU。
"""
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.schemas import Base, PostComment, RawPost, Vehicle


def test_default_secrets_path_is_repo_root():
    """隔审 P1-1 钉子：默认 .secrets 必须锚定仓库根（曾差一层到 pipeline/）。"""
    from pipeline.analysis import deepseek_polarity as dp
    repo_root = Path(__file__).resolve().parents[1]
    assert dp._DEFAULT_SECRETS == repo_root / ".secrets"


# ── 1. key 解析顺序 ──────────────────────────────────────────────────

def test_key_env_first(monkeypatch, tmp_path):
    from pipeline.analysis import deepseek_polarity as dp
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    key, src = dp.resolve_api_key(
        secrets_path=str(tmp_path / "none.secrets"), auth_path=str(tmp_path / "none.auth"))
    assert (key, src) == ("sk-env", "env")


def test_key_secrets_then_auth(monkeypatch, tmp_path):
    from pipeline.analysis import deepseek_polarity as dp
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    secrets = tmp_path / "s1"
    secrets.write_text(json.dumps({"deepseek": {"api_key": "sk-sec"}, "glm": {"api_key": "g"}}),
                       encoding="utf-8")
    auth = tmp_path / "a1"
    auth.write_text(json.dumps({"deepseek": {"key": "sk-auth"}}), encoding="utf-8")
    assert dp.resolve_api_key(secrets_path=str(secrets), auth_path=str(auth)) == ("sk-sec", ".secrets")
    # secrets 无 deepseek 段 → 落到 auth
    secrets2 = tmp_path / "s2"
    secrets2.write_text(json.dumps({"glm": {"api_key": "g"}}), encoding="utf-8")
    assert dp.resolve_api_key(secrets_path=str(secrets2), auth_path=str(auth)) == ("sk-auth", "pi-auth")
    # 全空
    assert dp.resolve_api_key(secrets_path=str(secrets2), auth_path=str(tmp_path / "nope")) == ("", "none")


def test_prompt_strips_no_think():
    from pipeline.analysis.deepseek_polarity import POLARITY_PROMPT
    assert "/no_think" not in POLARITY_PROMPT
    assert "1(正面)" in POLARITY_PROMPT  # 口径与微调 POLARITY_SYSTEM_PROMPT 同源


# ── 2. _post_one 解析与错误分类 ──────────────────────────────────────

class _FakeClient:
    def __init__(self, status=200, content="1", text=""):
        self._status, self._content, self._text = status, content, text

    async def post(self, url, headers=None, json=None):
        req = httpx.Request("POST", url)
        if self._status == 200:
            body = {"choices": [{"message": {"content": self._content}}]}
            return httpx.Response(200, json=body, request=req)
        return httpx.Response(self._status, text=self._text, request=req)


async def test_post_one_parses_and_unparseable():
    from pipeline.analysis.deepseek_polarity import _post_one
    assert await _post_one(_FakeClient(content="1"), "k", "m", "续航不错") == "1"
    assert await _post_one(_FakeClient(content="-1"), "k", "m", "x") == "-1"
    assert await _post_one(_FakeClient(content="很好开"), "k", "m", "x") is None  # 不可解析


async def test_post_one_permanent_error():
    from pipeline.analysis.deepseek_polarity import _post_one, DeepSeekPolarityError
    with pytest.raises(DeepSeekPolarityError):  # 401 永久错不重试
        await _post_one(_FakeClient(status=401, text="bad key"), "k", "m", "x")


async def test_post_one_5xx_retryable():
    from pipeline.analysis.deepseek_polarity import _post_one
    client = _FakeClient(status=500)
    with pytest.raises(httpx.HTTPStatusError):  # 5xx → raise_for_status（可重试类）
        await _post_one(client, "k", "m", "x")


# ── 3. tag_polarity_batch 重试与耗尽 ─────────────────────────────────

async def test_batch_retries_then_succeeds(monkeypatch):
    from pipeline.analysis import deepseek_polarity as dp

    monkeypatch.setattr(dp, "resolve_api_key", lambda: ("sk-t", "env"))

    async def fake_sleep(_s):  # 重试退避不真睡
        return None
    monkeypatch.setattr(dp.asyncio, "sleep", fake_sleep)

    calls = {"n": 0}

    async def flaky(client, api_key, model, content):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise httpx.TransportError("conn reset")
        return "1"

    monkeypatch.setattr(dp, "_post_one", flaky)
    assert await dp.tag_polarity_batch(["续航不错"]) == ["1"]
    assert calls["n"] == 3


async def test_batch_exhausted_raises(monkeypatch):
    from pipeline.analysis import deepseek_polarity as dp

    monkeypatch.setattr(dp, "resolve_api_key", lambda: ("sk-t", "env"))

    async def fake_sleep(_s):
        return None
    monkeypatch.setattr(dp.asyncio, "sleep", fake_sleep)

    async def always_fail(client, api_key, model, content):
        raise httpx.TransportError("down")

    monkeypatch.setattr(dp, "_post_one", always_fail)
    with pytest.raises(dp.DeepSeekPolarityError):
        await dp.tag_polarity_batch(["x"])


async def test_batch_no_key_raises(monkeypatch):
    from pipeline.analysis import deepseek_polarity as dp
    monkeypatch.setattr(dp, "resolve_api_key", lambda: ("", "none"))
    with pytest.raises(dp.DeepSeekPolarityError):
        await dp.tag_polarity_batch(["x"])


async def test_batch_permanent_error_among_successes(monkeypatch):
    """隔审 P2-1：批内一条永久错 → 整批契约失败（gather 聚合，不吞不穿透）。"""
    from pipeline.analysis import deepseek_polarity as dp

    monkeypatch.setattr(dp, "resolve_api_key", lambda: ("sk-t", "env"))

    async def fake_sleep(_s):
        return None
    monkeypatch.setattr(dp.asyncio, "sleep", fake_sleep)

    async def mixed(client, api_key, model, content):
        if "刹车" in content:
            raise dp.DeepSeekPolarityError("http401")
        return "1"

    monkeypatch.setattr(dp, "_post_one", mixed)
    with pytest.raises(dp.DeepSeekPolarityError):
        await dp.tag_polarity_batch(["续航不错", "刹车异响"])


# ── 4. batch_runner deepseek 路径 ────────────────────────────────────

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


async def _seed(db, vehicle_id: str) -> None:
    db.add(Vehicle(id=vehicle_id, name="DS测试车", brand="DS", status="active"))
    now = datetime.utcnow()
    for i, content in enumerate(["续航不错", "", "刹车异响"]):
        db.add(PostComment(
            id=f"c-new-{i}", post_id="p1", vehicle_id=vehicle_id,
            content=content, platform="xiaohongshu", collected_at=now,
        ))
    db.add(PostComment(
        id="c-old", post_id="p1", vehicle_id=vehicle_id,
        content="老评论", platform="xiaohongshu", collected_at=now,
        dim_sentiment='{"动力": 1}',
    ))
    db.add(RawPost(
        id="p1", vehicle_id=vehicle_id, platform="xiaohongshu", source="tikhub",
        content="帖子", collected_at=now, analysis_status="analyzed",
    ))
    await db.commit()


def _patch_engine(monkeypatch, results=None, error=None):
    """钉 deepseek 引擎 + mock 批打标。results=与 valid 等长的输出列表。"""
    from pipeline.analysis import deepseek_polarity as dp

    monkeypatch.setenv("POLARITY_ENGINE", "deepseek")

    async def fake_tag(texts):
        if error:
            raise error
        return list(results[:len(texts)]) + ["0"] * max(0, len(texts) - len(results))

    monkeypatch.setattr(dp, "tag_polarity_batch", fake_tag)


async def test_engine_routing_deepseek(db, monkeypatch):
    from pipeline.analysis import batch_runner as br

    await _seed(db, "v1")
    _patch_engine(monkeypatch, results=["1", "-1"])
    n = await br.BatchAnalysisRunner(db).run_comment_analysis("v1")

    rows = {c.id: c for c in (await db.execute(
        select(PostComment).where(PostComment.vehicle_id == "v1"))).scalars()}
    assert rows["c-new-0"].comment_polarity == "1"
    assert rows["c-new-2"].comment_polarity == "-1"
    assert rows["c-new-0"].dim_sentiment is None  # 不写 dim（极性轨口径不变）
    assert rows["c-new-1"].comment_polarity == "none"  # 空内容哨兵
    assert rows["c-old"].comment_polarity is None      # 老评论不重标
    assert rows["c-old"].dim_sentiment == '{"动力": 1}'
    assert n == 2


async def test_engine_failsoft_leaves_queue(db, monkeypatch):
    from pipeline.analysis import deepseek_polarity as dp

    await _seed(db, "v2")
    _patch_engine(monkeypatch, error=dp.DeepSeekPolarityError("network down"))
    n = await br2_run(db, "v2")

    rows = {c.id: c for c in (await db.execute(
        select(PostComment).where(PostComment.vehicle_id == "v2"))).scalars()}
    # 引擎失败：本批零写入（哨兵也不写），全部留 NULL 队列下次再标
    assert n == 0
    assert rows["c-new-0"].comment_polarity is None
    assert rows["c-new-1"].comment_polarity is None


async def br2_run(db, vid):
    from pipeline.analysis import batch_runner as br
    return await br.BatchAnalysisRunner(db).run_comment_analysis(vid)


async def test_unparseable_becomes_sentinel(db, monkeypatch):
    await _seed(db, "v3")
    _patch_engine(monkeypatch, results=[None, "-1"])  # 第一条不可解析
    await br2_run(db, "v3")
    rows = {c.id: c for c in (await db.execute(
        select(PostComment).where(PostComment.vehicle_id == "v3"))).scalars()}
    assert rows["c-new-0"].comment_polarity == "none"  # 真不可解析 → 哨兵（重试无益）
    assert rows["c-new-2"].comment_polarity == "-1"


async def test_engine_short_result_leaves_queue(db, monkeypatch):
    """隔审 P2-4：引擎返回短列表 → 契约破坏跳过本批，不 zip 截断落哨兵。"""
    from pipeline.analysis import deepseek_polarity as dp

    await _seed(db, "v5")
    monkeypatch.setenv("POLARITY_ENGINE", "deepseek")

    async def short_tag(texts):
        return ["1"]  # 无论入参多少只回 1 条

    monkeypatch.setattr(dp, "tag_polarity_batch", short_tag)
    n = await br2_run(db, "v5")
    rows = {c.id: c for c in (await db.execute(
        select(PostComment).where(PostComment.vehicle_id == "v5"))).scalars()}
    assert n == 0
    assert rows["c-new-0"].comment_polarity is None  # 全部留队列
    assert rows["c-new-1"].comment_polarity is None


async def test_run_cap_zero_skips(db, monkeypatch):
    from pipeline.analysis import deepseek_polarity as dp

    await _seed(db, "v4")
    _patch_engine(monkeypatch, results=["1"])
    monkeypatch.setenv("DS_POLARITY_MAX_PER_RUN", "0")
    called = {"n": 0}

    async def fake_tag(texts):
        called["n"] += 1
        return ["1"] * len(texts)

    monkeypatch.setattr(dp, "tag_polarity_batch", fake_tag)
    n = await br2_run(db, "v4")
    assert n == 0
    assert called["n"] == 0  # 上限 0 → 不发起任何调用


# ── 5. dashboard 可用性字段引擎化 ────────────────────────────────────

def test_availability_deepseek_key_present(monkeypatch):
    from api.routes import dashboard as dash
    from pipeline.analysis import deepseek_polarity as dp
    monkeypatch.setenv("POLARITY_ENGINE", "deepseek")
    monkeypatch.setattr(dp, "resolve_api_key", lambda: ("sk-x", "env"))
    assert dash._check_comment_model_available() is True


def test_availability_deepseek_no_key(monkeypatch):
    from api.routes import dashboard as dash
    from pipeline.analysis import deepseek_polarity as dp
    monkeypatch.setenv("POLARITY_ENGINE", "deepseek")
    monkeypatch.setattr(dp, "resolve_api_key", lambda: ("", "none"))
    assert dash._check_comment_model_available() is False


def test_availability_local_unloaded(monkeypatch):
    from api.routes import dashboard as dash
    from pipeline.analysis.local_absa import LocalABSAModel
    monkeypatch.setenv("POLARITY_ENGINE", "local")
    # 单测进程不载模型（_loaded=False）——镜像 test_degradation_visibility 语义
    assert LocalABSAModel.get()._loaded is False
    assert dash._check_comment_model_available() is False
