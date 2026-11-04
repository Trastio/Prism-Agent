from pipeline.collectors.post_utils import derive_comment_sentiment


def test_positive():
    assert derive_comment_sentiment({"续航": 0.5, "动力": 0.8}) == "positive"


def test_negative():
    assert derive_comment_sentiment({"刹车": -0.5, "异响": -0.8}) == "negative"


def test_neutral_avg_in_range():
    assert derive_comment_sentiment({"价格": 0.2, "外观": -0.1}) == "neutral"


def test_all_zeros():
    assert derive_comment_sentiment({"续航": 0, "价格": 0}) == "neutral"


def test_none():
    assert derive_comment_sentiment(None) == "neutral"


def test_empty_dict():
    assert derive_comment_sentiment({}) == "neutral"


def test_json_string():
    assert derive_comment_sentiment('{"刹车": -0.6}') == "negative"


def test_boundary_03():
    """0.3 边界：>0.3 才 positive，0.3 是 neutral"""
    assert derive_comment_sentiment({"x": 0.3}) == "neutral"  # 不 >0.3
    assert derive_comment_sentiment({"x": 0.31}) == "positive"


def test_boundary_neg03():
    assert derive_comment_sentiment({"x": -0.3}) == "neutral"  # 不 <-0.3
    assert derive_comment_sentiment({"x": -0.31}) == "negative"
