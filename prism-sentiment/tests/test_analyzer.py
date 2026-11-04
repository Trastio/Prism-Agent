"""Tests: Analysis Pipeline — dual-model + event tag pool + dim_sentiment."""
import json

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from pipeline.analysis.analyzer import AnalysisPipeline, EVENT_TAG_POOL


# ── Tag Pool ──────────────────────────────────────────────────────────────

class TestEventTagPool:
    def test_pool_has_17_tags(self):
        assert len(EVENT_TAG_POOL) == 17

    def test_pool_contains_all_expected_tags(self):
        expected = [
            "质量问题", "异响/故障", "安全事故", "召回",
            "新车发布/上市", "降价/促销", "交付延迟", "提车分享",
            "续航争议", "充电问题", "智能驾驶事故", "OTA升级",
            "维权投诉", "售后服务", "4S店纠纷",
            "政策法规", "行业动态",
        ]
        for tag in expected:
            assert tag in EVENT_TAG_POOL, f"Missing tag: {tag}"

    def test_pool_is_flat_strings(self):
        for tag in EVENT_TAG_POOL:
            assert isinstance(tag, str), f"Tag {tag!r} is not a string"


# ── Parse Response ────────────────────────────────────────────────────────

class TestParseResponse:
    def test_parse_full_json(self):
        raw = json.dumps({
            "event_tags": ["异响/故障"],
            "opinion_tags": ["刹车问题"],
            "sentiment": "negative",
            "dim_sentiment": {"安全性": -1},
            "confidence": 0.9,
        })
        result = AnalysisPipeline._parse_response(raw)
        assert result["sentiment"] == "negative"
        assert "安全性" in result["dim_sentiment"]
        assert "异响/故障" in result["event_tags"]

    def test_parse_non_event(self):
        raw = json.dumps({
            "event_tags": [],
            "opinion_tags": ["颜值高"],
            "sentiment": "positive",
            "dim_sentiment": {"外观": 1},
            "confidence": 0.85,
        })
        result = AnalysisPipeline._parse_response(raw)
        assert result["event_tags"] == []
        assert result["dim_sentiment"]["外观"] == 1

    def test_parse_filters_invalid_event_tags(self):
        raw = json.dumps({
            "event_tags": ["异响/故障", "不存在的标签", "召回"],
            "opinion_tags": [],
            "sentiment": "neutral",
            "dim_sentiment": {},
            "confidence": 0.7,
        })
        result = AnalysisPipeline._parse_response(raw)
        assert result["event_tags"] == ["异响/故障", "召回"]

    def test_parse_json_in_code_block(self):
        raw = '```json\n{"event_tags": [], "opinion_tags": [], "sentiment": "neutral", "dim_sentiment": {}, "confidence": 0.5}\n```'
        result = AnalysisPipeline._parse_response(raw)
        assert result["sentiment"] == "neutral"

    def test_parse_invalid_json_returns_fallback(self):
        result = AnalysisPipeline._parse_response("not json at all")
        assert result["sentiment"] == "neutral"
        assert result["event_tags"] == []
        assert result["dim_sentiment"] == {}

    def test_parse_partial_json(self):
        raw = '{"sentiment": "positive"}'
        result = AnalysisPipeline._parse_response(raw)
        assert result["sentiment"] == "positive"
        assert result["event_tags"] == []

    def test_parse_invalid_sentiment_defaults_neutral(self):
        raw = '{"sentiment": "excited", "event_tags": [], "opinion_tags": [], "dim_sentiment": {}, "confidence": 0.5}'
        result = AnalysisPipeline._parse_response(raw)
        assert result["sentiment"] == "neutral"

    def test_parse_filters_non_whitelist_dimensions(self):
        """dim_sentiment 必须只保留 15 个标准维度，丢弃 LLM 自创维度。"""
        raw = json.dumps({
            "event_tags": [],
            "opinion_tags": [],
            "sentiment": "positive",
            "dim_sentiment": {
                "外观": 1,
                "砍价技巧": 1,
                "销量": 1,
                "颠簸道路稳定性": -1,
                "售后服务": 0,
            },
            "confidence": 0.9,
        })
        result = AnalysisPipeline._parse_response(raw)
        assert result["dim_sentiment"] == {"外观": 1, "售后服务": 0}

    def test_parse_keeps_all_15_standard_dimensions(self):
        """全部 15 个标准维度都应保留。"""
        from pipeline.analysis.local_absa import ALL_DIMENSIONS
        dims = {d: 1 for d in ALL_DIMENSIONS}
        raw = json.dumps({
            "event_tags": [], "opinion_tags": [],
            "sentiment": "positive",
            "dim_sentiment": dims,
            "confidence": 0.9,
        })
        result = AnalysisPipeline._parse_response(raw)
        assert set(result["dim_sentiment"].keys()) == set(ALL_DIMENSIONS)
        assert len(result["dim_sentiment"]) == 15


# ── Fallback ──────────────────────────────────────────────────────────────

class TestFallback:
    def test_fallback_has_all_fields(self):
        result = AnalysisPipeline._fallback_result()
        assert result["sentiment"] == "neutral"
        assert result["event_tags"] == []
        assert result["opinion_tags"] == []
        assert result["dim_sentiment"] == {}
        assert result["confidence"] == 0.0

    def test_fallback_event_has_all_fields(self):
        result = AnalysisPipeline._fallback_event_result()
        assert result["event_tags"] == []
        assert result["opinion_tags"] == []
        assert result["confidence"] == 0.0


# ── API Selection ─────────────────────────────────────────────────────────

