"""Tests: 频率分层纯函数（pipeline/frequency.py）。"""
from datetime import date

from pipeline.frequency import (
    HOT_THRESHOLD, MID_THRESHOLD,
    recent_post_counts, _tier_of, select_by_frequency, db_path,
)


def test_thresholds_照搬_daily_update():
    """P1-1：阈值必须照搬 daily_update.py 真实常量，不擅自改。"""
    assert HOT_THRESHOLD == 100
    assert MID_THRESHOLD == 30


def test_tier_of_用大于号不是大于等于():
    """P1-1：> 不是 >=。"""
    assert _tier_of(101) == "hot"
    assert _tier_of(100) == "mid"   # 100 不算 hot（> 不是 >=）
    assert _tier_of(31) == "mid"
    assert _tier_of(30) == "cold"   # 30 不算 mid
    assert _tier_of(0) == "cold"


def test_select_by_frequency_偶数日_mid_跑():
    """P1-1：mid 排期用 today.day % 2 == 0（偶数日），非 weekday()。"""
    vehicles = [{"id": "v1", "name": "车A", "status": "active"}]
    counts = {"v1": 50}  # mid tier
    # 偶数日跑
    even_day = date(2026, 10, 6)  # 6 号偶数
    targets, skipped = select_by_frequency(vehicles, counts, even_day)
    assert len(targets) == 1
    # 奇数日跳过
    odd_day = date(2026, 10, 7)  # 7 号奇数
    targets, skipped = select_by_frequency(vehicles, counts, odd_day)
    assert len(targets) == 0
    assert len(skipped) == 1


def test_select_by_frequency_周一_cold_跑():
    """P1-1：cold 排期用 today.weekday() == 0（周一）。"""
    vehicles = [{"id": "v1", "name": "车A", "status": "active"}]
    counts = {"v1": 0}  # cold tier
    monday = date(2026, 10, 5)  # 周一（2026-10-05 是周一）
    targets, skipped = select_by_frequency(vehicles, counts, monday)
    assert len(targets) == 1
    tuesday = date(2026, 10, 6)  # 周二
    targets, skipped = select_by_frequency(vehicles, counts, tuesday)
    assert len(targets) == 0


def test_select_by_frequency_hot_每天都跑():
    vehicles = [{"id": "v1", "name": "车A", "status": "active"}]
    counts = {"v1": 200}  # hot tier
    for d in [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)]:
        targets, _ = select_by_frequency(vehicles, counts, d)
        assert len(targets) == 1


def test_select_by_frequency_非active跳过():
    vehicles = [{"id": "v1", "name": "车A", "status": "inactive"}]
    counts = {"v1": 200}
    targets, skipped = select_by_frequency(vehicles, counts, date(2026, 10, 6))
    assert len(targets) == 0
    assert len(skipped) == 0  # inactive 不进 skipped


def test_db_path_默认值():
    import os
    os.environ.pop("DB_PATH", None)
    assert db_path() == "data/vehicle_sentiment.db"


def test_recent_post_counts_空列表():
    """空 vehicle_ids 返回空 dict，不报错。"""
    counts = recent_post_counts([], "data/vehicle_sentiment.db")
    assert counts == {}
