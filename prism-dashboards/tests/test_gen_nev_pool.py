"""T1 单测：新能源车池名单生成器（gen_nev_pool）。

覆盖：窗口动态选取（跳零售空批）/ §3.1 过滤与聚合 / 双断言（能源构成+盘子环比）/
tier 分层 / ID 绑定（exact→search→manual_review，无子串绑定）/ 共壳检测 /
绑定缓存复用 / .prev 轮转。

全部不出网：绑定走注入的 FakeApi；库用内存 sqlite3 临时表（最小 DDL，
字段与 gen_nev_pool 用到的列同名）。
"""
import asyncio
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

import gen_nev_pool as g  # noqa: E402


# ---------- fixture 库 ----------

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(
        "CREATE TABLE sales_trim ("
        " model_code TEXT PRIMARY KEY, year INT, month TEXT, manufacturer TEXT,"
        " brand TEXT, series TEXT, level TEXT, body TEXT, energy_type TEXT,"
        " prod_status TEXT, msrp REAL, retail INT)")
    c.execute(
        "CREATE TABLE owner_reviews ("
        " review_id TEXT PRIMARY KEY, model_id TEXT, model_full_name TEXT)")
    c.execute("CREATE TABLE series_summaries (series_id TEXT PRIMARY KEY, review_count INT)")
    return c


