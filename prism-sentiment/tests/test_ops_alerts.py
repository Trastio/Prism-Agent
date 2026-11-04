"""Tests: T1.4 LLM 判错抽检 + T1.5 成本告警（402 推送）。

T1.4 scripts/llm_qa_sample.py：
- DeepSeek 未配置 → 退化人工核对模式（不调 API，只输出库内结论）
- DeepSeek 已配置 → 双模型交叉验证，输出不一致率

T1.5 pipeline/scheduler._alert_402：
- 仅 402/余额类账户错误触发告警（401/403 不触发）
- 按 vehicle_id 去重（同车多平台只告一次）
- COST_ALERT_WEBHOOK 可选推送
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from unittest.mock import MagicMock, patch

from models.schemas import AnalyzedPost, Base, RawPost, Vehicle
from pipeline.collectors.tikhub_collector import TikHubAuthError


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


@pytest_asyncio.fixture
async def vehicle_with_posts(db):
    """1 车 + 3 已分析帖（sentiment 各异）。"""
    v = Vehicle(id="v-qa", name="风云T7", brand="奇瑞",
                search_keywords='["风云T7"]')
    db.add(v)
    await db.flush()
    sentiments = ["positive", "negative", "neutral"]
    for i, s in enumerate(sentiments):
        rp = RawPost(
            id=f"rp-{i}", vehicle_id=v.id, source="news", platform="news",
            title=f"风云T7 测评 {i}", content=f"风云T7 第 {i} 条正文",
        )
        db.add(rp)
        db.add(AnalyzedPost(
            id=f"ap-{i}", post_id=rp.id, vehicle_id=v.id,
            sentiment=s, confidence=0.8, model_used="glm-4-flash",
        ))
    await db.commit()
    return v


# ── T1.5 成本告警 ────────────────────────────────────────────────────────

class TestAlert402:
    """_alert_402：仅余额类错误触发，按 vehicle_id 去重。"""

    def setup_method(self):
        # 每个测试重置去重集合，避免跨用例污染
        from pipeline import scheduler
        scheduler._alert_402_sent.clear()

    def test_balance_error_tikhub_402_triggers_alert(self, caplog):
        from pipeline.scheduler import _alert_402
        err = TikHubAuthError("TikHub x.y HTTP 402: insufficient balance")
        with caplog.at_level("ERROR"):
            _alert_402("v-1", "tikhub", err)
        assert any("COST ALERT" in r.message for r in caplog.records)
        assert "tikhub" in caplog.records[-1].message

    def test_balance_error_code301_text_triggers_alert(self, caplog):
        """余额文案（历史 code=301 兼容匹配）触发告警。"""
        from pipeline.scheduler import _alert_402
        err = TikHubAuthError("x.y 账户级错误 code=301: 余额不足")
        with caplog.at_level("ERROR"):
            _alert_402("v-2", "tikhub", err)
        assert any("COST ALERT" in r.message for r in caplog.records)

    def test_balance_error_302_triggers_alert(self, caplog):
        """302（历史 OneAPI 余额文案，防未来 provider 复用）触发告警。"""
        from pipeline.scheduler import _alert_402
        err = TikHubAuthError("HTTP 302: quota/balance exhausted upstream")
        with caplog.at_level("ERROR"):
            _alert_402("v-302", "tikhub", err)
        assert any("COST ALERT" in r.message for r in caplog.records)

    def test_balance_error_quota_exceeded_triggers_alert(self, caplog):
        """"quota exceeded" 措辞触发告警。"""
        from pipeline.scheduler import _alert_402
        err = TikHubAuthError("request rejected: quota exceeded for this account")
        with caplog.at_level("ERROR"):
            _alert_402("v-quota", "tikhub", err)
        assert any("COST ALERT" in r.message for r in caplog.records)

    def test_key_invalid_401_does_not_trigger(self, caplog):
        """401 key 失效非成本事件，不触发成本告警。"""
        from pipeline.scheduler import _alert_402
        err = TikHubAuthError("TikHub x.y HTTP 401: unauthorized")
        with caplog.at_level("ERROR"):
            _alert_402("v-3", "tikhub", err)
        assert not any("COST ALERT" in r.message for r in caplog.records)

    def test_account_403_does_not_trigger(self, caplog):
        """403 账户封禁非成本事件，不触发成本告警。"""
        from pipeline.scheduler import _alert_402
        err = TikHubAuthError("x.y 账户级错误 HTTP 403: account disabled")
        with caplog.at_level("ERROR"):
            _alert_402("v-4", "tikhub", err)
        assert not any("COST ALERT" in r.message for r in caplog.records)

    def test_dedup_per_vehicle(self, caplog):
        """同车多平台 402 只告警一次。"""
        from pipeline.scheduler import _alert_402
        err = TikHubAuthError("HTTP 402: balance")
        with caplog.at_level("ERROR"):
            _alert_402("v-dup", "tikhub", err)
            _alert_402("v-dup", "tikhub",
                       TikHubAuthError("code=301: 余额不足"))
        cost_logs = [r for r in caplog.records if "COST ALERT" in r.message]
        assert len(cost_logs) == 1

    def test_different_vehicles_both_alert(self, caplog):
        from pipeline.scheduler import _alert_402
        with caplog.at_level("ERROR"):
            _alert_402("v-a", "tikhub",
                       TikHubAuthError("HTTP 402: balance"))
            _alert_402("v-b", "tikhub",
                       TikHubAuthError("HTTP 402: balance"))
        cost_logs = [r for r in caplog.records if "COST ALERT" in r.message]
        assert len(cost_logs) == 2

    def test_webhook_called_when_configured(self, monkeypatch):
        from pipeline.scheduler import _alert_402
        monkeypatch.setenv("COST_ALERT_WEBHOOK", "https://hook.example/x")
        mock_post = MagicMock()
        with patch("httpx.post", mock_post):
            _alert_402("v-hook", "tikhub",
                       TikHubAuthError("HTTP 402: balance"))
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://hook.example/x"
        assert "余额耗尽" in kwargs["json"]["text"]

    def test_webhook_failure_does_not_raise(self, monkeypatch, caplog):
        """webhook 推送失败不应抛错，只 warning。"""
        from pipeline.scheduler import _alert_402
        monkeypatch.setenv("COST_ALERT_WEBHOOK", "https://hook.example/x")
        with patch("httpx.post", side_effect=RuntimeError("network down")):
            _alert_402("v-hook2", "tikhub",
                       TikHubAuthError("HTTP 402: balance"))
        # 告警本身已发，webhook 失败只记 warning
        assert any("COST ALERT" in r.message for r in caplog.records)


# ── T1.4 LLM 判错抽检 ────────────────────────────────────────────────────

class _SessionCtx:
    """async_session() 的上下文管理器替身，返回固定 session。"""
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *a):
        pass


async def _build_qa_db(monkeypatch, qa, vehicle_name="风云T7",
                       sentiments=("positive",)):
    """内存 DB + N 帖，patch qa.async_session 返回会话，返回 (engine, session)。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = factory()
    v = Vehicle(id="v-qa-test", name=vehicle_name, brand="奇瑞",
                search_keywords=f'["{vehicle_name}"]')
    session.add(v)
    await session.flush()
    for i, s in enumerate(sentiments):
        rp = RawPost(id=f"rp-qa-{i}", vehicle_id=v.id, source="news",
                     platform="news", title=f"{vehicle_name} 测评{i}",
                     content=f"{vehicle_name} 正文{i}")
        session.add(rp)
        session.add(AnalyzedPost(id=f"ap-qa-{i}", post_id=rp.id, vehicle_id=v.id,
                                 sentiment=s, confidence=0.9,
                                 model_used="glm-4-flash"))
    await session.commit()
    # qa_sample 内部 `from models.database import async_session` 在调用时
    # 读取模块属性，故 patch 源头模块而非脚本本地名
    monkeypatch.setattr("models.database.async_session",
                        lambda: _SessionCtx(session))
    return engine, session


