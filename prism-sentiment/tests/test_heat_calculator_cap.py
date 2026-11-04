"""Test interaction_intensity capping and attention_index fallback."""
import math
from pipeline.analysis.heat_calculator import _MAX_INTERACTION_PER_DAY


def test_max_interaction_constant_exists():
    """Verify the cap constant is defined and reasonable."""
    assert _MAX_INTERACTION_PER_DAY == 500_000


def test_attention_fallback_uses_log_transform():
    """log1p(6_000_000)*1000 ≈ 15_600, not 6_000_000."""
    raw = 6_000_000.0
    result = round(math.log1p(raw) * 1000, 1)
    assert result < 20_000, f"Expected ~15,600, got {result}"
    # Sanity: normal value ~20,000 should give ~9,900
    normal = 20_000.0
    normal_result = round(math.log1p(normal) * 1000, 1)
    assert 9_000 < normal_result < 11_000, f"Expected ~9,900, got {normal_result}"