def _ins(conn, code, series, month, body, energy, retail, msrp,
         year=2026, prod="在产", mfr="甲厂", level="紧凑型SUV", brand="甲牌"):
    conn.execute(
        "INSERT INTO sales_trim (model_code, year, month, manufacturer, brand,"
        " series, level, body, energy_type, prod_status, msrp, retail)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (code, year, month, mfr, brand, series, level, body, energy, prod, msrp, retail))


def _rev(conn, rid, model_id):
    conn.execute("INSERT INTO owner_reviews (review_id, model_id, model_full_name)"
                 " VALUES (?,?,?)", (rid, model_id, "full-name"))


@pytest.fixture()
def conn():
    c = _conn()
    # 窗口锚点行：让 5-8 月末在窗口检测里"有零售"，但两厢+传统能源永不入池
    # （9月末零售 None → 该批 retail_rows=0 → 应被跳过）
    for m, r in (("9月末", None), ("8月末", 2000), ("7月末", 1500), ("6月末", 500), ("5月末", 100)):
        _ins(c, f"base-{m}", "锚点月批", m, "两厢", "传统能源", r, 100000)
    _ins(c, "jia-9m", "甲A 纯电", "9月末", "SUV", "纯电动", None, 99000)  # 属性行零售空
    _ins(c, "jia-8a", "甲A 纯电", "8月末", "SUV", "纯电动", 2000, 100000, mfr="甲厂新")
    _ins(c, "jia-8b", "甲A 纯电", "8月末", "SUV", "纯电动", 2000, 120000, mfr="甲厂新")
    _ins(c, "jia-7a", "甲A 纯电", "7月末", "SUV", "纯电动", 1500, 110000)
    _ins(c, "jia-6a", "甲A 纯电", "6月末", "SUV", "纯电动", 500, 110000)
    # 乙B：插混三厢，零售 2500（≤3000 → longtail）
    _ins(c, "yi-8", "乙B 插混", "8月末", "三厢", "插电式混合", 1500, 90000)
    _ins(c, "yi-7", "乙B 插混", "7月末", "三厢", "插电式混合", 1000, 90000)
    # 丙C：增程 MPV，零售 10000，本地口碑 150（existing）
    _ins(c, "bing-8", "丙C 增程", "8月末", "MPV", "增程式混合", 10000, 200000)
    for i in range(150):
        _rev(c, f"r-bing-{i}", "bing-sid")
    # 边E：中位数恰 250000 → 在池内（方案 §3.3 极氪7X/理想L6 边界）
    _ins(c, "bian-8a", "边E 纯电", "8月末", "SUV", "纯电动", 500, 240000)
    _ins(c, "bian-8b", "边E 纯电", "8月末", "SUV", "纯电动", 500, 260000)
    # 应剔除项
    _ins(c, "gui-8", "贵D 超价", "8月末", "SUV", "纯电动", 5000, 260000)
    _ins(c, "gui-7", "贵D 超价", "7月末", "SUV", "纯电动", 5000, 270000)
    _ins(c, "you-8", "油F 燃油", "8月末", "SUV", "传统能源", 5000, 100000)
    _ins(c, "liang-8", "两G 两厢", "8月末", "两厢", "纯电动", 5000, 100000)
    _ins(c, "ting-8", "停H 停产", "8月末", "SUV", "纯电动", 5000, 100000, prod="停产")
    _ins(c, "wuling-8", "无零I 无零售", "8月末", "SUV", "纯电动", None, 100000)
    # 源站口碑量（壳表）
    c.execute("INSERT INTO series_summaries (series_id, review_count) VALUES ('bing-sid', 10020)")
    yield c
    c.close()


class FakeApi:
    """不出网的假 autohome api：index={sid:{name,brand_name}}，search={kw:[hits]}。"""

    def __init__(self, index=None, search=None):
        self.index = index or {}
        self.search = search or {}
        self.index_calls = 0
        self.search_calls = []

    async def build_series_index(self):
        self.index_calls += 1
        return self.index

    async def search_series(self, keyword):
        self.search_calls.append(keyword)
        return self.search.get(keyword, [])


def _entry(name, retail=5000, **kw):
    e = {"sales_name": name, "body_cat": "SUV", "retail_3m": retail,
         "msrp_p50": 100000.0, "energy_type": "纯电动", "tier": None,
         "series_id": None, "binding": None, "manufacturer": "甲厂", "level": "SUV",
         "local_review_count": None, "source_review_count": None}
    e.update(kw)
    return e


# ---------- 分类 ----------

def test_classify_body():
    assert g.classify_body("SUV") == "SUV"
    assert g.classify_body("三厢") == "SD"
    assert g.classify_body("MPV") == "MPV"
    assert g.classify_body("两厢") is None
    assert g.classify_body("掀背") is None
    assert g.classify_body(None) is None


def test_classify_energy_substring_shorter_than_db_values():
    # §3.2 勘误防线：子串必须比库值短，全词匹配会静默漏掉插混
    assert g.classify_energy("纯电动") == "纯电"
    assert g.classify_energy("插电式混合") == "插混"
    assert g.classify_energy("增程式混合") == "增程"
    assert g.classify_energy("燃料电池") == "燃料电池"
    assert g.classify_energy("传统能源") is None
    assert g.classify_energy("油电混合") is None  # HEV 排除（拍板②）
    assert g.classify_energy(None) is None


# ---------- 窗口 ----------

def test_latest_retail_window_skips_empty_batch_and_older(conn):
    w = g.latest_retail_window(conn)
    assert w["months"] == ["6月末", "7月末", "8月末"]  # 9月末零售全空被跳过
    assert w["year"] == 2026
    assert w["batches"] == [{"year": 2026, "month": "6月末"},
                            {"year": 2026, "month": "7月末"},
                            {"year": 2026, "month": "8月末"}]
    assert w["skipped_empty_retail"] == [{"year": 2026, "month": "9月末",
                                          "reason": "retail_all_empty"}]


def test_load_window_rows_scopes_to_batches(conn):
    w = g.latest_retail_window(conn)
    rows = g.load_window_rows(conn, w)
    months = {r["month"] for r in rows}
    # 只取窗口三批；被跳过的 9月末批不进窗口
    assert months == {"6月末", "7月末", "8月末"}
    assert all(r["year"] == 2026 for r in rows)


# ---------- 过滤与聚合 ----------

def test_build_pool_filters_and_aggregates(conn):
    rows = g.load_window_rows(conn, g.latest_retail_window(conn))
    pool, stats = g.build_pool(rows)
    names = {e["sales_name"] for e in pool}
    assert names == {"甲A 纯电", "乙B 插混", "丙C 增程", "边E 纯电"}
    assert stats["dropped_over_price"] == 1          # 贵D
    jia = next(e for e in pool if e["sales_name"] == "甲A 纯电")
    assert jia["retail_3m"] == 6000                  # 只计合格零售行(2000+2000+1500+500)
    assert jia["msrp_p50"] == 110000.0               # 中位数=合格行（9月末 99000 不入）
    assert jia["body_cat"] == "SUV"
    assert jia["manufacturer"] == "甲厂新"            # metadata 取最新月
    assert jia["energy_type"] == "纯电动"
    bian = next(e for e in pool if e["sales_name"] == "边E 纯电")
    assert bian["msrp_p50"] == 250000.0              # 恰 25 万 → 在池内
    assert all(e["tier"] is None and e["series_id"] is None for e in pool)


def test_build_pool_empty_is_empty(conn):
    pool, stats = g.build_pool([])
    assert pool == [] and stats["rows_kept"] == 0


# ---------- 断言 ----------

def test_energy_assertion_pass(conn):
    rows = g.load_window_rows(conn, g.latest_retail_window(conn))
    pool, _ = g.build_pool(rows)
    a = g.assert_energy_composition(pool)
    assert a["passed"] is True
    assert a["buckets"] == {"纯电": 2, "插混": 1, "增程": 1}
    assert a["three_categories_positive"] is True
    assert a["sum_equals_universe"] is True and a["universe"] == 4


def test_energy_assertion_fail_when_phev_missing():
    # §3.2 事故形态：插混全漏 → 三类计数含 0 → fail-closed
    pool = [_entry("纯电甲"), _entry("纯电乙")]
    a = g.assert_energy_composition(pool)
    assert a["passed"] is False
    assert a["three_categories_positive"] is False


def test_energy_assertion_fail_on_empty_pool():
    assert g.assert_energy_composition([])["passed"] is False


def test_prev_delta_within_tolerance():
    a = g.assert_prev_delta(110, 100)
    assert a["passed"] is True and a["delta_pct"] == 0.1


def test_prev_delta_blocked_and_forced():
    a = g.assert_prev_delta(120, 100)
    assert a["passed"] is False and a["delta_pct"] == 0.2
    f = g.assert_prev_delta(120, 100, force=True)
    assert f["passed"] is True and f["forced"] is True  # --force 豁免留痕


def test_prev_delta_skips_without_prev():
    a = g.assert_prev_delta(289, None, prev_status="no_prev")
    assert a["passed"] is True and a["skipped"] == "no_prev"


# ---------- tier ----------

def test_assign_tiers_boundaries():
    pool = [
        _entry("存量", retail=10000, binding="exact", series_id="s1", local_review_count=100),
        _entry("深采", retail=3001, binding="search", series_id="s2", local_review_count=99),
        _entry("门槛", retail=3000, binding="exact", series_id="s3", local_review_count=0),
        _entry("未绑", retail=99999, binding=None),
    ]
    g.assign_tiers(pool)
    assert [e["tier"] for e in pool] == ["existing", "deep", "longtail", None]


# ---------- 绑定 ----------

def test_bind_exact_then_search_then_manual():
    api = FakeApi(
        index={"1": {"name": "甲A 纯电", "brand_name": "甲牌"},
               "2": {"name": "乙B", "brand_name": "乙牌"},
               "10a": {"name": "含糊精确", "brand_name": "子牌"},
               "10b": {"name": "含糊精确", "brand_name": "丑牌"}},
        search={"丙C 增程": [{"series_id": "3", "name": "丙C 增程", "brand_name": "丙牌"}],
                "歧义车": [{"series_id": "9", "name": "歧义车", "brand_name": "子牌"},
                          {"series_id": "8", "name": "歧义车", "brand_name": "丑牌"}]})
    pool = [
        _entry("甲A 纯电"),           # 索引名精确 → exact
        _entry("乙牌 乙B"),           # 品牌名+车系名精确 → exact
        _entry("丙C 增程"),           # 索引未命中 → search 唯一精确 → search
        _entry("歧义车"),             # search 双精确命中 → manual_review(ambiguous)
        _entry("查无车"),             # 无命中 → manual_review(not_found)
        _entry("含糊精确"),           # 索引同名两条 → manual_review(ambiguous_exact)
    ]
    stats = asyncio.run(g.bind_pool(pool, {}, api, delay=0))
    assert pool[0]["series_id"] == "1" and pool[0]["binding"] == "exact"
    assert pool[1]["series_id"] == "2" and pool[1]["binding"] == "exact"
    assert pool[2]["series_id"] == "3" and pool[2]["binding"] == "search"
    assert pool[3]["binding"] == "manual_review" and pool[3]["_review_reason"] == "ambiguous_search"
    assert pool[4]["binding"] == "manual_review" and pool[4]["_review_reason"] == "not_found"
    assert pool[5]["binding"] == "manual_review" and pool[5]["_review_reason"] == "ambiguous_exact"
    assert pool[3]["series_id"] is None and pool[4]["series_id"] is None  # 不静默绑定
    assert stats == {"reused": 0, "exact": 2, "search": 1, "manual_review": 3}


def test_bind_rate_limit_between_search_calls():
    api = FakeApi(search={"甲": [], "乙": []})
    pool = [_entry("甲"), _entry("乙")]
    t0 = time.monotonic()
    asyncio.run(g.bind_pool(pool, {}, api, delay=0.05))
    elapsed = time.monotonic() - t0
    assert api.search_calls == ["甲", "乙"]
    assert elapsed >= 0.04  # 第二次调用前有 ≥delay 间隔


def test_binding_cache_reuse_avoids_network():
    api = FakeApi(index={"1": {"name": "甲A 纯电", "brand_name": "甲牌"}})  # 无价带 → 守卫放行
    cache = {g.norm_name("甲A 纯电"): {"series_id": "1", "binding": "exact",
                                       "source_review_count": 7}}
    pool = [_entry("甲A 纯电")]
    stats = asyncio.run(g.bind_pool(pool, cache, api, delay=0))
    assert stats["reused"] == 1
    assert pool[0]["series_id"] == "1" and pool[0]["binding"] == "exact"
    assert pool[0]["source_review_count"] == 7
    assert api.index_calls == 1 and api.search_calls == []  # 只拉一次索引复核，无逐项出网


def test_price_mismatch_guards_wrong_shell_binding():
    # 传祺E8 案例：CAM 插电 p50 23.28万 vs 之家同名燃油壳 17.98万 → 拒绑进人工复核
    api = FakeApi(index={"fuel": {"name": "传祺E8", "brand_name": "广汽传祺",
                                  "price_range": "17.98-17.98万"},
                         "phev": {"name": "传祺E8 PHEV", "brand_name": "广汽传祺",
                                  "price_range": "23.28-23.88万"}})
    pool = [_entry("传祺E8", msrp_p50=232800.0)]
    stats = asyncio.run(g.bind_pool(pool, {}, api, delay=0))
    assert stats["exact"] == 0 and stats["manual_review"] == 1
    e = pool[0]
    assert e["binding"] == "manual_review" and e["series_id"] is None
    assert e["_review_reason"] == "price_mismatch"
    cand_ids = [c["series_id"] for c in e["_candidates"]]
    assert cand_ids == ["fuel", "phev"]  # 同族候选并列给人审


def test_price_guard_passes_when_band_matches_or_missing():
    api = FakeApi(index={"phev": {"name": "传祺E8 PHEV", "price_range": "23.28-23.88万"},
                         "noprice": {"name": "无价带车"}})
    pool = [_entry("传祺E8 PHEV", msrp_p50=232800.0), _entry("无价带车", msrp_p50=999.0)]
    stats = asyncio.run(g.bind_pool(pool, {}, api, delay=0))
    assert stats["exact"] == 2 and stats["manual_review"] == 0
    assert pool[0]["series_id"] == "phev" and pool[1]["series_id"] == "noprice"


def test_price_guard_invalidates_stale_cache():
    # 缓存里的错绑（价带失检）→ 弃缓存，重走绑定后落 manual_review
    api = FakeApi(index={"fuel": {"name": "传祺E8", "price_range": "17.98-17.98万"}})
    cache = {g.norm_name("传祺E8"): {"series_id": "fuel", "binding": "exact"}}
    pool = [_entry("传祺E8", msrp_p50=232800.0)]
    stats = asyncio.run(g.bind_pool(pool, cache, api, delay=0))
    assert stats["reused"] == 0
    assert pool[0]["binding"] == "manual_review" and pool[0]["_review_reason"] == "price_mismatch"


def test_binding_cache_only_trusts_exact_search():
    api = FakeApi(index={"1": {"name": "甲A 纯电", "brand_name": "甲牌"}})
    cache = {g.norm_name("甲A 纯电"): {"series_id": "stale", "binding": "manual_review"}}
    pool = [_entry("甲A 纯电")]
    asyncio.run(g.bind_pool(pool, cache, api, delay=0))
    assert pool[0]["binding"] == "exact" and pool[0]["series_id"] == "1"  # 缓存里 manual_review 不复用


# ---------- 共壳 ----------

def test_shared_shell_demotes_all_peers():
    pool = [
        _entry("共壳甲 DM-i", binding="exact", series_id="5"),
        _entry("共壳甲 EV", binding="search", series_id="5"),
        _entry("无壳", binding="exact", series_id="6"),
    ]
    shells = g.detect_shared_shells(pool)
    assert shells == [{"series_id": "5", "sales_names": ["共壳甲 DM-i", "共壳甲 EV"]}]
    assert all(e["binding"] == "manual_review" for e in pool[:2])
    assert pool[0]["_review_reason"] == "shared_shell"
    assert pool[0]["_peers"] == ["共壳甲 DM-i", "共壳甲 EV"]
    assert pool[2]["binding"] == "exact"  # 无关项不动


# ---------- 汇总/输出 ----------

def test_attach_counts_and_totals(conn):
    rows = g.load_window_rows(conn, g.latest_retail_window(conn))
    pool, _ = g.build_pool(rows)
    by_name = {e["sales_name"]: e for e in pool}
    by_name["丙C 增程"]["binding"] = "exact"
    by_name["丙C 增程"]["series_id"] = "bing-sid"
    by_name["甲A 纯电"]["binding"] = "search"
    by_name["甲A 纯电"]["series_id"] = "jia-sid"
    g.attach_local_counts(conn, pool)
    g.attach_source_counts(conn, pool)
    g.assign_tiers(pool)
    assert by_name["丙C 增程"]["local_review_count"] == 150
    assert by_name["丙C 增程"]["source_review_count"] == 10020
    assert by_name["丙C 增程"]["tier"] == "existing"
    assert by_name["甲A 纯电"]["local_review_count"] == 0   # 无本地口碑 → 0
    assert by_name["甲A 纯电"]["source_review_count"] is None
    assert by_name["甲A 纯电"]["tier"] == "deep"            # 零售 4000 > 3000
    totals = g.compute_totals(pool)
    assert totals == {"universe": 4, "deep": 1, "longtail": 0, "existing": 1,
                      "manual_review": 0, "unbound": 2}


def test_manual_review_list_shape():
    pool = [_entry("查无车", retail=9000, binding="manual_review",
                   _review_reason="not_found", _candidates=[])]
    mr = g.manual_review_list(pool)
    assert mr == [{"sales_name": "查无车", "reason": "not_found", "retail_3m": 9000,
                   "tier_by_retail": "deep", "series_id": None,
                   "candidates": [], "peers": [], "shell_hints": []}]


def test_not_found_gets_shell_hint_not_binding():
    # §3.3 合并壳形态在 T1b 后走规则绑定：价带过检 → rule_merged_shell 绑定；
    # 价带不过 → manual(price_mismatch) 并列候选；无后缀可剥 → not_found 无线索
    api = FakeApi(index={"9": {"name": "测试壳", "brand_name": "X牌", "price_range": "20-25万"}})
    pool = [_entry("测试壳 DM-i"), _entry("无提示车")]
    stats = asyncio.run(g.bind_pool(pool, {}, api, delay=0))
    e1, e2 = pool
    assert e1["binding"] == "manual_review" and e1["series_id"] is None  # 价带不符拦下
    assert e1["_review_reason"] == "price_mismatch"
    assert e1["_candidates"][0]["series_id"] == "9"  # 人审候选在案
    assert e2["binding"] == "manual_review" and e2["_review_reason"] == "not_found"
    assert e2.get("_shell_hints") is None  # 无后缀可剥 → 无线索


# ---------- 规则1 rule_merged_shell（T1b） ----------

def test_strip_powertrain_attached():
    # 粘着形动力后缀（长词优先，剥完须仍含字母数字/汉字）
    assert g.strip_powertrain_all("比亚迪 唐DM-i") == "比亚迪 唐"
    assert g.strip_powertrain_all("比亚迪 汉EV") == "比亚迪 汉"
    assert g.strip_powertrain_all("帕萨特ePro") == "帕萨特"
    assert g.strip_powertrain_all("启辰大V DD-i超混动") == "启辰大V DD-i"
    assert g.strip_powertrain_all("皓影 e:PHEV") == "皓影"   # e:PHEV 整 token 剥离
    assert g.strip_powertrain_all("比亚迪 秦PLUS DM-i") == "比亚迪 秦PLUS"
    assert g.strip_powertrain_all("悦意03") == "悦意03"       # 无后缀不动
    # 剥完剩纯符号 → 视为失败回退（'e:' 无字母数字）


def test_rule_merged_shell_binds_shared_shell_and_tier():
    # 秦PLUS DM-i / 秦PLUS EV 同绑之家合并壳 5964：shared_shell 互列兄弟，共壳检测不降级
    api = FakeApi(index={"5964": {"name": "秦PLUS", "brand_name": "比亚迪",
                                  "price_range": "7.98-17.98万"}})
    pool = [_entry("比亚迪 秦PLUS DM-i", retail=24967, msrp_p50=100000.0),
            _entry("比亚迪 秦PLUS EV", retail=9223, msrp_p50=110000.0)]
    stats = asyncio.run(g.bind_pool(pool, {}, api, delay=0))
    assert stats["manual_review"] == 0
    assert all(e["binding"] == "rule_merged_shell" and e["series_id"] == "5964"
               for e in pool)
    g.attach_shared_shells(pool)
    assert pool[0]["shared_shell"] == ["比亚迪 秦PLUS EV"]
    assert pool[1]["shared_shell"] == ["比亚迪 秦PLUS DM-i"]
    assert g.detect_shared_shells(pool) == []  # 规则绑定共壳=刻意语义，不降级
    assert all(e["binding"] == "rule_merged_shell" for e in pool)
    ev = pool[0]["_binding_evidence"]
    assert ev["rule"] == "rule_merged_shell"
    assert ev["matched_name"] == "秦PLUS"
    assert ev["matched_price_range"] == "7.98-17.98万"
    assert ev["cam_msrp_p50"] == 100000.0
    # 规则绑定同权参与 tier：口碑 0 + 零售 >3000 → deep
    g.assign_tiers(pool)
    assert pool[0]["tier"] == "deep"


def test_rule_merged_shell_multi_hit_or_twin_goes_manual():
    # 去后缀命中多条（含动力分壳兄弟壳 坦克300新能源）→ 歧义 → 宁留人审
    api = FakeApi(index={"5810": {"name": "坦克300", "brand_name": "坦克",
                                  "price_range": "19.98-23.48万"},
                        "7210": {"name": "坦克300新能源", "brand_name": "坦克",
                                 "price_range": "24.98-24.98万"}})
    pool = [_entry("坦克300 Hi4-T", msrp_p50=279800.0)]
    stats = asyncio.run(g.bind_pool(pool, {}, api, delay=0))
    assert stats["manual_review"] == 1
    e = pool[0]
    assert e["binding"] == "manual_review" and e["series_id"] is None
    assert e["_review_reason"] == "ambiguous_rule"
    assert {c["series_id"] for c in e["_candidates"]} == {"5810", "7210"}


def test_rule_merged_shell_price_mismatch_keeps_manual():
    # 基名唯一命中但 CAM 中位价 ∉ 之家价带 → price_mismatch 人审（不放宽）
    api = FakeApi(index={"5499": {"name": "汉", "brand_name": "比亚迪",
                                  "price_range": "16.88-22.58万"}})
    pool = [_entry("比亚迪 汉EV", msrp_p50=300000.0)]
    stats = asyncio.run(g.bind_pool(pool, {}, api, delay=0))
    assert stats["manual_review"] == 1
    assert pool[0]["_review_reason"] == "price_mismatch" and pool[0]["series_id"] is None


# ---------- 规则2 rule_alias（T1b） ----------

def test_rule_alias_pair_binds_and_unpaired_stays_manual():
    api = FakeApi(index={"7743": {"name": "领裕新能源", "brand_name": "福特",
                                  "price_range": "20.68-23.88万"},
                        "5910": {"name": "领裕", "brand_name": "福特",
                                 "price_range": "17.38-22.18万"}})
    pool = [_entry("领裕 PHEV", msrp_p50=215000.0), _entry("领睿 PHEV", msrp_p50=180000.0)]
    stats = asyncio.run(g.bind_pool(pool, {}, api, delay=0))
    # 显式对 → 领裕新能源（燃油壳 领裕 同名并存，靠转写表消歧）
    assert pool[0]["binding"] == "rule_alias" and pool[0]["series_id"] == "7743"
    assert pool[0]["_binding_evidence"]["rule"] == "rule_alias"
    assert pool[0]["_binding_evidence"]["matched_name"] == "领裕新能源"
    # 转写表没有的目标 → 不预猜，走 search 兜底 → not_found 人审
    assert pool[1]["binding"] == "manual_review"
    assert pool[1]["_review_reason"] == "not_found"


def test_rule_alias_pair_price_guard_blocks():
    # 显式对也必须过价带守卫：星光560新能源 9.18-9.88万 vs CAM p50 8.5万 → 拦下人审
    api = FakeApi(index={"8216": {"name": "星光560新能源", "brand_name": "五菱汽车",
                                  "price_range": "9.18-9.88万"}})
    pool = [_entry("五菱星光560 PHEV", msrp_p50=85000.0)]
    stats = asyncio.run(g.bind_pool(pool, {}, api, delay=0))
    assert stats["manual_review"] == 1 and pool[0]["series_id"] is None
    assert pool[0]["binding"] == "manual_review"
    assert pool[0]["_review_reason"] in ("price_mismatch", "ambiguous_rule")


def test_rule_alias_brand_and_greek_translit():
    # ARCFOX αS5 → 极狐 阿尔法S5；ARCFOX βS3 → 极狐贝塔S3（α/β 希腊字母映射）
    api = FakeApi(index={"7327": {"name": "极狐 阿尔法S5", "brand_name": "ARCFOX极狐",
                                  "price_range": "13.98-19.98万"},
                        "8190": {"name": "极狐贝塔S3", "brand_name": "ARCFOX极狐",
                                 "price_range": "8.48-16.28万"}})
    pool = [_entry("ARCFOX αS5", msrp_p50=160000.0),
            _entry("ARCFOX βS3", msrp_p50=100000.0)]
    stats = asyncio.run(g.bind_pool(pool, {}, api, delay=0))
    assert pool[0]["binding"] == "rule_alias" and pool[0]["series_id"] == "7327"
    assert pool[0]["_binding_evidence"]["base_or_variant"] == "极狐 阿尔法S5"
    assert pool[1]["binding"] == "rule_alias" and pool[1]["series_id"] == "8190"


def test_rule_alias_index_prefix_strip():
    # 之家壳名带品牌前缀：极狐 考拉S←考拉S(7797)、东风风神L7←风神L7(7323)
    api = FakeApi(index={"7797": {"name": "极狐 考拉S", "brand_name": "ARCFOX极狐",
                                  "price_range": "9.98-10.98万"},
                        "7323": {"name": "东风风神L7", "brand_name": "东风风神",
                                 "price_range": "9.49-22.45万"}})
    pool = [_entry("考拉S", msrp_p50=101800.0),
            _entry("风神L7 纯电", msrp_p50=130000.0)]
    stats = asyncio.run(g.bind_pool(pool, {}, api, delay=0))
    assert pool[0]["binding"] == "rule_alias" and pool[0]["series_id"] == "7797"
    assert pool[1]["binding"] == "rule_alias" and pool[1]["series_id"] == "7323"


def test_rule_alias_id_dot_prefix_and_rule1_boundary():
    # ID.与众06 → 与众06（大众 ID. 系列之家立壳不带前缀）；
    # 纯基名命中走规则1 而非规则2（规则归属不串）
    api = FakeApi(index={"7628": {"name": "与众06", "brand_name": "大众",
                                  "price_range": "14.99-15.99万"},
                        "5964": {"name": "秦PLUS", "brand_name": "比亚迪",
                                 "price_range": "7.98-17.98万"}})
    pool = [_entry("ID.与众06", msrp_p50=153000.0),
            _entry("比亚迪 秦PLUS EV", msrp_p50=110000.0)]
    asyncio.run(g.bind_pool(pool, {}, api, delay=0))
    assert pool[0]["binding"] == "rule_alias" and pool[0]["series_id"] == "7628"
    assert pool[1]["binding"] == "rule_merged_shell" and pool[1]["series_id"] == "5964"


def test_shared_shell_discloses_cross_kind_peers():
    # 规则绑定与 exact 绑定同壳（小鹏G6 exact + 小鹏G6 增程 rule_merged_shell → 7162）：
    # 双方 shared_shell 互列（一 id 多 sales 名全类别披露）
    api = FakeApi(index={"7162": {"name": "小鹏G6", "brand_name": "小鹏",
                                  "price_range": "17.68-18.68万"}})
    pool = [_entry("小鹏G6", msrp_p50=180000.0),
            _entry("小鹏G6 增程", msrp_p50=180000.0)]
    asyncio.run(g.bind_pool(pool, {}, api, delay=0))
    g.attach_shared_shells(pool)
    assert pool[0]["binding"] == "exact" and pool[1]["binding"] == "rule_merged_shell"
    assert pool[0]["series_id"] == pool[1]["series_id"] == "7162"
    assert pool[0]["shared_shell"] == ["小鹏G6 增程"]
    assert pool[1]["shared_shell"] == ["小鹏G6"]
    assert g.detect_shared_shells(pool) == []  # 含 rule 成员的同壳不降级


def test_strip_powertrain_tokens():
    assert g.strip_powertrain_tokens("秦PLUS DM-i") == "秦PLUS"
    assert g.strip_powertrain_tokens("海豹06 EV") == "海豹06"
    assert g.strip_powertrain_tokens("ARCFOX αS5 增程") == "ARCFOX αS5"
    assert g.strip_powertrain_tokens("锐胜M8 纯电") == "锐胜M8"
    assert g.strip_powertrain_tokens("深蓝S05 纯电") == "深蓝S05"
    assert g.strip_powertrain_tokens("悦意03") == "悦意03"  # 无动力后缀不动
    assert g.strip_powertrain_tokens("") == ""


def test_write_pool_rotates_prev(tmp_path):
    out = tmp_path / "nev_pool.json"
    out.write_text('{"old": true}', encoding="utf-8")
    g.write_pool(out, {"new": 1})
    assert json_load(out) == {"new": 1}
    assert json_load(tmp_path / "nev_pool.json.prev") == {"old": True}


def json_load(p):
    import json
    return json.loads(p.read_text(encoding="utf-8"))


# ---------- 端到端（离线形态，不出网） ----------

def test_offline_pipeline_window_to_totals(conn):
    w = g.latest_retail_window(conn)
    pool, _ = g.build_pool(g.load_window_rows(conn, w))
    ea = g.assert_energy_composition(pool)
    pa = g.assert_prev_delta(len(pool), None, prev_status="no_prev")
    totals = g.compute_totals(pool)  # 未绑定 → tier 全空
    assert ea["passed"] and pa["passed"] and pa["skipped"] == "no_prev"
    assert totals == {"universe": 4, "deep": 0, "longtail": 0, "existing": 0,
                      "manual_review": 0, "unbound": 4}
