"""backfill_tags_pool T5 单测：名称解析 / 差集选取 / 覆盖率计算 / 打标写入。

全部 mock tagger，不出网；DB 用 tmp_path 一次性 sqlite（init_db 显式传 url，
不打生产库）。"""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import backfill_tags_pool as bt  # noqa: E402
import src.storage.db as sdb  # noqa: E402
from src.models.orm import OwnerReview, ReviewTag  # noqa: E402
from src.storage.db import init_db  # noqa: E402


# ---------------- fixture：一次性 sqlite，前后重置全局引擎 ----------------

@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sdb._engine = None
    sdb._SessionLocal = None
    init_db(f"sqlite:///{tmp_path / 't5test.db'}")
    yield
    sdb._engine = None
    sdb._SessionLocal = None


def _seed_review(rid, model_id="7982", best="", worst="", bfull="", wfull="",
                 owner="o1", full_name="海狮05 EV 2025款 605领航版"):
    with sdb.session_scope() as s:
        s.add(OwnerReview(review_id=rid, owner_id=owner, model_full_name=full_name,
                          model_id=model_id, best_review_text=best,
                          worst_review_text=worst, best_full_text=bfull,
                          worst_full_text=wfull))


class FakeTagger:
    """不出网 mock：fn(best, worst) -> tags list；记录调用入参。"""

    def __init__(self, fn):
        self.fn = fn
        self.calls = []

    async def extract_tags(self, best, worst):
        self.calls.append((best, worst))
        return self.fn(best, worst)


def _tag(name="动力强", senti="pro", cat="驾驶感受"):
    return {"tag_category": cat, "tag_name": name, "sentiment": senti,
            "confidence": 0.9, "source_text": "原文片段"}


# ---------------- 名称精确解析（红线#7，不猜 ID） ----------------

def test_resolve_names_exact_unique():
    table = {"元UP": ["7538"], "海狮05 EV": ["7982"]}
    resolved, unresolved = bt.resolve_names(["元UP", "海狮05 EV"],
                                            lambda n: table.get(n, []))
    assert resolved == {"元UP": "7538", "海狮05 EV": "7982"}
    assert unresolved == {}


def test_resolve_names_not_found_reported_not_guessed():
    # 库内只有"海狮06"，目标名"海狮06 DM-i"精确匹配失败 → 必须进 unresolved，不许绑 8087
    table = {"海狮06": ["8087"]}
    resolved, unresolved = bt.resolve_names(["海狮06 DM-i"], lambda n: table.get(n, []))
    assert resolved == {}
    assert unresolved["海狮06 DM-i"] == {"reason": "not_found", "candidates": []}


def test_resolve_names_ambiguous():
    resolved, unresolved = bt.resolve_names(["X"], lambda n: ["2", "1"])
    assert resolved == {}
    assert unresolved["X"]["reason"] == "ambiguous"
    assert unresolved["X"]["candidates"] == ["1", "2"]


def test_resolve_names_partial_mixed():
    table = {"元UP": ["7538"]}
    resolved, unresolved = bt.resolve_names(["元UP", "缺"], lambda n: table.get(n, []))
    assert resolved == {"元UP": "7538"}
    assert set(unresolved) == {"缺"}


# ---------------- 差集选取 ----------------

def test_untagged_ids_diff_order_preserving():
    assert bt.untagged_ids(["a", "b", "c"], ["b"]) == ["a", "c"]


def test_untagged_ids_empty_sides():
    assert bt.untagged_ids(["a"], []) == ["a"]
    assert bt.untagged_ids([], ["x"]) == []
    assert bt.untagged_ids([], []) == []


def test_untagged_ids_tagged_dup_ignored():
    assert bt.untagged_ids(["a", "b", "c"], ["b", "b"]) == ["a", "c"]


# ---------------- 覆盖率计算 ----------------

def test_coverage_ratio_basic():
    assert bt.coverage_ratio(7, 10) == pytest.approx(0.7)
    assert bt.coverage_ratio(0, 10) == 0.0
    assert bt.coverage_ratio(10, 10) == 1.0


