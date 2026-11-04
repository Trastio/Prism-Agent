"""概念配置「单格语义求值」与蕴含关系单测（2026-10-14 NOA/差价方向根因根治）。

锁定三件事（防再犯）：
1. C1/C2 映射到「辅助驾驶路段」并按复合枚举子项（extract=sublist_contains）求值——
   城市NOA 不再从「辅助驾驶系统」（智驾品牌名，如 猎鹰500/Leapmotor Pilot）读取。
2. concept_present_cell：子项命中→●/未命中→-；字段未命中→该车系无此项；缺采→None。
3. spec_compare_horizontal 的 implies（城市NOA⇒高速NOA）同列传递"具备"。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.insights.concept_config import _load_configs, concept_present_cell
from src.storage.db import init_db, session_scope
from src.models.orm import ConfigSnapshot
from src.api.dashboard_data import get_config_snapshot, spec_compare_horizontal

_CFG = {c["id"]: c for c in _load_configs()}


# ---------------- 纯函数：concept_present_cell ----------------

def _cats(cat, param, spec_vals):
    return {cat: {param: spec_vals}}


def test_c1_highway_noa_from_road_segment():
    """C1 高速NOA：按 辅助驾驶路段 是否含"高速路段"判读，命中→●。"""
    c1 = _CFG["C1"]
    assert c1["ah_param"] == "辅助驾驶路段" and c1["extract"] == "sublist_contains"
    hit = _cats("驾驶功能", "辅助驾驶路段", {"s1": [{"name": "高速路段"}]})
    miss = _cats("驾驶功能", "辅助驾驶路段", {"s1": [{"name": "城市路段"}]})
    assert concept_present_cell(c1, hit, "s1")[:2] == ("●", 1)
    assert concept_present_cell(c1, miss, "s1")[:2] == ("-", 0)


def test_c2_city_noa_not_from_system_brand_name():
    """C2 城市NOA：映射修正为 辅助驾驶路段（原误映射 辅助驾驶系统=品牌名）。"""
    c2 = _CFG["C2"]
    assert c2["ah_param"] == "辅助驾驶路段"
    assert c2["extract"] == "sublist_contains" and c2.get("implies") == ["C1"]
    hit = _cats("驾驶功能", "辅助驾驶路段", {"s1": [{"name": "城市路段"}, {"name": "高速路段"}]})
    assert concept_present_cell(c2, hit, "s1")[:2] == ("●", 1)
    # 只有品牌名（辅助驾驶系统）、无 辅助驾驶路段 → 城市NOA 判"该车系无此项"（不再误显示品牌名）
    only_brand = _cats("驾驶功能", "辅助驾驶系统", {"s1": [{"name": "Leapmotor Pilot"}]})
    assert concept_present_cell(c2, only_brand, "s1")[:2] == ("该车系无此项", 0)


def test_i1_keyless_entry_requires_full_car():
    """I1 无钥匙进入(4门)：仅"全车"算具备，"驾驶位"不算。"""
    i1 = _CFG["I1"]
    assert i1["extract"] == "sublist_contains"
    assert concept_present_cell(i1, _cats("外观/防盗", "无钥匙进入功能", {"s1": "全车"}), "s1")[:2] == ("●", 1)
    assert concept_present_cell(i1, _cats("外观/防盗", "无钥匙进入功能", {"s1": "驾驶位"}), "s1")[:2] == ("-", 0)


def test_present_cell_missing_field_and_value():
    c1 = _CFG["C1"]
    # 字段不存在 → 确认 absence（0，不参与 presence 差异计价之外的缺采）
    assert concept_present_cell(c1, {"驾驶功能": {}}, "s1")[:2] == ("该车系无此项", 0)
    # 值为空 → 缺采（None，不可确认 absence）
    empty = _cats("驾驶功能", "辅助驾驶路段", {"s1": None})
    assert concept_present_cell(c1, empty, "s1")[:2] == ("缺采", None)


def test_non_sublist_item_keeps_raw_value():
    """值型项（续航 regex_num）保持原样展示，供数值差计价。"""
    a1 = _CFG["A1"]
    cats = _cats(a1["ah_category"], a1["ah_param"], {"s1": "600"})
    cell, present, _ = concept_present_cell(a1, cats, "s1")
    assert cell == "600" and present == 1


# ---------------- 被动安全复合字段（D1/D2/D3）----------------

def test_d1_front_side_airbag():
    """D1 前排侧气囊：字段值"前● / 后●"复合，按"前●"判读；○选配按口径=无。"""
    d1 = _CFG["D1"]
    assert d1["extract"] == "sublist_contains"
    assert concept_present_cell(d1, _cats("被动安全", "前排侧气囊", {"s1": "前● / 后-"}), "s1")[:2] == ("●", 1)
    assert concept_present_cell(d1, _cats("被动安全", "前排侧气囊", {"s1": "前○ / 后-"}), "s1")[:2] == ("-", 0)


def test_d2_curtain_airbag_either_row():
    d2 = _CFG["D2"]
    assert concept_present_cell(d2, _cats("被动安全", "前后排头部气囊(气帘)", {"s1": "前● / 后●"}), "s1")[:2] == ("●", 1)
    assert concept_present_cell(d2, _cats("被动安全", "前后排头部气囊(气帘)", {"s1": "-"}), "s1")[:2] == ("-", 0)


def test_d3_rear_side_airbag_same_combined_field():
    """D3 后排侧气囊：与前排侧气囊同字段（值"前● / 后●"），按"后●"判读（原 ah_param 匹配不到字段）。"""
    d3 = _CFG["D3"]
    assert d3["ah_param"] == "前排侧气囊" and d3["extract"] == "sublist_contains"
    assert concept_present_cell(d3, _cats("被动安全", "前排侧气囊", {"s1": "前● / 后●"}), "s1")[:2] == ("●", 1)
    assert concept_present_cell(d3, _cats("被动安全", "前排侧气囊", {"s1": "前● / 后-"}), "s1")[:2] == ("-", 0)


# ---------------- DB-backed：spec_compare_horizontal 语义 + implies ----------------

def _seed(series_id, name, categories):
    with session_scope() as s:
        s.add(ConfigSnapshot(series_id=series_id, series_name=name,
                             energy="纯电", categories=categories))


def test_horizontal_semantic_cells_and_implies():
    """A=高速路段 / B=城市路段：C1(A有/B经蕴含补齐)、C2(A无/B有)。"""
    init_db("sqlite://")
    _seed("A", "A车", {"驾驶功能": {"辅助驾驶路段": {"s1": [{"name": "高速路段"}]}}})
    _seed("B", "B车", {"驾驶功能": {"辅助驾驶路段": {"s1": [{"name": "城市路段"}]}}})
    snaps = {m: get_config_snapshot(m) for m in ("A", "B")}
    hc = asyncio.run(spec_compare_horizontal([("A", "s1"), ("B", "s1")], snaps))
    rows = {r["id"]: r for r in hc["rows"]}
    # C2 城市NOA：A 无 / B 有
    assert rows["C2"]["cells"] == ["-", "●"]
    # C1 高速NOA：A 有；B 无"高速路段"但被 C2 蕴含 → 同列补齐为 ●
    assert rows["C1"]["cells"] == ["●", "●"]
    assert rows["C1"]["present"] == [1, 1]


def test_horizontal_city_noa_not_from_brand_name():
    """仅有智驾品牌名（辅助驾驶系统）的版型：城市NOA 不再显示品牌名。"""
    init_db("sqlite://")
    _seed("X", "X车", {"驾驶功能": {"辅助驾驶系统": {"s1": [{"name": "猎鹰500"}]}}})
    _seed("Y", "Y车", {"驾驶功能": {"辅助驾驶系统": {"s1": [{"name": "Leapmotor Pilot"}]}}})
    snaps = {m: get_config_snapshot(m) for m in ("X", "Y")}
    hc = asyncio.run(spec_compare_horizontal([("X", "s1"), ("Y", "s1")], snaps))
    # 关键回归：整表任何单元格都不应再出现智驾系统品牌名
    all_cells = [c for r in hc["rows"] for c in r["cells"]]
    assert "猎鹰500" not in all_cells and "Leapmotor Pilot" not in all_cells
    # 两列均无「辅助驾驶路段」→ 城市NOA 行不展示（旧口径会显示品牌名）
    assert "C2" not in {r["id"] for r in hc["rows"]}


# ---------------- hidden_if_any：激光雷达在 NOA 存在时整行隐藏 ----------------

def test_lidar_row_hidden_when_noa_present():
    """任一列有 NOA（高速/城市）→ 激光雷达(K1) 整行隐藏。"""
    init_db("sqlite://")
    _seed("A", "A车", {"驾驶功能": {"辅助驾驶路段": {"s1": [{"name": "高速路段"}]}},
                       "驾驶硬件": {"激光雷达数量": {"s1": [{"name": "1个"}]}}})
    _seed("B", "B车", {"驾驶硬件": {"激光雷达数量": {"s1": [{"name": "1个"}]}}})
    snaps = {m: get_config_snapshot(m) for m in ("A", "B")}
    hc = asyncio.run(spec_compare_horizontal([("A", "s1"), ("B", "s1")], snaps))
    ids = {r["id"] for r in hc["rows"]}
    assert "C1" in ids          # 高速NOA 行在
    assert "K1" not in ids      # A 有 NOA → 激光雷达行隐藏


def test_lidar_row_visible_when_no_noa():
    """两侧都无 NOA → 激光雷达行保留展示（不计价由 value_diff excluded 负责）。"""
    init_db("sqlite://")
    _seed("A", "A车", {"驾驶硬件": {"激光雷达数量": {"s1": [{"name": "1个"}]}}})
    _seed("B", "B车", {"驾驶硬件": {"激光雷达数量": {"s1": "-"}}})
    snaps = {m: get_config_snapshot(m) for m in ("A", "B")}
    hc = asyncio.run(spec_compare_horizontal([("A", "s1"), ("B", "s1")], snaps))
    rows_by_id = {r["id"]: r for r in hc["rows"]}
    assert "K1" in rows_by_id
    assert rows_by_id["K1"]["cells"] == ["1个", "-"]
