"""Tests: Local ABSA model — parsing, sentiment derivation, batch logic."""
import pytest

from pipeline.analysis.local_absa import parse_absa_output, _derive_overall_sentiment, ALL_DIMENSIONS


# ── parse_absa_output ──────────────────────────────────────────────────────

class TestParseAbsaOutput:
    def test_basic_two_dims(self):
        result = parse_absa_output("外观#1|空间#0")
        assert result["dim_sentiment"] == {"外观": 1, "空间": 0}
        assert result["sentiment"] == "positive"

    def test_negative_sentiment(self):
        result = parse_absa_output("电耗#-1|续航里程#-1")
        assert result["dim_sentiment"] == {"电耗": -1, "续航里程": -1}
        assert result["sentiment"] == "negative"

    def test_mixed_dims_equal_pos_neg_is_neutral(self):
        result = parse_absa_output("外观#1|舒适性#0|安全性#-1")
        assert result["dim_sentiment"] == {"外观": 1, "舒适性": 0, "安全性": -1}
        # 1 positive, 1 negative, avg=0 → neutral
        assert result["sentiment"] == "neutral"

    def test_mixed_dims_lean_positive_by_avg(self):
        result = parse_absa_output("外观#1|内饰#1|安全性#-1")
        assert result["dim_sentiment"] == {"外观": 1, "内饰": 1, "安全性": -1}
        # 2 positive, 1 negative → positive
        assert result["sentiment"] == "positive"

    def test_single_dimension(self):
        result = parse_absa_output("动力/加速#1")
        assert result["dim_sentiment"] == {"动力/加速": 1}
        assert result["sentiment"] == "positive"

    def test_neutral_dim_only(self):
        result = parse_absa_output("操控#0")
        assert result["dim_sentiment"] == {"操控": 0}
        assert result["sentiment"] == "neutral"

    def test_empty_string(self):
        result = parse_absa_output("")
        assert result["dim_sentiment"] == {}
        assert result["sentiment"] == "neutral"

    def test_whitespace_only(self):
        result = parse_absa_output("   ")
        assert result["dim_sentiment"] == {}

    def test_invalid_dimension_ignored(self):
        result = parse_absa_output("外观#1|不存在的维度#1")
        assert result["dim_sentiment"] == {"外观": 1}

    def test_invalid_sentiment_ignored(self):
        result = parse_absa_output("外观#2")
        assert result["dim_sentiment"] == {}

    def test_strips_whitespace(self):
        result = parse_absa_output(" 外观 # 1 | 空间 # 0 ")
        assert result["dim_sentiment"] == {"外观": 1, "空间": 0}

    def test_removes_qwen3_think_tags(self):
        result = parse_absa_output("<think\n分析外观...\n</think\n\n外观#1")
        assert result["dim_sentiment"] == {"外观": 1}

    def test_removes_think_tag_variant(self):
        result = parse_absa_output("<thinkreasoning</think/>外观#1|空间#0")
        assert result["dim_sentiment"] == {"外观": 1, "空间": 0}

    def test_no_think_content_returns_neutral(self):
        result = parse_absa_output("<think\nonly thinking\n</think\n")
        assert result["dim_sentiment"] == {}
        assert result["sentiment"] == "neutral"


# ── _derive_overall_sentiment ──────────────────────────────────────────────

class TestDeriveOverallSentiment:
    def test_all_positive(self):
        assert _derive_overall_sentiment({"外观": 1, "空间": 1}) == "positive"

    def test_all_negative(self):
        assert _derive_overall_sentiment({"安全性": -1, "电耗": -1}) == "negative"

    def test_more_negative_than_positive(self):
        assert _derive_overall_sentiment({"外观": 1, "电耗": -1, "续航里程": -1}) == "negative"

    def test_more_positive_than_negative(self):
        assert _derive_overall_sentiment({"外观": 1, "内饰": 1, "安全性": -1}) == "positive"

    def test_equal_positive_negative_lean_positive_by_avg(self):
        # 1 positive + 1 negative, avg = 0 → neutral... actually let's check
        assert _derive_overall_sentiment({"外观": 1, "安全性": -1}) == "neutral"

    def test_all_neutral(self):
        assert _derive_overall_sentiment({"操控": 0, "外观": 0}) == "neutral"

    def test_empty_dict(self):
        assert _derive_overall_sentiment({}) == "neutral"

    def test_single_positive(self):
        assert _derive_overall_sentiment({"外观": 1}) == "positive"


# ── ALL_DIMENSIONS coverage ────────────────────────────────────────────────

class TestAllDimensions:
    def test_has_15_dimensions(self):
        assert len(ALL_DIMENSIONS) == 15

    def test_includes_oil_and_nev(self):
        assert "油耗" in ALL_DIMENSIONS
        assert "续航里程" in ALL_DIMENSIONS
        assert "电耗" in ALL_DIMENSIONS
        assert "充电体验" in ALL_DIMENSIONS


# ── LocalABSAModel (unit tests without GPU) ───────────────────────────────

class TestLocalABSAModelUnit:
    def test_singleton_pattern(self):
        from pipeline.analysis.local_absa import LocalABSAModel
        a = LocalABSAModel.get()
        b = LocalABSAModel.get()
        assert a is b

    def test_not_loaded_by_default(self):
        from pipeline.analysis.local_absa import LocalABSAModel
        # Reset singleton for test isolation
        LocalABSAModel._instance = None
        model = LocalABSAModel.get()
        assert not model.is_loaded()

    def test_predict_batch_unloaded_returns_neutral(self):
        from pipeline.analysis.local_absa import LocalABSAModel
        LocalABSAModel._instance = None
        model = LocalABSAModel.get()
        results = model.predict_batch(["外观好看", "续航差"])
        assert len(results) == 2
        assert results[0]["sentiment"] == "neutral"
        assert results[0]["dim_sentiment"] == {}

    def test_predict_single_unloaded_returns_neutral(self):
        from pipeline.analysis.local_absa import LocalABSAModel
        LocalABSAModel._instance = None
        model = LocalABSAModel.get()
        result = model.predict_single("some text")
        assert result["sentiment"] == "neutral"
