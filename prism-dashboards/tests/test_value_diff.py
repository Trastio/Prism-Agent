"""value_diff 单测（配置赋值口径改造 T1.3 parity + T1.4 新规则）。

parity 层：legacy_mode 逐字复刻 dash_config.html 原 `_computeDiffCells` JS 公式，
期望值全部由公式手工推导（JS 公式见 value_diff.py 模块 docstring 与本文件注释），
不引用前端代码运行结果（前端已删该 JS）。

新规则层：直接加载真实 diff_pricing.json（顺带校验 schema 与 61 项覆盖）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.insights.value_diff import (compute_value_diff, load_pricing_table,
                                     _cell_state, _extract_num)


def row(id_, cells, present=None, param=None, price=None):
    return {"id": id_, "name": id_, "param": param or id_, "cells": cells,
            "present": present if present is not None else
            [0 if c in ("-", "缺采", None) else 1 for c in cells],
            "price": price, "is_concept": True}


# ---------------- T1.3 parity（legacy_mode，锁 JS 公式） ----------------

def test_parity_presence_diff_plus():
    # Δ = pk−p0 = 0−1 = −1 ×2000 → −2000；列2 比 col1 少
    rows = [row("A4", ["●", "-"], present=[1, 0], price=2000)]
    out = compute_value_diff(rows, {}, legacy_mode=True)
    c = out["columns"][1]
    assert (c["comparable"], c["total_n"], c["priced_n"]) == (1, 1, 1)
    assert c["amount"] == -2000
    assert c["text"] == "列2 比列1 -¥2,000（已定价 1 / 共 1 项）"


def test_parity_presence_diff_reverse():
    rows = [row("L3", ["-", "●"], present=[0, 1], price=500)]
    c = compute_value_diff(rows, {}, legacy_mode=True)["columns"][1]
    assert c["amount"] == 500


def test_parity_numeric_diff():
    # Δ = 420−605 = −185 ×100 → −18500
    rows = [row("A1", ["605", "420"], present=[1, 1], price=100)]
    c = compute_value_diff(rows, {}, legacy_mode=True)["columns"][1]
    assert c["amount"] == -18500
    assert c["text"] == "列2 比列1 -¥18,500（已定价 1 / 共 1 项）"


def test_parity_text_diff_skipped():
    # 双方具备文本差异 → 不计价（不计 total_n）
    rows = [row("F1", ["●", "仿皮"], present=[1, 1], price=300)]
    c = compute_value_diff(rows, {}, legacy_mode=True)["columns"][1]
    assert (c["comparable"], c["total_n"], c["priced_n"], c["amount"]) == (1, 0, 0, 0)
    assert c["text"] == "无差价项"


def test_parity_equal_numeric_skipped():
    rows = [row("A1", ["605", "605"], present=[1, 1], price=100)]
    c = compute_value_diff(rows, {}, legacy_mode=True)["columns"][1]
    assert c["total_n"] == 0


def test_parity_both_absent_skipped():
    rows = [row("E8", ["-", "-"], present=[0, 0], price=300)]
    c = compute_value_diff(rows, {}, legacy_mode=True)["columns"][1]
    assert (c["comparable"], c["total_n"]) == (1, 0)


def test_parity_missing_skips_row_entirely():
    # 缺采整行跳过：不计 comparable → 差价值不可用
    rows = [row("A1", ["605", "缺采"], present=[1, None], price=100)]
    out = compute_value_diff(rows, {}, legacy_mode=True)
    c = out["columns"][1]
    assert c["comparable"] == 0
    assert c["available"] is False
    assert c["text"] == "差价值不可用（该列概念配置无可比数据）"


def test_parity_unpriced_counts_only():
    rows = [row("A4", ["●", "-"], present=[1, 0], price=None)]
    c = compute_value_diff(rows, {}, legacy_mode=True)["columns"][1]
    assert (c["total_n"], c["priced_n"], c["amount"]) == (1, 0, 0)
    assert c["text"] == "未定价（共 1 项）"


def test_parity_manual_price_overrides():
    rows = [row("A4", ["●", "-"], present=[1, 0], price=2000, param="高压平台")]
    c = compute_value_diff(rows, {}, manual_prices={"高压平台": 999},
                           legacy_mode=True)["columns"][1]
    assert c["amount"] == -999  # Δ = p(k)−p(0) = −1 × 999


def test_parity_multi_col_and_baseline():
    # 3 列：k=1（列2）与 k=2（列3）各自相对列1
    rows = [row("A4", ["●", "-", "●"], present=[1, 0, 1], price=2000),
            row("L3", ["●", "●", "-"], present=[1, 1, 0], price=500)]
    out = compute_value_diff(rows, {}, legacy_mode=True)
    assert out["columns"][0]["text"] == "基准"
    c1, c2 = out["columns"][1], out["columns"][2]
    # 列2：A4 Δ=−1×2000 + L3 Δ=0 → −2000；列3：A4 Δ=0 + L3 Δ=−1×500 → −500
    assert c1["amount"] == -2000
    assert c2["amount"] == -500
    assert c1["text"].startswith("列2 比列1 ")
    assert c2["text"].startswith("列3 比列1 ")


def test_parity_non_concept_rows_ignored():
    rows = [{"id": "x", "is_concept": False, "cells": ["a", "b"],
             "present": [1, 1], "price": 100}]
    out = compute_value_diff(rows, {}, legacy_mode=True)
    assert out["columns"][1]["comparable"] == 0


# ---------------- T1.4 新规则（生产模式，真实 diff_pricing.json） ----------------

@pytest.fixture(scope="module")
def table():
    return load_pricing_table()


def _one(table, id_, cells, manual=None):
    rows = [{"id": id_, "name": id_, "param": f"p_{id_}", "cells": cells,
             "present": [1 if _cell_state(c) == "present" else 0 for c in cells],
             "price": None, "is_concept": True}]
    out = compute_value_diff(rows, table, manual_prices=manual)
    return out, (out["items"].get(id_) or {})


def test_band_text_seat_material(table):
    # 口径：amount = 值(列k) − 值(列1)。真皮(2500) − 仿皮(1500) = +1000，列2 多
    out, it = _one(table, "F1", ["仿皮", "真皮"])
    assert it["verdict"] == "多" and it["amount"] == 1000


def test_band_absent_side_zero(table):
    # 列2 无天窗 → 0 − 2500 = −2500，列2 少
    out, it = _one(table, "E1", ["可开启全景天窗", "-"])
    assert it["verdict"] == "少" and it["amount"] == -2500


def test_band_substring_order_fixed(table):
    # "不可开启全景" 含 "可开启全景" 子串 → 匹配序必须不可开启优先
    out, it = _one(table, "E1", ["不可开启全景天幕", "-"])
    assert it["amount"] == -2000


def test_band_numeric_wheel(table):
    # R16(0) − R18(1400) = −1400
    out, it = _one(table, "B1", ["225/55 R18", "205/60 R16"])
    assert it["amount"] == -1400  # 列2 相对列1 少 1400


def test_band_unmatched_missing_blocks_totals(table):
    # R23 落不了档且 fallback=null → missing_rules + 汇总拒绝（不脑补）
    out, it = _one(table, "B1", ["R23", "R18"])
    assert "B1" in out["missing_rules"] and out["blocked"] is True
    assert out["columns"][1]["amount"] is None
    assert "缺规则" in out["columns"][1]["text"]


def test_band_combo_suspension(table):
    # 软硬(1000) − 软硬+高低(9000) = −8000
    out, it = _one(table, "M2", ["软硬+高低调节", "软硬调节"])
    assert it["amount"] == -8000


def test_band_fallback_zero_streaming(table):
    # carkit 豁免语义：常规防眩目=0，流媒体=1000
    out, it = _one(table, "H6", ["自动防眩目", "流媒体内后视镜"])
    assert it["amount"] == 1000


def test_band_motor_count(table):
    out, it = _one(table, "A3", ["双电机", "三电机"])
    assert it["amount"] == 8000  # 16000 → 24000


def test_band_800v_fallback_zero(table):
    # 400V 落不进 "800" 档 → fallback 0：0 − 2000 = −2000，不误计
    out, it = _one(table, "A4", ["800V", "400V"])
    assert it["amount"] == -2000


def test_per_unit_speaker_count(table):
    out, it = _one(table, "G5", ["12", "8"])
    assert it["amount"] == -400  # (8−12)×100


def test_per_unit_range(table):
    out, it = _one(table, "A1", ["605", "500"])
    assert it["amount"] == -10500


def test_threshold_below_no_charge(table):
    out, it = _one(table, "G1", ["15.6", "14.6"])
    assert it["verdict"] == "不计"  # |1.0| < 3寸


def test_threshold_hit_both_directions(table):
    _, it1 = _one(table, "G1", ["15.6", "12.3"])
    assert it1["amount"] == -500  # 列2 更小
    _, it2 = _one(table, "G1", ["12.3", "15.6"])
    assert it2["amount"] == 500


def test_optional_marked_absent(table):
    # 拍板：○ 选装=无 → 列1 "○800V可选装" 按无计(0)，列2 "800V"=2000 → +2000 多
    out, it = _one(table, "A4", ["○800V可选装", "800V"])
    assert it["verdict"] == "多" and it["amount"] == 2000


def test_missing_cell_row_skipped(table):
    out, it = _one(table, "L3", ["缺采", "●"])
    assert it["verdict"] == "不计"
    assert out["columns"][1]["comparable"] == 0


def test_flat_text_diff_not_priced(table):
    out, it = _one(table, "A5", ["3.3kW", "6kW"])
    assert it["verdict"] == "不计"  # flat 无档位，文本差异不计


def test_item_without_rule_missing(table):
    rows = [{"id": "ZZ", "name": "不存在的项", "param": "p_zz",
             "cells": ["●", "-"], "present": [1, 0], "price": None,
             "is_concept": True}]
    out = compute_value_diff(rows, table)
    assert "ZZ" in out["missing_rules"] and out["blocked"] is True


def test_manual_price_overrides_production(table):
    out, it = _one(table, "F2", ["●", "-"], manual={"p_F2": 100})
    assert it["amount"] == -100 and it["price_source"] == "manual"  # Δ=−1×100


def test_same_cells_verdict_tong(table):
    out, it = _one(table, "L3", ["●", "●"])
    assert it["verdict"] == "同"


# ---------------- 真值表 schema 与 61 项覆盖 ----------------

def test_table_covers_all_61_concepts():
    cfg = json.load(open(Path(__file__).parent.parent / "data" / "concept_configs.json",
                         encoding="utf-8"))
    ids = {c["id"] for c in cfg}
    tbl = load_pricing_table()
    assert tbl["version"] == "v1.1-20261014"
    # 补项后 72 项：items 必须覆盖全部非 excluded 概念，excluded 项只登记不定价
    non_excluded = ids - set(tbl["excluded"]["ids"])
    assert set(tbl["items"].keys()) == non_excluded
    assert isinstance(tbl["excluded"]["ids"], list)
    for cid, it in tbl["items"].items():
        assert it["pricing"] in ("flat", "per_unit", "band", "threshold"), cid
        assert it.get("basis"), cid


# ---------------- 补项 change（2026-10-14）：清单外豁免 + 求和语义 ----------------

def test_excluded_item_visible_not_priced(table):
    """excluded.ids 项：有差异也只标"不计"，不进 missing 不阻断汇总。"""
    t2 = json.loads(json.dumps(table))
    t2.setdefault("excluded", {})["ids"] = ["ZZ9"]
    rows = [row("ZZ9", ["●", "-"])]
    out = compute_value_diff(rows, t2, legacy_mode=False)
    assert out["items"]["ZZ9"]["verdict"] == "不计"
    assert "ZZ9" not in out["missing_rules"]
    assert out["blocked"] is False


def test_usb_sum_numbers(table):
    """G7 求和语义：'前排3个/后排2个'→5；基准在前、具备方在后 → +100。"""
    rows = [row("G7", ["前排2个/后排1个", "前排3个/后排2个"])]
    out = compute_value_diff(rows, table, legacy_mode=False)
    assert out["items"]["G7"]["amount"] == 100.0


# ---------------- Step8 审查修复回归（2026-10-13 隔离审查 P0-1/P1-1/P1-2/P2-1） ----------------

def test_unavailable_column_config_adv_none(table):
    """P1-1：全部行缺采 → 列不可用，config_adv 必须 None（不能被当 0）。"""
    rows = [row("A5", ["缺采", "缺采"]), row("L3", [None, None])]
    out = compute_value_diff(rows, table, legacy_mode=False)
    assert out["config_adv"] is None
    assert out["columns"][1]["available"] is False
    # 端点侧契约：blocked=False 但 config_adv=None，消费方不得 or 0
    assert out["blocked"] is False


def test_absent_spelling_diff_no_false_missing(table):
    """P1-2：item=None 行 cells=["○","—"] 语义同为无 → 不进 missing_rules。"""
    rows = [row("ZZZ", ["○", "—"])]
    out = compute_value_diff(rows, table, legacy_mode=False)
    assert "ZZZ" not in out["missing_rules"]
    assert out["blocked"] is False
    assert out["items"]["ZZZ"]["verdict"] == "同"


def test_absent_trailing_space_no_false_diff(table):
    """P1-2 伴生：present 值仅尾随空格差不算差异（item=None 不触发 missing）。"""
    rows = [row("ZZZ", ["仿皮", "仿皮 "])]
    out = compute_value_diff(rows, table, legacy_mode=False)
    assert "ZZZ" not in out["missing_rules"]


def test_fmt_amount_half_up():
    """P2-1：.5 对齐 JS Math.round（half-up），非 banker's。"""
    from src.insights.value_diff import _fmt_amount
    assert _fmt_amount(10000.5) == "10,001"
    assert _fmt_amount(10000.4) == "10,000"


