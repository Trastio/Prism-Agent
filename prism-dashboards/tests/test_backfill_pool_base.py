"""T2 单测：底座批 backfill_pool_base。

覆盖：缺口计算（bound 过滤/唯一去重/只补缺）/ metadata 映射（键名对齐 ORM、
energy 归一、共壳冲突披露）/ API→SeriesSummary 列映射（缺列 NULL、0 价→NULL、
error→None）/ upsert 幂等 / locked 重试。

全部不出网：库用内存 sqlite/sqlalchemy，无真实 API 调用。
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

import backfill_pool_base as b  # noqa: E402


def _entry(name, sid, binding="exact", **kw):
    e = {"sales_name": name, "body_cat": "SUV", "retail_3m": 5000,
         "msrp_p50": 100000.0, "energy_type": "纯电动", "tier": "deep",
         "series_id": sid, "binding": binding, "manufacturer": "甲厂",
         "level": "A", "local_review_count": 0, "source_review_count": None}
    e.update(kw)
    return e


# ---------- 名单过滤 ----------

def test_load_bound_items_filters_manual_review_and_empty_sid(tmp_path):
    pool = {"series": [
        _entry("已绑", "1"),
        _entry("人审", None, binding="manual_review"),
        _entry("人审带id", "2", binding="manual_review"),
        _entry("规则绑", "3", binding="rule_merged_shell"),
    ]}
    p = tmp_path / "pool.json"
    p.write_text(__import__("json").dumps(pool, ensure_ascii=False), encoding="utf-8")
    items = b.load_bound_items(p)
    assert [it["series_id"] for it in items] == ["1", "3"]


# ---------- 缺口计算 ----------

def test_compute_gaps_missing_and_dedup():
    items = [
        _entry("甲A", "1"),
        _entry("乙B", "2"),
        _entry("共壳甲 DM-i", "1"),   # 共壳：同 sid 第二个 sales 名
    ]
    gaps = b.compute_gaps(items, shell_ids={"2"}, cfg_ids=set())
    assert gaps["bound_items"] == 3
    assert gaps["unique_ids"] == 2                     # 1 / 2
    assert gaps["order"] == ["1", "2"]
    assert gaps["names"]["1"] == ["甲A", "共壳甲 DM-i"]
    assert gaps["missing_shell"] == ["1"]              # 2 已有壳 → 只补缺
    assert gaps["missing_config"] == ["1", "2"]


def test_compute_gaps_no_missing():
    items = [_entry("甲A", "1")]
    gaps = b.compute_gaps(items, shell_ids={"1"}, cfg_ids={"1"})
    assert gaps["missing_shell"] == [] and gaps["missing_config"] == []


# ---------- metadata 映射 ----------

def test_build_metadata_map_keys_and_energy_norm():
    items = [
        _entry("甲A 纯电", "1", energy_type="纯电动", manufacturer="零跑汽车", level="A"),
        _entry("乙B 插混", "2", energy_type="插电式混合", manufacturer="比亚迪汽车", level="B"),
        _entry("丙C 增程", "3", energy_type="增程式混合", manufacturer="赛力斯汽车", level="C"),
    ]
    meta, conflicts = b.build_metadata_map(items)
    assert conflicts == []
    # 键名对齐 upsert_config_snapshot 实际列：maker/energy/level
    assert meta["1"] == {"maker": "零跑汽车", "energy": "纯电", "level": "A"}
    assert meta["2"] == {"maker": "比亚迪汽车", "energy": "插混", "level": "B"}
    assert meta["3"] == {"maker": "赛力斯汽车", "energy": "增程", "level": "C"}


def test_build_metadata_map_unknown_energy_kept_verbatim():
    meta, conflicts = b.build_metadata_map(
        [_entry("怪车", "9", energy_type="燃料电池")])
    assert meta["9"]["energy"] == "燃料电池"  # 不编造、不改写未知值
    assert conflicts == []


def test_build_metadata_map_shared_shell_conflict_disclosed_first_wins():
    # 共壳 DM-i/EV 同 sid，energy 冲突 → 首见项落库，冲突如实披露
    items = [
        _entry("秦X DM-i", "5", energy_type="插电式混合"),
        _entry("秦X EV", "5", energy_type="纯电动"),
    ]
    meta, conflicts = b.build_metadata_map(items)
    assert meta["5"]["energy"] == "插混"
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["series_id"] == "5" and c["sales_name"] == "秦X EV"
    assert c["diff"]["energy"] == {"kept": "插混", "dropped": "纯电"}


def test_build_metadata_map_same_metadata_shared_shell_no_conflict():
    items = [_entry("共壳甲 DM-i", "5"), _entry("共壳甲 EV", "5")]
    _, conflicts = b.build_metadata_map(items)
    assert conflicts == []


# ---------- 壳列映射 ----------

def _full_summary(sid="1"):
    return {
        "series_id": sid, "series_name": "甲A", "brand_name": "甲牌",
        "brand_id": "11", "level_name": "紧凑型SUV", "level_id": "15",
        "level_rank": 3, "level_series_count": 120,
        "price_range": "10-15万", "min_price": 10.0, "max_price": 15.98,
        "average_score": 4.5,
        "dimension_scores": [{"name": "空间", "score": 4.6, "rank": 2}],
        "review_count": 1000, "onsell_review_count": 800, "pph": 250,
        "powertype": 4, "cmp_scores": [], "cmp_pph": [],
        "consumption": "5.5", "consumption_battery": "13.8",
        "spec_groups": [{"name": "2026款", "count": 3}],
        "data_source": "汽车之家口碑API",
    }


def test_map_summary_full_roundtrip():
    cols = b.map_summary_to_columns(_full_summary("42"))
    assert cols["series_id"] == "42"
    assert cols["series_name"] == "甲A" and cols["brand_name"] == "甲牌"
    assert cols["min_price"] == 10.0 and cols["max_price"] == 15.98
    assert cols["average_score"] == 4.5 and cols["review_count"] == 1000
    assert cols["spec_groups"] == [{"name": "2026款", "count": 3}]


def test_map_summary_error_returns_none():
    assert b.map_summary_to_columns({"error": "无法获取车系汇总", "series_id": "1"}) is None
    assert b.map_summary_to_columns(None) is None
    assert b.map_summary_to_columns("junk") is None


def test_map_summary_missing_fields_null_never_fabricates():
    # API 半空形态：没给的列 → None；0 价/空串 → None（0 元不是真实价）
    cols = b.map_summary_to_columns({
        "series_id": "7", "series_name": "", "min_price": 0, "max_price": None,
        "average_score": None, "consumption": "", "brand_id": "",
    })
    assert cols["series_name"] is None
    assert cols["brand_name"] is None and cols["brand_id"] is None
    assert cols["min_price"] is None and cols["max_price"] is None
    assert cols["average_score"] is None and cols["consumption"] is None
    assert cols["level_rank"] is None and cols["spec_groups"] is None


# ---------- upsert（内存 sqlalchemy，不碰生产库） ----------

@pytest.fixture()
def sa_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.models.orm import Base
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    yield s
    s.close()
    eng.dispose()


def test_upsert_series_summary_insert_then_update(sa_session):
    from src.models.orm import SeriesSummary
    cols = b.map_summary_to_columns(_full_summary("42"))
    assert b.upsert_series_summary(sa_session, cols) == "inserted"
    sa_session.commit()
    row = sa_session.get(SeriesSummary, "42")
    assert row.series_name == "甲A" and row.review_count == 1000
    # 二次：只改非 None 字段，None 不擦旧值
    cols2 = b.map_summary_to_columns({"series_id": "42", "review_count": 1200})
    assert b.upsert_series_summary(sa_session, cols2) == "updated"
    sa_session.commit()
    row = sa_session.get(SeriesSummary, "42")
    assert row.review_count == 1200
    assert row.series_name == "甲A"  # 未被 None 擦掉
    assert row.brand_name == "甲牌"  # 原有字段保留


# ---------- locked 重试 ----------

def test_is_locked_error():
    assert b.is_locked_error(RuntimeError("database is locked"))
    assert b.is_locked_error(RuntimeError("database table is locked"))
    assert b.is_locked_error(RuntimeError("database is busy"))
    assert not b.is_locked_error(RuntimeError("no categories"))


def test_with_locked_retry_retries_then_succeeds():
    calls = {"n": 0}
    sleeps: list[float] = []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("sqlite3.OperationalError: database is locked")
        return "ok"

    r = b.with_locked_retry(flaky, wait_s=0.0, max_retry=10, sleep=sleeps.append)
    assert r == "ok" and calls["n"] == 3 and len(sleeps) == 2


def test_with_locked_retry_non_locked_raises_immediately():
    calls = {"n": 0}

    def broken():
        calls["n"] += 1
        raise ValueError("no categories")

    with pytest.raises(ValueError):
        b.with_locked_retry(broken, wait_s=0.0, max_retry=10, sleep=lambda s: None)
    assert calls["n"] == 1  # 非 locked 不重试


def test_with_locked_retry_gives_up_after_max():
    calls = {"n": 0}

    def always_locked():
        calls["n"] += 1
        raise RuntimeError("database is locked")

    with pytest.raises(RuntimeError):
        b.with_locked_retry(always_locked, wait_s=0.0, max_retry=3,
                            sleep=lambda s: None)
    assert calls["n"] == 3


# ---------- load_db_ids 只读 ----------

def test_load_db_ids_readonly(tmp_path):
    db = tmp_path / "x.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE series_summaries (series_id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE config_snapshots (series_id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO series_summaries VALUES ('1')")
    conn.commit()
    conn.close()
    shell, cfg = b.load_db_ids(db)
    assert shell == {"1"} and cfg == set()