def test_coverage_ratio_zero_total_is_zero():
    assert bt.coverage_ratio(0, 0) == 0.0
    assert bt.coverage_ratio(5, 0) == 0.0


def test_meets_target_threshold():
    assert bt.meets_target(0.70)
    assert not bt.meets_target(0.699)
    assert bt.meets_target(0.5, target=0.5)


# ---------------- 打标输入选择 ----------------

def test_pick_tag_input_prefers_short_text():
    assert bt.pick_tag_input("短best", "短worst", "全best", "全worst") == ("短best", "短worst")


def test_pick_tag_input_falls_back_full_text():
    assert bt.pick_tag_input("", " ", "全best", "全worst") == ("全best", "全worst")
    assert bt.pick_tag_input(None, None, "全best", "") == ("全best", "")


def test_pick_tag_input_all_empty():
    assert bt.pick_tag_input("", "", "", "") == ("", "")
    assert bt.pick_tag_input(None, None, None, None) == ("", "")


def test_pick_tag_input_mixed_sides():
    # best 侧有短文本、worst 侧只有全文 → 逐侧独立回退
    assert bt.pick_tag_input("短", "", "", "全worst") == ("短", "全worst")


# ---------------- split_taggable ----------------

def test_split_taggable_and_no_text():
    rows = [
        {"review_id": "r1", "best_review_text": "a", "worst_review_text": "",
         "best_full_text": "", "worst_full_text": ""},
        {"review_id": "r2", "best_review_text": "", "worst_review_text": "",
         "best_full_text": "全文", "worst_full_text": ""},
        {"review_id": "r3", "best_review_text": "", "worst_review_text": "",
         "best_full_text": "", "worst_full_text": ""},
    ]
    taggable, no_text = bt.split_taggable(rows)
    assert [t[0]["review_id"] for t in taggable] == ["r1", "r2"]
    assert no_text == 1


# ---------------- 备份探测 ----------------

def test_find_backup_picks_latest(tmp_path):
    assert bt.find_backup(tmp_path) is None
    (tmp_path / "autohome-pre-nevpool-20261016-200000.db").write_bytes(b"x")
    (tmp_path / "autohome-pre-nevpool-20261016-200017.db").write_bytes(b"x")
    assert bt.find_backup(tmp_path).name.endswith("200017.db")


# ---------------- 写入路径（temp DB + mock tagger） ----------------

def test_insert_tags_dedupes_and_filters(temp_db):
    _seed_review("r1", best="x")
    row = bt.load_untagged_rows("7982")[0]
    tags = [_tag("动力强", "pro"), _tag("动力强", "pro"),       # 批内重复
            _tag("噪音大", "neutral"),                          # 非法 sentiment
            _tag("", "pro")]                                    # 空名
    assert bt.insert_tags(row, tags, "7982") == 1
    with sdb.session_scope() as s:
        rows = s.query(ReviewTag).all()
        assert len(rows) == 1
        assert rows[0].review_id == "r1" and rows[0].tag_name == "动力强"
        assert rows[0].model_id == "7982" and rows[0].sentiment == "pro"


def test_insert_tags_skips_existing_pair_idempotent(temp_db):
    _seed_review("r1", best="x")
    row = bt.load_untagged_rows("7982")[0]
    assert bt.insert_tags(row, [_tag()], "7982") == 1
    # 同 (review_id, tag_name, sentiment) 重放 → 库内已存在，跳过（防撞唯一索引）
    assert bt.insert_tags(row, [_tag()], "7982") == 0


def test_backfill_series_inserts_tags_owner_reviews_untouched(temp_db):
    _seed_review("r1", best="动力强，好开")
    _seed_review("r2", best="", worst="", bfull="全文best", wfull="全文worst")
    _seed_review("r3")  # 纯图片无文本 → 物理不可打

    def fn(best, worst):
        return [_tag()] if best or worst else []

    stats = asyncio.run(bt.backfill_series("7982", FakeTagger(fn)))
    assert stats["invariant_ok"]
    assert stats["pre_count"] == 3 and stats["post_count"] == 3   # owner_reviews 零触碰
    assert stats["untagged"] == 3 and stats["taggable"] == 2 and stats["no_text"] == 1
    assert stats["newly_tagged"] == 2 and stats["inserted"] == 2 and stats["failed"] == 0
    with sdb.session_scope() as s:
        assert s.query(OwnerReview).count() == 3                  # 行数不变
        tagged_rids = {t.review_id for t in s.query(ReviewTag).all()}
        assert tagged_rids == {"r1", "r2"}                        # r3 无文本被跳过


