"""人工题集转金标 Block 0 单测：market_series_filter + /api/series-filter。

in-memory sqlite fixture 造 5 车系（design Block 0 §测试 规格钉死）：
- 银河EV跨价：BEV 跨价（msrp 11-15万）+ 锚月众数（wheelbase 2750×2 > 2790×1）
  + 9月中旧行 wheelbase 2600/无零售（验证属性锚月取车系自身最新月）
- 混动旗舰：PHEV（插电式混合）
- 油混经典：ICE 油电混合 + 两锚分离（属性锚=9月末无零售，零售锚=8月末 8000）
- 风云 T7形：无零售有属性（T7 形态；增程式混合 → PHEV 桶），latest_retail=None
- 微电小钢炮：A0 级（验证 level 精确，A 不吞 A0）
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.api import market_data, market_routes
from src.models.orm import SalesTrim
from src.storage.db import init_db, session_scope


def _t(code, series, year, month, **kw):
    return SalesTrim(model_code=code, series=series, year=year, month=month, **kw)


@pytest.fixture()
def db():
    """in-memory sqlite：init_db 建表后灌 5 车系（每测试独立实例）。"""
    init_db("sqlite://")
    rows = [
        # S1 银河EV跨价：BEV 跨价；9月中旧行（wheelbase 2600/brand 领克 无零售）作锚月干扰
        _t("s1-m", "银河EV跨价", 2026, "9月中", energy_type="纯电动", level="A",
           wheelbase_mm=2600, retail=None, brand="领克",
           manufacturer="领克汽车"),
        _t("s1-a", "银河EV跨价", 2026, "9月末", energy_type="纯电动", level="A",
           msrp=110000.0, wheelbase_mm=2750, retail=2000, tp=105000.0,
           brand="吉利", manufacturer="吉利汽车"),
        _t("s1-b", "银河EV跨价", 2026, "9月末", energy_type="纯电动", level="A",
           msrp=130000.0, wheelbase_mm=2750, retail=2000, brand="吉利",
           manufacturer="吉利汽车"),
        _t("s1-c", "银河EV跨价", 2026, "9月末", energy_type="纯电动", level="A",
           msrp=150000.0, wheelbase_mm=2790, retail=1000, brand="几何",
           manufacturer="几何汽车"),
        # S2 混动旗舰：PHEV（插电式混合）
        _t("s2-a", "混动旗舰", 2026, "9月末", energy_type="插电式混合", level="B",
           msrp=160000.0, wheelbase_mm=2800, retail=1500, brand="比亚迪"),
        _t("s2-b", "混动旗舰", 2026, "9月末", energy_type="插电式混合", level="B",
           msrp=180000.0, wheelbase_mm=2800, retail=1500, brand="比亚迪"),
        # S3 油混经典：ICE（油电混合）；两锚分离（属性锚 9月末无零售带空格 brand，零售锚 8月末）
        _t("s3-a", "油混经典", 2026, "8月末", energy_type="油电混合", level="A",
           msrp=185000.0, wheelbase_mm=2650, retail=8000, brand="一汽",
           manufacturer="中国一汽"),
        _t("s3-m", "油混经典", 2026, "9月中", energy_type="油电混合", level="A",
           wheelbase_mm=2700, retail=None, brand="一汽",
           manufacturer="中国一汽"),
        _t("s3-b", "油混经典", 2026, "9月末", energy_type="油电混合", level="A",
           msrp=190000.0, wheelbase_mm=2700, retail=None, brand="一汽 丰田",
           manufacturer="一汽 丰田汽车"),
        _t("s3-c", "油混经典", 2026, "9月末", energy_type="油电混合", level="A",
           msrp=210000.0, wheelbase_mm=2700, retail=None, brand="一汽 丰田",
           manufacturer="一汽 丰田汽车"),
        # S4 风云 T7形：T7 形态（无零售有属性）；增程式混合 → PHEV 桶
        _t("s4-m", "风云 T7形", 2026, "9月中", energy_type="增程式混合", level="C",
           wheelbase_mm=2900, retail=None, brand="奇瑞",
           manufacturer="奇瑞 汽车"),
        _t("s4-a", "风云 T7形", 2026, "9月末", energy_type="增程式混合", level="C",
           msrp=230000.0, wheelbase_mm=2950, retail=None, brand="奇瑞",
           manufacturer="奇瑞 汽车"),
        # S5 微电小钢炮：A0 级（level 精确考点）
        _t("s5-a", "微电小钢炮", 2026, "9月末", energy_type="纯电动", level="A0",
           msrp=70000.0, wheelbase_mm=2500, retail=50, brand="上汽通用五菱"),
        _t("s5-b", "微电小钢炮", 2026, "9月末", energy_type="纯电动", level="A0",
           msrp=90000.0, wheelbase_mm=2500, retail=50, brand="上汽通用五菱"),
        # S6 智界S7形：拍板 B 考点——子品牌不含查询词、仅集团 manufacturer 命中
        _t("s6-a", "智界S7形", 2026, "9月末", energy_type="纯电动", level="B",
           msrp=240000.0, wheelbase_mm=2950, retail=300, brand="智界",
           manufacturer="奇瑞汽车"),
        _t("s6-b", "智界S7形", 2026, "9月末", energy_type="纯电动", level="B",
           msrp=250000.0, wheelbase_mm=2950, retail=300, brand="智界",
           manufacturer="奇瑞汽车"),
    ]
    with session_scope() as s:
        s.add_all(rows)
    yield


def _names(out) -> list[str]:
    rows = out["rows"] if isinstance(out, dict) else out
    return [r["series"] for r in rows]


def test_no_filter_retail_desc_none_last(db):
    out = market_data.market_series_filter()
    assert out["total_library"] == 6
    assert out["total_matched"] == 6
    # latest_retail 降序，None 最后，再按名
    assert _names(out) == ["油混经典", "银河EV跨价", "混动旗舰", "智界S7形",
                           "微电小钢炮", "风云 T7形"]
    by = {r["series"]: r for r in out["rows"]}
    # 两锚分离：S3 属性取 9月末（wheelbase 2700 / msrp 19-21万），零售取 8月末 8000
    assert by["油混经典"]["latest_retail"] == 8000
    assert by["油混经典"]["has_retail"] is True
    assert by["油混经典"]["wheelbase"] == 2700
    assert by["油混经典"]["msrp_min"] == 190000.0
    assert by["油混经典"]["msrp_max"] == 210000.0
    # T7 形态：latest_retail=None 排最后，属性仍可用（不丢行）
    assert by["风云 T7形"]["latest_retail"] is None
    assert by["风云 T7形"]["has_retail"] is False
    assert by["风云 T7形"]["wheelbase"] == 2950
    # 锚月众数：S1 wheelbase 2750（2 票）而非 2790/9月中 2600；msrp 非空 min/max
    assert by["银河EV跨价"]["wheelbase"] == 2750
    assert by["银河EV跨价"]["msrp_min"] == 110000.0
    assert by["银河EV跨价"]["msrp_max"] == 150000.0
    assert by["银河EV跨价"]["has_weighted"] is True  # 存在 tp 非空行
    # 行字段齐（design 规格钉死的 9 列）
    assert set(by["银河EV跨价"]) == {"series", "latest_retail", "has_retail",
                                     "has_weighted", "energy", "level",
                                     "msrp_min", "msrp_max", "wheelbase"}


def test_energy_enum_mapping(db):
    assert _names(market_data.market_series_filter(energy="BEV")) == \
        ["银河EV跨价", "智界S7形", "微电小钢炮"]
    # 增程式混合与插电式混合同归 PHEV 桶
    assert _names(market_data.market_series_filter(energy="PHEV")) == \
        ["混动旗舰", "风云 T7形"]
    # ICE=传统能源+油电混合（用户第9行期望锚）
    assert _names(market_data.market_series_filter(energy="ICE")) == ["油混经典"]
    assert _names(market_data.market_series_filter(energy="NEV")) == \
        ["银河EV跨价", "混动旗舰", "智界S7形", "微电小钢炮", "风云 T7形"]


def test_energy_illegal_enum_raises(db):
    with pytest.raises(ValueError):
        market_data.market_series_filter(energy="DIESEL")


def test_level_exact_match(db):
    # A 精确匹配，不吞 A0/A00
    assert _names(market_data.market_series_filter(level="A")) == \
        ["油混经典", "银河EV跨价"]
    assert _names(market_data.market_series_filter(level="A0")) == ["微电小钢炮"]


def test_price_partial_overlap(db):
    # 查询 [14.5,15.5]万 与 S1 [11,15]万 部分重叠 → 命中；其余不重叠
    assert _names(market_data.market_series_filter(
        price_min=145000, price_max=155000)) == ["银河EV跨价"]
    # 仅 price_min：闭区间端点 15万 也命中（S1 hi=150000）
    assert set(_names(market_data.market_series_filter(price_min=150000))) == \
        {"银河EV跨价", "混动旗舰", "油混经典", "智界S7形", "风云 T7形"}


def test_wheelbase_range(db):
    # 闭区间含端点；S1 取锚月众数 2750（非 9月中 2600），S3 取锚月 2700（非 8月末 2650）
    assert _names(market_data.market_series_filter(
        wheelbase_min=2650, wheelbase_max=2750)) == ["油混经典", "银河EV跨价"]
    assert _names(market_data.market_series_filter(wheelbase_min=2751)) == \
        ["混动旗舰", "智界S7形", "风云 T7形"]


def test_kw_space_stripped(db):
    # 车系名带空格"风云 T7形"，kw 去空格后包含命中（既有惯例）
    assert _names(market_data.market_series_filter(kw="风云T7形")) == ["风云 T7形"]
    assert _names(market_data.market_series_filter(kw="T7")) == ["风云 T7形"]


def test_brand_contains_and_space(db):
    # 锚月众数 brand="一汽 丰田"（带空格），查询去空格包含命中；子串 contains 亦可
    assert _names(market_data.market_series_filter(brand="一汽丰田")) == ["油混经典"]
    assert _names(market_data.market_series_filter(brand="丰田")) == ["油混经典"]
    assert _names(market_data.market_series_filter(brand="上汽")) == ["微电小钢炮"]


def test_brand_anchor_month_mode(db):
    # S1 锚月（9月末）众数=吉利（2 票 > 几何 1 票）；9月中旧行 brand=领克 不参与
    assert _names(market_data.market_series_filter(brand="吉利")) == ["银河EV跨价"]
    assert _names(market_data.market_series_filter(brand="领克")) == []
    # 拍板 B 后 brand=奇瑞：风云 T7形（brand 众数命中）+ 智界S7形（manufacturer 命中）
    assert _names(market_data.market_series_filter(brand="奇瑞")) == \
        ["智界S7形", "风云 T7形"]


def test_brand_manufacturer_only_hit(db):
    # 智界S7形：子品牌='智界' 不含'奇瑞'，仅集团 manufacturer='奇瑞汽车' 命中
    assert _names(market_data.market_series_filter(brand="奇瑞")) == \
        ["智界S7形", "风云 T7形"]
    # 反向：查子品牌词'智界'——brand 众数 contains 命中（manufacturer 不含智界）
    assert _names(market_data.market_series_filter(brand="智界")) == ["智界S7形"]


def test_brand_or_manufacturer_anchor_mode(db):
    # 仅 manufacturer 众数路径：S1 brand 众数='吉利' 不含'吉利汽车'，
    # manufacturer 锚月众数='吉利汽车'（2 票 > 几何汽车）contains 命中
    assert _names(market_data.market_series_filter(brand="吉利汽车")) == \
        ["银河EV跨价"]
    # 锚月众数语义：S3 manufacturer 旧行='中国一汽'（8月末/9月中）非锚月众数，
    # 锚月众数='一汽 丰田汽车' 不含'中国一汽' → 不命中（防旧行串入）
    assert _names(market_data.market_series_filter(brand="中国一汽")) == []
    # 非众数值不命中：S1 锚月几何 1 票非众数，brand/manufacturer 众数均不含
    assert _names(market_data.market_series_filter(brand="几何")) == []


def test_brand_plus_energy(db):
    # Excel 奇瑞题形态：brand=奇瑞 + 能耗枚举组合
    assert _names(market_data.market_series_filter(
        brand="奇瑞", energy="PHEV")) == ["风云 T7形"]


def test_combined_energy_price(db):
    assert _names(market_data.market_series_filter(
        energy="BEV", price_min=110000, price_max=130000)) == ["银河EV跨价"]


def _body(resp) -> dict:
    return json.loads(resp.body)


def test_route_rejects_illegal_energy(db):
    resp = market_routes.api_series_filter(energy="DIESEL")
    assert resp.status_code == 400
    assert "energy 非法枚举" in _body(resp)["error"]


def test_route_rejects_non_numeric_price(db):
    resp = market_routes.api_series_filter(price_min="abc")
    assert resp.status_code == 400
    assert "非数值" in _body(resp)["error"]
    resp = market_routes.api_series_filter(wheelbase_max="2.7米")
    assert resp.status_code == 400


def test_route_limit_and_truncation(db):
    out = market_routes.api_series_filter(limit="2")
    assert out["ok"] is True
    assert len(out["rows"]) == 2
    assert out["total_matched"] == 6
    assert out["_truncated"]["kept_rows"] == 2
    assert out["_truncated"]["total_matched"] == 6
    # limit 超 50 收敛为 50（不 400）
    out = market_routes.api_series_filter(limit="999")
    assert out["ok"] is True
    assert len(out["rows"]) == 6  # 库内仅 6 条，未触发 _truncated
    assert "_truncated" not in out


def test_route_passes_filters(db):
    out = market_routes.api_series_filter(
        energy="BEV", price_min="110000", price_max="130000", kw="银河")
    assert out["ok"] is True
    assert _names(out) == ["银河EV跨价"]


def test_route_passes_brand(db):
    out = market_routes.api_series_filter(brand="奇瑞")
    assert out["ok"] is True
    assert _names(out) == ["智界S7形", "风云 T7形"]


def test_cross_year_anchor_prefers_latest_year(db):
    """跨年锚月（本 change 核心教训的回归保护）：属性锚月取最新年月，零售锚月独立取最新有零售月。"""
    with session_scope() as s:
        s.add_all([
            _t("x1-a", "跨年车", 2025, "12月末", energy_type="纯电动", level="A",
               wheelbase_mm=2600, retail=500, brand="测试", manufacturer="测试汽车"),
            _t("x1-b", "跨年车", 2026, "1月中", energy_type="插电式混合", level="A",
               msrp=120000.0, wheelbase_mm=2700, retail=None, brand="测试", manufacturer="测试汽车"),
        ])
    out = market_data.market_series_filter(kw="跨年车")
    r = out["rows"][0]
    assert r["energy"] == "插电式混合"   # 属性锚月=2026-1月中（最新月），非 2025-12末
    assert r["wheelbase"] == 2700
    assert r["latest_retail"] == 500      # 零售锚月=2025-12末（唯一有零售月），两锚分离
    assert r["has_retail"] is True


def test_mode_tie_break_ascending_deterministic(db):
    """众数平票取值升序（确定性）：同计数 1:1 时 energy 取 '油电混合'（<纯电动）、level 取 'B'（<C）。"""
    with session_scope() as s:
        s.add_all([
            _t("y1-a", "平票车", 2026, "9月末", energy_type="纯电动", level="B",
               retail=10, brand="平票", manufacturer="平票汽车"),
            _t("y1-b", "平票车", 2026, "9月末", energy_type="油电混合", level="C",
               retail=10, brand="平票", manufacturer="平票汽车"),
        ])
    out = market_data.market_series_filter(kw="平票车")
    r = out["rows"][0]
    assert r["energy"] == "油电混合"
    assert r["level"] == "B"
