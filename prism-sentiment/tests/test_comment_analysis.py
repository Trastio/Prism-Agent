"""Test comment dimension analysis with local ABSA."""
import json
from models.schemas import PostComment


def test_postcomment_has_dim_sentiment_column():
    """Verify PostComment model has dim_sentiment attribute."""
    assert hasattr(PostComment, "dim_sentiment"), "dim_sentiment column missing"


def test_dim_sentiment_stores_json():
    """dim_sentiment should store valid JSON dict."""
    pc = PostComment(
        id="test-c1", post_id="p1", vehicle_id="v1",
        content="续航不行但空间大", author="用户A",
        dim_sentiment='{"续航里程": -1, "空间": 1}',
    )
    dims = json.loads(pc.dim_sentiment)
    assert dims["续航里程"] == -1
    assert dims["空间"] == 1


def test_dim_sentiment_defaults_none():
    """New comments without analysis should have dim_sentiment=None."""
    pc = PostComment(
        id="test-c2", post_id="p2", vehicle_id="v1",
        content="普通评论", author="用户B",
    )
    assert pc.dim_sentiment is None
