"""T1 舆情降本参数批单测（2026-10-15 change 舆情采集降本）。

覆盖：缺陷词 P1 轮换确定性 / initial 首采窗 env。
（6 词构成断言在 test_defect_keywords；平台注册表在 test_platform_strategy。）
"""
from datetime import date, timedelta

import pytest


_WORDS = [f"车名 词{i}" for i in range(1, 13)]  # 12 缺陷词


class TestRotateDefectWords:
    def test_same_date_same_group_deterministic(self):
        from pipeline.scheduler import rotate_defect_words
        d = date(2026, 10, 15)
        a = rotate_defect_words(_WORDS, today=d, rotate_days=2)
        b = rotate_defect_words(_WORDS, today=d, rotate_days=2)
        assert a == b and len(a) == 3

    def test_group_changes_after_rotate_days(self):
        from pipeline.scheduler import rotate_defect_words
        d0 = date(2026, 10, 15)
        g0 = rotate_defect_words(_WORDS, today=d0, rotate_days=2)
        # 同轮换周期内（次日）同组
        assert rotate_defect_words(_WORDS, today=d0 + timedelta(days=1), rotate_days=2) == g0
        # 跨周期（+2 天）换组
        assert rotate_defect_words(_WORDS, today=d0 + timedelta(days=2), rotate_days=2) != g0

    def test_full_cycle_covers_all_words(self):
        """rotate_days=2、12 词 4 组：8 天一轮，4 组并集 = 全词表。"""
        from pipeline.scheduler import rotate_defect_words
        d0 = date(2026, 10, 15)
        groups = [tuple(rotate_defect_words(_WORDS, today=d0 + timedelta(days=2 * k),
                                            rotate_days=2)) for k in range(4)]
        union = [w for g in groups for w in g]
        assert sorted(union) == sorted(_WORDS)
        assert len(set(union)) == 12

    def test_env_rotate_days_takes_effect(self, monkeypatch):
        from pipeline.scheduler import rotate_defect_words
        monkeypatch.setenv("DEFECT_ROTATE_DAYS", "1")
        # rotate_days=1 = 回退档"永远前 3"：任意日期同结果 → 证明 env 被读取生效
        g_a = rotate_defect_words(_WORDS, today=date(2026, 10, 15))
        g_b = rotate_defect_words(_WORDS, today=date(2026, 11, 20))
        assert g_a == g_b == _WORDS[:3]

    def test_rotate_days_one_degrades_to_top3(self):
        from pipeline.scheduler import rotate_defect_words
        assert rotate_defect_words(_WORDS, today=date(2026, 10, 15),
                                   rotate_days=1) == _WORDS[:3]

    def test_short_list_returned_as_is(self):
        from pipeline.scheduler import rotate_defect_words
        assert rotate_defect_words(["a", "b"], today=date(2026, 10, 15)) == ["a", "b"]


class TestInitialWindowEnv:
    def _ranges(self):
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler.__new__(CollectionScheduler)
        return s._get_date_ranges("initial", None)

    def test_default_30_days(self):
        today = date.today()
        assert self._ranges()[0][0] == (today - timedelta(days=30)).strftime("%Y-%m-%d")

    def test_env_override(self, monkeypatch):
        import pipeline.scheduler as sched_mod
        monkeypatch.setattr(sched_mod, "_INITIAL_WINDOW_DAYS", 45, raising=False)
        today = date.today()
        assert self._ranges()[0][0] == (today - timedelta(days=45)).strftime("%Y-%m-%d")
