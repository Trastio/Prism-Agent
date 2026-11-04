"""recollect_koubei_with_full nevpool T3 改造单测（cap/守卫/名单/预估/progress）。

全部 mock，不出网不写生产库；recollect_series 的 cap 行为用 FakeAPI + monkeypatch
parse_koubei_item 验证（review_id 用 k_api_ 前缀使 show_id 为空，跳过详情页抓取）。"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import recollect_koubei_with_full as rec  # noqa: E402
from recollect_koubei_with_full import (  # noqa: E402
    append_progress, estimate_requests, find_backup, find_pool_conflicts,
    guard_conflicts, load_pool_series_ids, load_progress, pages_for,
    recollect_series, _parse_args,
)


# ---------------- cap 页数计算 ----------------

def test_pages_for_ceiling():
    assert pages_for(300) == 15   # 300 条 = 15 页
    assert pages_for(1) == 1
    assert pages_for(20) == 1
    assert pages_for(21) == 2
    assert pages_for(301) == 16


def test_pages_for_no_cap():
    assert pages_for(None) is None
    assert pages_for(0) is None
    assert pages_for(-5) is None


def test_pages_for_custom_page_size():
    assert pages_for(300, page_size=50) == 6


# ---------------- 守卫交集判定 ----------------

def test_conflict_detected():
    counts = {"A": 150, "B": 99, "C": 0}
    conflicts = find_pool_conflicts(["A", "B", "C"], lambda s: counts.get(s, 0))
    assert conflicts == [("A", 150)]


def test_no_conflict_passes():
    counts = {"X": 5000}
    assert find_pool_conflicts(["P", "Q"], lambda s: counts.get(s, 0)) == []
    assert find_pool_conflicts([], lambda s: 999) == []


def test_conflict_threshold_is_100_inclusive():
    # 恰好 100 条也算存量分析池（≥100）
    conflicts = find_pool_conflicts(["D"], lambda s: 100)
    assert conflicts == [("D", 100)]


# ---------------- 守卫终版语义：本管线自有写入豁免（T4 续跑不被锁死） ----------------

def test_guard_blocks_preexisting_pool():
    # 存量分析池车系（无 progress 记录）→ 拦截
    assert guard_conflicts(["6298"], lambda s: 2268, {}) == [("6298", 2268)]


def test_guard_exempts_own_write_exact_match():
    # 首批深采入库（150 条）后重跑：progress done 且库内行数与记录相等 → 豁免
    prog = {"7740": {"status": "done", "collected": 150}}
    assert guard_conflicts(["7740"], lambda s: 150, prog) == []


def test_guard_blocks_if_rows_changed_since_progress():
    # progress 记录 150 条但库内已是 160 条（外部变动）→ 仍拦截（fail-closed）
    prog = {"7740": {"status": "done", "collected": 150}}
    assert guard_conflicts(["7740"], lambda s: 160, prog) == [("7740", 160)]


def test_guard_blocks_failed_progress():
    # failed 不是终态豁免（该系未成功写入自有数据）→ 拦截
    prog = {"7712": {"status": "failed", "collected": 0}}
    assert guard_conflicts(["7712"], lambda s: 120, prog) == [("7712", 120)]


def test_guard_exempts_empty_terminal_state():
    # empty 终态（源站无口碑，0 行）且行数一致 → 豁免
    prog = {"X": {"status": "empty", "collected": 0}}
    assert guard_conflicts(["X"], lambda s: 0, prog) == []
    # 注意：0 < 100 本来就不拦，此测试锚定 empty+等号路径不误判


def test_guard_below_threshold_never_blocks():
    assert guard_conflicts(["P"], lambda s: 99, {}) == []


# ---------------- pool-file 解析 ----------------

def test_pool_file_list_form(tmp_path):
    p = tmp_path / "nev_pool.json"
    p.write_text(json.dumps([
        {"series_name": "甲", "series_id": "111", "tier": "deep"},
        {"series_name": "乙", "series_id": "222", "tier": "longtail"},
        {"series_name": "丙", "series_id": "333", "tier": "deep"},
        {"series_name": "丁", "series_id": "444", "tier": "existing"},
    ], ensure_ascii=False), encoding="utf-8")
    assert load_pool_series_ids(p, tier="deep") == ["111", "333"]


def test_pool_file_dict_pool_form(tmp_path):
    p = tmp_path / "nev_pool.json"
    p.write_text(json.dumps({"generated_at": "2026-10-16",
                             "pool": [{"series_id": 7712, "tier": "deep"},
                                      {"series_id": 7382, "tier": "deep"}]}),
                 encoding="utf-8")
    assert load_pool_series_ids(p, tier="deep") == ["7712", "7382"]


def test_pool_file_mapping_form(tmp_path):
    # {sid: record} 映射外壳
    p = tmp_path / "nev_pool.json"
    p.write_text(json.dumps({"7712": {"tier": "deep"}, "7740": {"tier": "longtail"}}),
                 encoding="utf-8")
    assert load_pool_series_ids(p, tier="deep") == ["7712"]


def test_pool_file_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_pool_series_ids(tmp_path / "nope.json")


# ---------------- dry-run 预估（纯函数） ----------------

def test_estimate_requests_with_cap():
    rows = estimate_requests(["1", "2"], 300, {"1": 726, "2": 100})
    by_id = {r["series_id"]: r for r in rows}
    assert by_id["1"] == {"series_id": "1", "available": 726, "capped": 300,
                          "pages": 15, "requests": 315}
    assert by_id["2"]["capped"] == 100          # 可得 < cap
    assert by_id["2"]["pages"] == 5
    assert by_id["2"]["requests"] == 105


def test_estimate_requests_no_cap():
    rows = estimate_requests(["1"], None, {"1": 726})
    assert rows[0]["capped"] == 726 and rows[0]["pages"] == 37


def test_estimate_requests_unknown_series():
    rows = estimate_requests(["404"], 300, {})
    assert rows[0]["available"] is None and rows[0]["requests"] is None


# ---------------- progress 断点 ----------------

def test_progress_roundtrip_and_skip(tmp_path):
    p = tmp_path / "prog.jsonl"
    append_progress(p, {"series_id": "A", "status": "done", "collected": 20})
    append_progress(p, {"series_id": "B", "status": "empty", "collected": 0})
    append_progress(p, {"series_id": "C", "status": "failed", "error": "boom"})
    m = load_progress(p)
    assert m["A"]["status"] == "done"
    assert m["C"]["error"] == "boom"
    # 断点跳过口径：done/empty 跳，failed 重跑
    pending = [sid for sid in ("A", "B", "C")
               if m.get(sid, {}).get("status") not in ("done", "empty")]
    assert pending == ["C"]


def test_progress_missing_file(tmp_path):
    assert load_progress(tmp_path / "none.jsonl") == {}


def test_progress_corrupt_line_skipped(tmp_path):
    p = tmp_path / "prog.jsonl"
    p.write_text('{"series_id": "A", "status": "done"}\nnot-json\n', encoding="utf-8")
    assert set(load_progress(p)) == {"A"}


def test_progress_last_write_wins(tmp_path):
    p = tmp_path / "prog.jsonl"
    append_progress(p, {"series_id": "A", "status": "failed"})
    append_progress(p, {"series_id": "A", "status": "done", "collected": 300})
    assert load_progress(p)["A"]["status"] == "done"


# ---------------- 备份探测 ----------------

def test_find_backup_picks_latest(tmp_path):
    assert find_backup(tmp_path) is None
    (tmp_path / "autohome-pre-nevpool-20261016-200000.db").write_bytes(b"x")
    (tmp_path / "autohome-pre-nevpool-20261016-200017.db").write_bytes(b"x")
    assert find_backup(tmp_path).name.endswith("200017.db")


# ---------------- CLI 解析 ----------------

def test_parse_args_new_flags():
    a = _parse_args(["--series-ids=7712,7740", "--max-reviews", "300"])
    assert a["series_ids"] == ["7712", "7740"] and a["max_reviews"] == 300


def test_parse_args_pool_and_progress():
    a = _parse_args(["--pool-file=data/nev_pool.json",
                     "--progress-file", "p.jsonl", "--max-reviews=50"])
    assert a["pool_file"] == "data/nev_pool.json"
    assert a["progress_file"] == "p.jsonl"
    assert a["max_reviews"] == 50


def test_parse_args_backward_compat_defaults():
    a = _parse_args(["--limit-series", "5"])
    # 口碑周更 change：新增 mode/budget_reviews 两键（缺省 full/None=旧行为不变）
    assert a == {"series_ids": None, "limit_series": 5, "max_reviews": None,
                 "pool_file": None, "progress_file": None, "force": False,
                 "series_delay": 0.0, "mode": "full", "budget_reviews": None}


def test_parse_args_force_and_series_delay():
    a = _parse_args(["--series-ids", "8245,7578", "--force", "--series-delay", "20"])
    assert a["series_ids"] == ["8245", "7578"]
    assert a["force"] is True
    assert a["series_delay"] == 20.0
    b = _parse_args(["--series-ids", "8245"])
    assert b["force"] is False and b["series_delay"] == 0.0


# ---------------- recollect_series cap 行为（mock，不出网） ----------------

class _FakeAPI:
    """pages: {page_no: {"list": [...], "pagecount": n}}；记录调用页码。"""

    def __init__(self, pages):
        self.pages = pages
        self.calls: list[int] = []

    async def fetch_koubei_page(self, series_id, page, page_size=20):
        self.calls.append(page)
        return self.pages.get(page)


@pytest.fixture()
def fake_parse(monkeypatch):
    # review_id 用 k_api_ 前缀 → show_id 为空 → 不抓详情页（client 不出网）
    monkeypatch.setattr(
        rec.AutohomeAPI, "parse_koubei_item",
        staticmethod(lambda item, series_display_name="": {"review_id": f"k_api_{item['i']}"}))


def _fake_pages(n_pages, per_page=20):
    pages = {}
    for p in range(1, n_pages + 1):
        pages[p] = {"list": [{"i": (p - 1) * per_page + k} for k in range(per_page)],
                    "pagecount": n_pages}
    return pages


def test_recollect_series_no_cap_keeps_legacy(fake_parse):
    api = _FakeAPI(_fake_pages(3))

    async def run():
        return await recollect_series(api, None, "7712", asyncio.Semaphore(3))

    results = asyncio.run(run())
    assert len(results) == 60
    assert api.calls == [1, 2, 3]


def test_recollect_series_cap_page_granularity(fake_parse):
    # cap 300 = 15 页；源站 20 页 → 15 页 300 条
    api = _FakeAPI(_fake_pages(20))

    async def run():
        return await recollect_series(api, None, "7712", asyncio.Semaphore(3),
                                      max_reviews=300)

    results = asyncio.run(run())
    assert len(results) == 300
    assert api.calls == list(range(1, 16))


def test_recollect_series_cap_below_one_page(fake_parse):
    api = _FakeAPI(_fake_pages(3))

    async def run():
        return await recollect_series(api, None, "7712", asyncio.Semaphore(3),
                                      max_reviews=1)

    assert len(asyncio.run(run())) == 20  # 页粒度：1 页整页 20 条
    assert api.calls == [1]


def test_recollect_series_cap_natural_end_wins(fake_parse):
    # 源站只有 2 页，cap 300（15 页）→ 自然尽 2 页 40 条
    api = _FakeAPI(_fake_pages(2))

    async def run():
        return await recollect_series(api, None, "7712", asyncio.Semaphore(3),
                                      max_reviews=300)

    assert len(asyncio.run(run())) == 40


def test_recollect_series_dedupes_cross_page_duplicates(fake_parse):
    # 之家翻页不稳定：page2 复现 page1 尾部 5 条、page3 复现 page2 尾部 5 条
    # （铂智3X 2026-10-16 实证：重复 review_id 撞主键整批回滚）→ 去重保首现
    pages = {
        1: {"list": [{"i": k} for k in range(0, 20)], "pagecount": 3},
        2: {"list": [{"i": k} for k in range(15, 35)], "pagecount": 3},
        3: {"list": [{"i": k} for k in range(30, 40)], "pagecount": 3},
    }
    api = _FakeAPI(pages)

    async def run():
        return await recollect_series(api, None, "7712", asyncio.Semaphore(3))

    results = asyncio.run(run())
    rids = [r["review_id"] for r in results]
    assert len(results) == 40                      # 0..39 去重后
    assert len(rids) == len(set(rids))             # 无重复 review_id
    assert api.calls == [1, 2, 3]                  # 翻页语义未变


def test_recollect_series_dedup_keeps_first_occurrence_order(fake_parse):
    pages = {
        1: {"list": [{"i": 1}, {"i": 2}], "pagecount": 2},
        2: {"list": [{"i": 1}, {"i": 3}], "pagecount": 2},
    }
    api = _FakeAPI(pages)

    async def run():
        return await recollect_series(api, None, "7712", asyncio.Semaphore(3))

    results = asyncio.run(run())
    assert [r["review_id"] for r in results] == ["k_api_1", "k_api_2", "k_api_3"]