class TestApiSelection:
    def test_uses_glm_when_configured(self):
        secrets = {"glm": {"api_key": "test-key", "base_url": "https://open.bigmodel.cn/api/paas/v4"}}
        with patch("utils.llm_client.load_api_config", return_value=secrets):
            p = AnalysisPipeline()
        assert p._use_anthropic_format is False
        assert p._api_key == "test-key"
        assert p._api_url.endswith("/chat/completions")

    def test_uses_deepseek_when_no_glm(self):
        secrets = {"deepseek": {"api_key": "ds-key", "api_url": "https://api.deepseek.com/v1/chat/completions"}}
        with patch("utils.llm_client.load_api_config", return_value=secrets):
            p = AnalysisPipeline()
        assert p._use_anthropic_format is False
        assert p._api_key == "ds-key"

    def test_no_key_means_empty(self):
        with patch("utils.llm_client.load_api_config", return_value={}):
            p = AnalysisPipeline()
        assert p._api_key == ""


# ── analyze_single (with mocked _call_api) ────────────────────────────────

class TestAnalyzeSingle:
    @pytest.mark.asyncio
    async def test_event_post(self):
        pipeline = AnalysisPipeline()
        with patch.object(pipeline, "_call_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = json.dumps({
                "event_tags": ["异响/故障"],
                "opinion_tags": ["刹车问题"],
                "sentiment": "negative",
                "dim_sentiment": {"安全性": -1},
                "confidence": 0.9,
            })
            result = await pipeline.analyze_single("提车一周发现刹车异响严重")
            assert result["sentiment"] == "negative"
            assert "安全性" in result["dim_sentiment"]
            assert "异响/故障" in result["event_tags"]

    @pytest.mark.asyncio
    async def test_non_event_post(self):
        pipeline = AnalysisPipeline()
        with patch.object(pipeline, "_call_api", new_callable=AsyncMock) as mock_api:
            mock_api.return_value = json.dumps({
                "event_tags": [],
                "opinion_tags": ["颜值高"],
                "sentiment": "positive",
                "dim_sentiment": {"外观": 1},
                "confidence": 0.85,
            })
            result = await pipeline.analyze_single("今天终于提车了，外观真的好看")
            assert result["event_tags"] == []

    @pytest.mark.asyncio
    async def test_empty_text_returns_fallback(self):
        pipeline = AnalysisPipeline()
        result = await pipeline.analyze_single("")
        assert result["sentiment"] == "neutral"

    @pytest.mark.asyncio
    async def test_no_api_key_returns_fallback(self):
        pipeline = AnalysisPipeline()
        pipeline._api_key = ""
        result = await pipeline.analyze_single("some text about cars")
        assert result["sentiment"] == "neutral"

    @pytest.mark.asyncio
    async def test_api_exception_returns_fallback(self):
        pipeline = AnalysisPipeline()
        with patch.object(pipeline, "_call_api", new_callable=AsyncMock) as mock_api:
            mock_api.side_effect = Exception("API timeout")
            result = await pipeline.analyze_single("car post")
            assert result["sentiment"] == "neutral"
            assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_fallback(self):
        pipeline = AnalysisPipeline()
        result = await pipeline.analyze_single("   \n\t  ")
        assert result["sentiment"] == "neutral"


# ── analyze_batch ─────────────────────────────────────────────────────────

class TestAnalyzeBatch:
    @pytest.mark.asyncio
    async def test_batch_with_mock(self):
        pipeline = AnalysisPipeline()
        posts = [
            {"id": "p1", "content": "海豹续航很好"},
            {"id": "p2", "content": "海豹刹车异响"},
        ]
        mock_result = {
            "sentiment": "positive",
            "event_tags": [],
            "opinion_tags": ["续航好"],
            "dim_sentiment": {"续航里程": 1},
            "confidence": 0.9,
        }
        with patch.object(pipeline, "analyze_single", new_callable=AsyncMock, return_value=mock_result):
            results = await pipeline.analyze_batch(posts)
        assert len(results) == 2
        assert results[0]["content"] == "海豹续航很好"
        assert results[0]["id"] == "p1"



# ── Event-only API prompt ─────────────────────────────────────────────────

class TestEventOnlyApi:
    @pytest.mark.asyncio
    async def test_event_api_parse(self):
        pipeline = AnalysisPipeline()
        raw = json.dumps({
            "event_tags": ["降价/促销"],
            "opinion_tags": ["价格跳水"],
            "confidence": 0.88,
        })
        result = AnalysisPipeline._parse_event_response(raw)
        assert result["event_tags"] == ["降价/促销"]
        assert result["opinion_tags"] == ["价格跳水"]

    @pytest.mark.asyncio
    async def test_event_api_invalid_json(self):
        result = AnalysisPipeline._parse_event_response("not json")
        assert result["event_tags"] == []
        assert result["confidence"] == 0.0


# ── Integration: real API format (Anthropic) ──────────────────────────────

class TestAnalyzeSingleIntegration:
    @pytest.mark.asyncio
    async def test_analyze_single_with_openai_format_mock(self):
        secrets = {"glm": {"api_key": "test-key", "base_url": "https://open.bigmodel.cn/api/paas/v4"}}
        with patch("utils.llm_client.load_api_config", return_value=secrets):
            p = AnalysisPipeline()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "event_tags": [],
                "opinion_tags": ["续航好"],
                "sentiment": "positive",
                "dim_sentiment": {"续航里程": 1},
                "confidence": 0.85,
            })}}]
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await p.analyze_single("海豹续航实测不错")
        assert result["sentiment"] == "positive"
        assert result["dim_sentiment"]["续航里程"] == 1
        call_args = mock_client.post.call_args
        assert "Authorization" in call_args[1]["headers"]
        assert call_args[1]["headers"]["Authorization"].startswith("Bearer test-key")