def test_pricing_table_missing_field_fail_closed(table):
    """P2-4：规则缺 val 字段 → missing fail-closed，不 KeyError。"""
    import copy
    t2 = copy.deepcopy(table)
    t2["items"]["A5"] = {"pricing": "flat"}  # 缺 val
    rows = [row("A5", ["●", "-"])]
    out = compute_value_diff(rows, t2, legacy_mode=False)
    assert "A5" in out["missing_rules"]
    assert out["blocked"] is True


def test_m2_magic_carpet_suspension_9000(table):
    """2026-10-13 carkit suspension.py 新语义对齐：空气/魔毯=软硬+高低组合=9000。
    方向约定：col1=基准（无），col2=具备方 → 差价为正。"""
    def m2_amount(a, b):
        out = compute_value_diff([row("M2", [a, b])], table, legacy_mode=False)
        return (out["items"]["M2"]["amount"], "M2" in out["missing_rules"])
    assert m2_amount("-", "魔毯智能悬架") == (9000.0, False)   # 原 fallback 0 漏计
    assert m2_amount("-", "空气悬架") == (9000.0, False)        # 原 8000 漂移
    assert m2_amount("-", "软硬+空气悬架") == (9000.0, False)
    assert m2_amount("-", "软硬调节") == (1000.0, False)
    assert m2_amount("-", "高低调节") == (8000.0, False)
    assert m2_amount("-", "软硬+高低调节") == (9000.0, False)
    assert m2_amount("可变悬架", "-") == (None, False)  # 未识别类型(0元档) vs 无=无可计差价→文本差异不计价