class TestQaSample:
    """scripts/llm_qa_sample.qa_sample 行为。"""

    @pytest.mark.asyncio
    async def test_degraded_mode_when_deepseek_unconfigured(self, monkeypatch, capsys):
        """DeepSeek 未配置 → 退化人工核对模式，不调 API。"""
        import scripts.llm_qa_sample as qa
        monkeypatch.setattr(qa, "load_api_config", lambda: {
            "glm": {"api_key": "g", "model": "glm-4-flash"}
        })
        engine, _session = await _build_qa_db(
            monkeypatch, qa, sentiments=("positive",))
        try:
            rc = await qa.qa_sample("风云T7", sample_size=20, seed=1)
        finally:
            await engine.dispose()
        out = capsys.readouterr().out
        assert "无法交叉验证" in out
        assert "positive" in out
        assert rc == 0

    @pytest.mark.asyncio
    async def test_cross_validation_mismatch_counted(self, monkeypatch, capsys):
        """DeepSeek 已配置 → 调 DeepSeek 重判，不一致计入报告。"""
        import scripts.llm_qa_sample as qa
        monkeypatch.setattr(qa, "load_api_config", lambda: {
            "glm": {"api_key": "g", "model": "glm-4-flash"},
            "deepseek": {"api_key": "d", "model": "deepseek-chat"},
        })
        # DeepSeek 返回 negative（库内 GLM 是 positive → 不一致）
        async def fake_call(api_key, api_url, model, prompt):
            return '{"sentiment": "negative"}'
        monkeypatch.setattr(qa, "_call_model", fake_call)
        engine, _session = await _build_qa_db(
            monkeypatch, qa, sentiments=("positive",))
        try:
            rc = await qa.qa_sample("风云T7", sample_size=20, seed=1)
        finally:
            await engine.dispose()
        out = capsys.readouterr().out
        assert "不一致" in out
        assert "MISMATCH" in out
        assert rc == 0

    @pytest.mark.asyncio
    async def test_vehicle_not_found_returns_nonzero(self, monkeypatch, capsys):
        import scripts.llm_qa_sample as qa
        monkeypatch.setattr(qa, "load_api_config", lambda: {
            "glm": {"api_key": "g", "model": "glm-4-flash"},
        })
        engine, _session = await _build_qa_db(
            monkeypatch, qa, vehicle_name="风云T7")
        try:
            rc = await qa.qa_sample("不存在的车", sample_size=5)
        finally:
            await engine.dispose()
        out = capsys.readouterr().out
        assert rc == 1
        assert "未找到" in out
