"""Test subject_name column exists and stores competitor names."""
import pytest
from models.schemas import AnalyzedPost


def test_analyzed_post_has_subject_name_column():
    """Verify AnalyzedPost model has subject_name attribute."""
    assert hasattr(AnalyzedPost, "subject_name"), (
        "AnalyzedPost.subject_name column missing — run migration first"
    )


def test_subject_name_defaults_to_empty():
    """subject_name should default to empty string for new records."""
    ap = AnalyzedPost(
        id="test-01", post_id="p1", vehicle_id="v1",
        sentiment="neutral", subject="self",
    )
    assert ap.subject_name == "" or ap.subject_name is None


def test_subject_name_stores_competitor_name():
    """Competitor posts should store the competitor car name."""
    ap = AnalyzedPost(
        id="test-02", post_id="p2", vehicle_id="v1",
        sentiment="neutral", subject="competitor",
        subject_name="比亚迪海豚",
    )
    assert ap.subject_name == "比亚迪海豚"
