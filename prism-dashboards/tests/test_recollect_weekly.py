"""口碑周更增量采集 change 单测（水位/insert-skip/预算帽/零删除断言/台账/catchup）。

全部 mock 或临时 sqlite，零网络零真实库；风格对标 test_recollect_koubei_cap.py。"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import recollect_koubei_with_full as rec  # noqa: E402
from recollect_koubei_with_full import (  # noqa: E402
    page_all_known, recollect_series_incremental, _save_new_reviews,
)
import koubei_weekly_update as kwu  # noqa: E402


# ---------------- 水位停止判定（纯函数） ----------------

def test_page_all_known_true():
    assert page_all_known(["a", "b"], {"a", "b", "c"}) is True


def test_page_all_known_partial():
    # 部分已知（乱序页：新条目混在已知里）→ 不停，继续翻
    assert page_all_known(["a", "new1"], {"a", "b"}) is False


def test_page_all_known_none():
    assert page_all_known([], {"a"}) is False


# ---------------- 增量采集（FakeAPI，不出网） ----------------

class _FakeAPI:
    def __init__(self, pages):
        self.pages = pages
        self.calls: list[int] = []

    async def fetch_koubei_page(self, series_id, page, page_size=20):
        self.calls.append(page)
        return self.pages.get(page)

    async def close(self):
        pass


@pytest.fixture()
def fake_parse(monkeypatch):
    # model_full_name NOT NULL；review_id 用 k_api_ 前缀跳过详情页抓取
    monkeypatch.setattr(
        rec.AutohomeAPI, "parse_koubei_item",
        staticmethod(lambda item, series_display_name="": {
            "review_id": f"k_api_{item['i']}",
            "model_full_name": item.get("seriesname", "测试车系"),
        }))


def test_incremental_collects_only_new_and_stops_on_all_known(fake_parse):
    # 库已知 {0..4}；page1 = [0,1 已知, 5 新]（含新条目 → 计数清零，继续翻）
    # → page2 = [2,3,4]（整页库已知 → 计数 1，加固拍板：单页不停）
    # → page3 = [3,4]（第 2 个连续整页已知 → 停）
    known = {f"k_api_{i}" for i in range(5)}
    pages = {
        1: {"list": [{"i": 0}, {"i": 1}, {"i": 5}], "pagecount": 3},
        2: {"list": [{"i": 2}, {"i": 3}, {"i": 4}], "pagecount": 3},
        3: {"list": [{"i": 3}, {"i": 4}], "pagecount": 3},
    }
    api = _FakeAPI(pages)

    async def run():
        return await recollect_series_incremental(api, None, "7712",
                                                  asyncio.Semaphore(3), known)

    res = asyncio.run(run())
    assert [r["review_id"] for r in res["new"]] == ["k_api_5"]   # 只收集新条目
    assert res["stopped"] == "all_known"
    assert api.calls == [1, 2, 3]   # 连续 2 页全已知（page2+3）才停


def test_incremental_single_known_page_not_stop(fake_parse):
    # 加固拍板 2026-11-01：单页已知不停（防乱序滑深漏采），连续第 2 页才停
    known = {f"k_api_{i}" for i in range(3)}
    pages = {1: {"list": [{"i": 0}, {"i": 1}, {"i": 2}], "pagecount": 5},
             2: {"list": [{"i": 1}, {"i": 2}], "pagecount": 5}}
    api = _FakeAPI(pages)

    async def run():
        return await recollect_series_incremental(api, None, "7712",
                                                  asyncio.Semaphore(3), known)

    res = asyncio.run(run())
    assert res["new"] == []
    assert res["stopped"] == "all_known"
    assert api.calls == [1, 2]   # 第 1 页已知不停，第 2 页连续已知才停


def test_incremental_pagecount_natural_end(fake_parse):
    # 全新车系（known 空）翻尽 pagecount
    pages = {1: {"list": [{"i": 0}, {"i": 1}], "pagecount": 1}}
    api = _FakeAPI(pages)

    async def run():
        return await recollect_series_incremental(api, None, "7712",
                                                  asyncio.Semaphore(3), set())

    res = asyncio.run(run())
    assert len(res["new"]) == 2
    assert res["stopped"] == "pagecount"


def test_incremental_unstable_pagination_not_early_stopped(fake_parse):
    # 乱序页（page1 尾部复现在 page2 头部，之家实证形态）：18/19 首现于 page1 收集，
    # page2 复现 18/19（本轮已见去重）+ 20/21 新；page3 = [20,21] 复现（已见，不重复收）
    # 水位严格用库已知（不含本轮已收）→ page3 不误停，翻尽 pagecount 自然停
    known = {f"k_api_{i}" for i in range(0, 18)}
    pages = {
        1: {"list": [{"i": i} for i in range(15, 20)], "pagecount": 3},
        2: {"list": [{"i": 18}, {"i": 19}, {"i": 20}, {"i": 21}], "pagecount": 3},
        3: {"list": [{"i": 20}, {"i": 21}], "pagecount": 3},
    }
    api = _FakeAPI(pages)

    async def run():
        return await recollect_series_incremental(api, None, "7712",
                                                  asyncio.Semaphore(3), known)

    res = asyncio.run(run())
    # 18/19/20/21 全是新条目，首现收集；18/19/20/21 复现均不重复收集
    assert [r["review_id"] for r in res["new"]] == [
        "k_api_18", "k_api_19", "k_api_20", "k_api_21"]
    assert res["stopped"] == "pagecount"
    assert api.calls == [1, 2, 3]


# ---------------- 临时库 fixture（insert-skip / 断言 / 台账 / 预算帽） ----------------

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """临时 sqlite：init_db 建表（含 collection_runs），预插 3 系各 2 条已知口碑。"""
    db = tmp_path / "weekly_test.db"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(db).replace("\\", "/"))
    from src.storage.db import init_db, session_scope
    init_db()
    from src.models.orm import OwnerReview
    with session_scope() as s:
        for sid in ("7712", "7740", "8666"):
            for k in range(2):
                s.add(OwnerReview(review_id=f"k_api_known_{sid}_{k}",
                                  model_full_name="测试车系", model_id=sid))
    yield db


def _new_parsed(sid: str, n: int) -> list[dict]:
    return [{"review_id": f"k_api_new_{sid}_{k}", "model_full_name": "测试车系"}
            for k in range(n)]


def test_save_new_reviews_insert_skip_idempotent(tmp_db):
    from src.storage.db import session_scope
    from src.models.orm import OwnerReview

    async def run():
        return await _save_new_reviews(_new_parsed("7712", 3), "7712",
                                       known_ids={f"k_api_known_7712_{k}" for k in range(2)})
    assert asyncio.run(run()) == 3
    with session_scope() as s:
        n1 = s.query(OwnerReview).filter(OwnerReview.model_id == "7712").count()
    assert n1 == 5  # 2 已知 + 3 新

    # 同批二次跑（幂等）：known 现在含新 id → 零新增
    with session_scope() as s:
        known2 = {r[0] for r in s.query(OwnerReview.review_id)
                  .filter(OwnerReview.model_id == "7712").all()}
    async def run2():
        return await _save_new_reviews(_new_parsed("7712", 3), "7712", known_ids=known2)
    assert asyncio.run(run2()) == 0
    with session_scope() as s:
        n2 = s.query(OwnerReview).filter(OwnerReview.model_id == "7712").count()
    assert n2 == 5  # insert-skip：二次跑零变化


def test_save_new_reviews_zero_delete_assertion(tmp_db, monkeypatch):
    # 零删除断言：mock 行数计数在插入后返回异常值（模拟外部并发删行）→ RuntimeError
    calls = {"n": 0}
    real_count = rec._db_series_review_count

    def fake_count(mid):
        calls["n"] += 1
        # before 用真值；after（第 2 次调用）返回 before-1 → 断言失败
        v = real_count(mid)
        return v - 1 if calls["n"] >= 2 else v

    monkeypatch.setattr(rec, "_db_series_review_count", fake_count)
    with pytest.raises(RuntimeError, match="零删除断言失败"):
        asyncio.run(_save_new_reviews(_new_parsed("7712", 1), "7712", known_ids=set()))


def test_backfill_untagged_tags_textful_reviews(tmp_db):
    # 加固拍板 2026-11-01：有原文无标签 → 补打；无原文/已打标 → 跳过；幂等复跑零补
    from src.storage.db import session_scope
    from src.models.orm import OwnerReview, ReviewTag

    with session_scope() as s:
        s.add(OwnerReview(review_id="k_api_bf_1", model_full_name="测试车系",
                          model_id="7712", best_review_text="空间大"))
        s.add(OwnerReview(review_id="k_api_bf_2", model_full_name="测试车系",
                          model_id="7712", worst_review_text="续航虚"))
        s.add(OwnerReview(review_id="k_api_bf_3", model_full_name="测试车系",
                          model_id="7712", best_review_text="已打过"))
        s.add(ReviewTag(review_id="k_api_bf_3", owner_id="o", model_full_name="测试车系",
                        model_id="7712", tag_name="空间大", sentiment="pro"))

    class _StubTagger:
        async def extract_tags(self, best, worst):
            return [{"tag_name": "空间大" if best else "续航虚",
                     "sentiment": "pro" if best else "con",
                     "source_text": best or worst, "confidence": 0.9,
                     "tag_category": "空间" if best else "续航"}]

    assert asyncio.run(rec._backfill_untagged("7712", _StubTagger())) == 2
    with session_scope() as s:
        tagged = {r[0] for r in s.query(ReviewTag.review_id)
                  .filter(ReviewTag.model_id == "7712").all()}
    assert {"k_api_bf_1", "k_api_bf_2"} <= tagged
    # 幂等：补过的下周（已知标签）不再补
    assert asyncio.run(rec._backfill_untagged("7712", _StubTagger())) == 0
    # 无 tagger（mock/异常形态）安全返回
    assert asyncio.run(rec._backfill_untagged("7712", None)) == 0


def test_push_enabled_gating(tmp_path, monkeypatch):
    # 方案 A 推送门：env 关=不推；缺凭据文件=不推；两者齐=推
    import importlib
    monkeypatch.setattr(kwu, "SSHPASS_FILE", tmp_path / ".sshpass")
    monkeypatch.setenv("PRISM_KOUBEI_PUSH", "0")
    (tmp_path / ".sshpass").write_text("x")
    assert kwu.push_enabled() is False
    monkeypatch.setenv("PRISM_KOUBEI_PUSH", "1")
    assert kwu.push_enabled() is True
    (tmp_path / ".sshpass").unlink()
    assert kwu.push_enabled() is False


def test_budget_capped_early_exit_and_progress(tmp_db, monkeypatch, tmp_path):
    # 预算帽 2：第 1 系插 2 条后触顶 → 第 2/3 系 budget_capped 早退（progress 留痕）
    progress = tmp_path / "wp.jsonl"

    class _FixedAPI:
        @staticmethod
        def parse_koubei_item(item, series_display_name=""):
            return {"review_id": f"k_api_b_{item['i']}", "model_full_name": "测试车系"}

        async def fetch_koubei_page(self, series_id, page, page_size=20):
            return {"list": [{"i": 900 + int(series_id) % 10}, {"i": 901 + int(series_id) % 10}],
                    "pagecount": 1}

        async def close(self):
            pass

    async def fake_tagger():
        return None

    monkeypatch.setattr(rec, "AutohomeAPI", _FixedAPI)
    monkeypatch.setattr(rec, "get_tagger", fake_tagger)
    monkeypatch.setattr(rec, "close_tagger", fake_tagger)

    stats = asyncio.run(rec.recollect_all(
        mode="incremental", budget_reviews=2, live=True,
        progress_path=str(progress), inter_series_sleep=0))
    assert stats["new_reviews_total"] == 2
    assert len(stats["budget_capped_series"]) == 2       # 7740/8666 早退
    assert not stats["failures"]
    # progress 留痕：1 done + 2 budget_capped
    lines = [json.loads(l) for l in progress.read_text(encoding="utf-8").splitlines() if l]
    statuses = sorted(l["status"] for l in lines)
    assert statuses == ["budget_capped", "budget_capped", "done"]


def test_collection_runs_orm_roundtrip(tmp_db):
    from src.storage.db import session_scope
    from src.models.orm import CollectionRun
    with session_scope() as s:
        s.add(CollectionRun(mode="weekly", series_total=96, series_done=96,
                            new_reviews=37, status="success"))
    with session_scope() as s:
        row = (s.query(CollectionRun).filter(CollectionRun.mode == "weekly")
               .order_by(CollectionRun.run_id.desc()).first())
        assert row.status == "success" and row.new_reviews == 37


# ---------------- catchup 判定（纯函数，时区边界） ----------------

CN = timezone(timedelta(hours=8))
UTC = timezone.utc


def _local(y, m, d, h, minute=0):
    return datetime(y, m, d, h, minute, tzinfo=CN)


def test_catchup_before_seven_no_judge():
    ok, why = kwu.should_catchup(_local(2026, 11, 1, 6, 30),
                                 None, False)
    assert ok is False and "不判定" in why


def test_catchup_never_ran():
    ok, _ = kwu.should_catchup(_local(2026, 11, 1, 9), None, False)
    assert ok is True


def test_catchup_marker_idempotent():
    ok, why = kwu.should_catchup(_local(2026, 11, 1, 9), None, True)
    assert ok is False and "幂等" in why


def test_catchup_stale_triggers():
    last = datetime(2026, 10, 20, 20, 0, tzinfo=UTC)      # 距 11-01 09:00 本地 ≈ 11 天
    ok, why = kwu.should_catchup(_local(2026, 11, 1, 9), last, False)
    assert (ok is True and "11" in why) or (ok is True and "10" in why)  # P2-7c：天数入理由，防永真


def test_catchup_fresh_no_run():
    last = datetime(2026, 10, 31, 20, 0, tzinfo=UTC)      # 距 11-01 09:00 本地 < 8 天
    ok, why = kwu.should_catchup(_local(2026, 11, 1, 9), last, False)
    assert ok is False and "新鲜" in why


def test_catchup_boundary_exactly_stale():
    # 恰好 8 天边界（> 8 天才补）：09:00 本地 = 01:00 UTC，减 8 天整 = 不补
    now = _local(2026, 11, 9, 9)
    last = (now.astimezone(UTC) - timedelta(days=8))
    ok, _ = kwu.should_catchup(now, last, False)
    assert ok is False                                    # 8 天整不触发（严格大于）
    last2 = (now.astimezone(UTC) - timedelta(days=8, seconds=1))
    ok2, _ = kwu.should_catchup(now, last2, False)
    assert ok2 is True                                    # 超 8 天触发


def test_catchup_naive_utc_treated_as_utc():
    # 台账读出 naive datetime（fromisoformat）→ 按 UTC 解释
    last_naive = datetime(2026, 10, 20, 20, 0)            # naive
    ok, _ = kwu.should_catchup(_local(2026, 11, 1, 9), last_naive, False)
    assert ok is True


# ---------------- progress 滚动 ----------------

def test_roll_weekly_progress(tmp_path):
    db = tmp_path / "autohome.db"
    db.write_bytes(b"")                                   # 占位（函数只认 db 路径取 parent）
    cur = tmp_path / "weekly_progress.jsonl"
    cur.write_text("{\"series_id\":\"1\"}\n", encoding="utf-8")
    for i in range(10):
        (tmp_path / f"weekly_progress_2026010{i % 10}-00000{i}.jsonl").write_text("{}", encoding="utf-8")
    rolled = kwu.roll_weekly_progress(db, keep=8)
    assert rolled is not None and rolled.is_file()
    assert not cur.exists()                               # 当前文件已改名
    olds = sorted(tmp_path.glob("weekly_progress_*.jsonl"))
    assert len(olds) == 8                                 # 含新滚入的这份，共 8 份


def test_roll_weekly_progress_noop(tmp_path):
    assert kwu.roll_weekly_progress(tmp_path) is None


# ---------------- 目标库解析 ----------------

def test_resolve_db_prefers_cli(tmp_path):
    f = tmp_path / "x.db"
    f.write_bytes(b"")
    assert kwu.resolve_db_path(str(f)) == f


def test_resolve_db_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        kwu.resolve_db_path(str(tmp_path / "nope.db"))