def test_backfill_series_uses_full_text_fallback(temp_db):
    # 短文本空、全文在 → tagger 入参应是全文
    _seed_review("r1", best="", bfull="这是详情页全文")
    got = {}

    def fn(best, worst):
        got["best"] = best
        return [_tag()]

    asyncio.run(bt.backfill_series("7982", FakeTagger(fn)))
    assert got["best"] == "这是详情页全文"


def test_backfill_series_idempotent_second_run_noop(temp_db):
    _seed_review("r1", best="空间大")
    tagger = FakeTagger(lambda b, w: [_tag("空间大", "pro", "空间")])
    first = asyncio.run(bt.backfill_series("7982", tagger))
    assert first["inserted"] == 1
    second = asyncio.run(bt.backfill_series("7982", tagger))
    # 首跑后 r1 已有标签 → 差集为空，不再调 tagger
    assert second["untagged"] == 0 and second["taggable"] == 0
    assert second["inserted"] == 0
    assert len(tagger.calls) == 1


def test_backfill_series_counts_failed_items_but_continues(temp_db):
    _seed_review("r1", best="a")
    _seed_review("r2", best="b")

    class BoomTagger:
        async def extract_tags(self, best, worst):
            raise RuntimeError("LLM 超时")

    stats = asyncio.run(bt.backfill_series("7982", BoomTagger()))
    assert stats["failed"] == 2 and stats["inserted"] == 0
    assert stats["invariant_ok"]           # 单条失败不影响本系继续与对账


# ---------------- 断网静默空跑熔断（TaggerUnreachable） ----------------

def test_backfill_series_aborts_on_consecutive_empty_streak(temp_db):
    # 断网时 tagger 吞错返回 []：连续 EMPTY_STREAK_ABORT 条空 → 本系熔断，不许静默空跑
    for k in range(20):
        _seed_review(f"r{k}", best=f"文本{k}")

    class DeadNetTagger:
        async def extract_tags(self, best, worst):
            return []                      # 网络错误被 tagger 吞成空返回

    with pytest.raises(bt.TaggerUnreachable, match="连续 12 条返回空"):
        asyncio.run(bt.backfill_series("7982", DeadNetTagger()))
    assert bt.tagged_distinct_count("7982") == 0        # 零写入
    assert bt.count_owner_reviews("7982") == 20         # owner_reviews 零触碰


def test_backfill_series_empty_streak_resets_on_success(temp_db):
    # 11 条空（未达阈值）后 1 条成功 → 计数清零，继续正常跑
    for k in range(13):
        _seed_review(f"r{k}", best=f"文本{k}")
    calls = {"n": 0}

    class FlakyTagger:
        async def extract_tags(self, best, worst):
            calls["n"] += 1
            return [] if calls["n"] <= 11 else [_tag()]

    stats = asyncio.run(bt.backfill_series("7982", FlakyTagger()))
    assert stats["newly_tagged"] == 2 and stats["inserted"] == 2   # r11、r12 成功
    assert stats["failed"] == 0


# ---------------- coverage 汇总（backfill 后口径） ----------------

def test_coverage_after_backfill_matches_db(temp_db):
    _seed_review("r1", best="a")
    _seed_review("r2")  # 无文本
    asyncio.run(bt.backfill_series("7982", FakeTagger(lambda b, w: [_tag()])))
    tagged = bt.tagged_distinct_count("7982")
    total = bt.count_owner_reviews("7982")
    text_having = bt.count_text_having("7982")
    assert bt.coverage_ratio(tagged, total) == pytest.approx(1 / 2)     # total 口径
    assert bt.coverage_ratio(tagged, text_having) == pytest.approx(1.0)  # 可打标分母口径
