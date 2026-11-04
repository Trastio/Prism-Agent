"""概念配置抽取器（specs/config-workshop v5）。
从 config_snapshots categories 按 concept_configs.json 映射取值 → 档位归一 → 赋值查询。
插拔设计：替换 JSON 文件并重启服务后切正式赋值表，不改代码。
注意：路径用 Path(__file__) 绝对定位（比既有 os.path.join("data",...) 更健壮，
不依赖 cwd），与 option_prices.py 的 os.path.join 模式有意偏离。"""
from __future__ import annotations

import json, re
from pathlib import Path

from src.api.dashboard_data import _state  # v8 4 态判读（单一真相源，避免本地复制漂移）

_CONFIGS: list[dict] | None = None
_CONFIGS_BY_ID: dict[str, dict] | None = None
_WEIGHTS: dict | None = None
_REVERSE_INDEX: dict[tuple[str, str], str] | None = None


def _load_configs() -> list[dict]:
    global _CONFIGS, _CONFIGS_BY_ID
    if _CONFIGS is None:
        p = Path(__file__).parent.parent.parent / "data" / "concept_configs.json"
        with open(p, "r", encoding="utf-8") as f:
            _CONFIGS = json.load(f)
        _CONFIGS_BY_ID = {c["id"]: c for c in _CONFIGS}
    return _CONFIGS


def _configs_by_id() -> dict[str, dict]:
    """{concept_id: cfg} 索引（O(1) 查找，specs/config-workshop v5 /simplify）。"""
    if _CONFIGS_BY_ID is None:
        _load_configs()
    return _CONFIGS_BY_ID


def _build_reverse_index() -> dict[tuple[str, str], str]:
    """从 concept_configs.json 正向映射构建反向索引 (ah_category, ah_param) → concept_id。
    specs/config-workshop v7 P0-3（方案 C）：供配置对比/阶梯/年款双层定价反向查 concept_id。"""
    global _REVERSE_INDEX
    if _REVERSE_INDEX is None:
        configs = _load_configs()
        _REVERSE_INDEX = {(c["ah_category"], c["ah_param"]): c["id"] for c in configs}
    return _REVERSE_INDEX


def _reverse_lookup(ah_category: str, ah_param: str) -> str | None:
    """反向查找 concept_id。先精确 dict 查；miss 时按 contains 兜底
    （快照字段名可能残缺，如"卫星航系统"vs concept 的"卫星导航系统"，
    与正向 _find_param 同根源——concept 的 ah_param 是完整名，快照可能是残缺名）。
    类别精确匹配（不做类别 contains，比 _find_param Pass2 更严，避免跨类别误命中）；
    参数双向 contains（ah_param 是 concept 完整名的子串，或反之）。"""
    idx = _build_reverse_index()
    # 精确
    cid = idx.get((ah_category, ah_param))
    if cid:
        return cid
    # contains 兜底：ah_param 是 concept 完整名的子串，或反之
    for (cat, param), c in idx.items():
        if cat == ah_category and (ah_param in param or param in ah_param):
            return c
    return None


def _concept_price_for_param(ah_category: str, ah_param: str,
                             manual_prices: dict, tier: int = 1) -> float | None:
    """双层定价（specs/config-workshop v7 P0-3 方案 C）：
    手填价（option_prices 原生参数名）优先 → 概念赋值（concept_weights）兜底 → 均 None（未定价）。
    看板横表等 presence 折价场景无 tier 概念，默认 tier=1（具备方档位）。
    per_unit 型无 value 时 _price_for 落 weights[tier]（多为 0），不编造。"""
    # 手填覆盖优先（按原生参数名）
    if ah_param in manual_prices:
        return manual_prices[ah_param]
    # 概念赋值兜底
    cid = _reverse_lookup(ah_category, ah_param)
    if cid is None:
        return None
    cfg = _configs_by_id().get(cid)
    if cfg is None:
        return None
    return _price_for(cfg, _load_weights(), tier)


def _concept_tier_for_state(ah_category: str, ah_param: str, state: str) -> int:
    """根据 4 态返回概念 tier（dashboard-v8 选配中档/标配高档口径）。
    标配→cfg['tier_high']（默认 1）；选配→cfg['tier_mid']（默认 1，boolean 无独立中档时同高档）；
    其余（数值/文本）→高档。反向未命中 → 1（fallback，手填价不受 tier 影响）。"""
    cid = _reverse_lookup(ah_category, ah_param)
    if cid is None:
        return 1
    cfg = _configs_by_id().get(cid)
    if cfg is None:
        return 1
    if state == "选配":
        return cfg.get("tier_mid", 1)
    return cfg.get("tier_high", 1)


def _load_weights() -> dict:
    global _WEIGHTS
    if _WEIGHTS is None:
        p = Path(__file__).parent.parent.parent / "data" / "concept_weights.json"
        with open(p, "r", encoding="utf-8") as f:
            _WEIGHTS = json.load(f)
    return _WEIGHTS


def _find_param(categories: dict, ah_cat: str, ah_param: str, match: str = "contains") -> tuple[str | None, object]:
    """在 categories 里找匹配的参数。返回 (param_name, value)。
    三遍匹配（config-horizontal-compare rq02 修复）：
    Pass0 类别精确 + 参数 **exact**（ah_param 完整名 == 字段名时直接返回，防 longest-contains
    误选更长 sibling 字段，如 ah_param='电动后备厢' 时不选 '电动后备厢位置记忆'）
    → Pass1 类别精确 + 参数 contains（最长参数名优先，**Pass0 未命中才走**；
    防「座椅加热」被首命中顺序短路边命中歧义行，或长目标名落空）
    → Pass2 类别 contains 兜底（双向 contains：防字体加密截/扩类别名，
    如快照键「被动安」vs 概念类别「被动安全」）+ 参数最长 contains。
    match="exact" 保留参数精确匹配（现 61 项配置均 contains，仅兼容存量签名）。"""
    if match == "exact":
        for p, v in (categories.get(ah_cat) or {}).items():
            if p == ah_param:
                return p, v
        return None, None
    # Pass 0: 类别精确 + 参数 exact（rq02：优先 exact match 防 sibling 误选）
    for p, v in (categories.get(ah_cat) or {}).items():
        if p == ah_param:
            return p, v
    # Pass 1: 类别精确 + 参数 contains（最长参数名优先）
    best_p, best_v, best_len = None, None, 0
    for p, v in (categories.get(ah_cat) or {}).items():
        if ah_param in p and len(p) > best_len:
            best_p, best_v, best_len = p, v, len(p)
    if best_p:
        return best_p, best_v
    # Pass 2: 类别 contains 兜底（双向：快照键被截短或加长都容忍）+ 参数最长 contains
    for ckey, params in categories.items():
        if ckey != ah_cat and (ah_cat in ckey or ckey in ah_cat):
            for p, v in params.items():
                if ah_param in p and len(p) > best_len:
                    best_p, best_v, best_len = p, v, len(p)
    if best_p:
        return best_p, best_v
    return None, None


def _extract_value(raw, spec_id: str) -> str | list | None:
    """从参数值取指定 spec_id 的值。dict→按 spec_id 取，标量→直接。
    T1b.1：`-`/`—` 是之家"无"标记 → 返回字符串（让 boolean 分支判 tier=0 入分母），
    不再归 None（原归 None 会被上层当"缺采" tier=-1 不入分母，与"无"语义混淆）。
    字段缺失（dict 无该 spec_id / raw=None）才是真缺采 → 返回 None。
    list[{name}]（复合功能 sublist 保结构）原样返回供 sublist_contains 解析。"""
    if isinstance(raw, dict):
        v = raw.get(str(spec_id), raw.get(spec_id))
    else:
        v = raw
    if v is None:
        return None  # 字段缺失 / raw=None → 真缺采
    if isinstance(v, list):
        return v
    s = str(v).strip()
    if s == "":
        return None  # 空值 → 缺采（与"-"区分）
    return s  # "-" / "—" / "●" / "○" / 数值 / 文本 → 都返回字符串


def _as_str(val) -> str:
    """把 extract 值归一为字符串：list[{name}] → names 用 ' / ' join（向后兼容
    旧 join 快照的展示口径）；str → 原样。"""
    if isinstance(val, list):
        return " / ".join(it.get("name", "") for it in val if isinstance(it, dict))
    return str(val)


def _sublist_names(val) -> list[str]:
    """从 extract 值取 subname 列表：list[{name}] → [name,...]；
    str → 视为旧 join 串按 ' / ' 拆分（兼容未重刷快照）。"""
    if isinstance(val, list):
        return [it.get("name", "") for it in val if isinstance(it, dict)]
    if val is None:
        return []
    return [p.strip() for p in str(val).split("/") if p.strip()]


def _sublist_hit(cfg: dict, val) -> bool:
    """复合枚举子项命中：val 的子项名列表中任一含 extract_pattern（支持 str/list 多关键词）。
    供 extract_concept（评分）与 concept_present_cell（看板/差价）共用，避免两处口径漂移。"""
    names = _sublist_names(val)
    pattern = cfg.get("extract_pattern", "")
    pats = pattern if isinstance(pattern, list) else [pattern]
    return any(any(p and p in n for n in names) for p in pats)


def concept_present_cell(cfg: dict, categories: dict, spec_id: str) -> tuple[str, int | None, str | None]:
    """看板横表/差价的「单格语义求值」（单一真相源：看板展示与差价引擎共用）。

    按概念项自身的 extract 规则判读「是否具备」，返回 (展示值, present, 命中字段名)：
    - 字段未命中 → ("该车系无此项", 0, None)（确认 absence）
    - 值缺失（缺采）→ ("缺采", None, 字段名)（不可确认 absence，不参与计价）
    - extract=sublist_contains（复合枚举子项）→ 命中 extract_pattern → ("●", 1)，否则 ("-", 0)。
      修正「字段有值 ≠ 该子项具备」：如「辅助驾驶路段」含"高速路段"才算高速NOA；
      「前排座椅功能」含"按摩"才算前排座椅按摩 —— 旧口径下双方字段都非空 → 差价判"不计"，
      真实子项差异被系统性吞掉（差价方向算反的根因）。
    - 其余（boolean/regex_num/discrete/exact 等）保持原样展示 + 字段存在性判读
      （值型项需原始值参与数值差计价，不能折叠为 ●/-）。
    命中字段名（pname）供调用方登记 field 溯源（sources）。
    """
    pname, raw = _find_param(categories, cfg["ah_category"], cfg["ah_param"],
                             cfg.get("match", "contains"))
    if pname is None:
        return "该车系无此项", 0, None
    val = _extract_value(raw, spec_id)
    if val is None:
        return "缺采", None, pname
    if cfg.get("extract") == "sublist_contains":
        return (("●", 1, pname) if _sublist_hit(cfg, val) else ("-", 0, pname))
    disp = _as_str(val)
    return disp, (0 if _state(disp) == "无" else 1), pname


def _parse_num(s: str) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", s or "")
    return float(m.group()) if m else None


def _weight_for(concept_id: str, tier: int) -> float:
    weights = _load_weights()
    w = weights.get(concept_id, {})
    if w.get("pricing") == "per_unit":
        return 0  # per_unit 由 score_concept 按 value 计算
    return w.get("weights", {}).get(str(tier), 0)


def _price_for(cfg: dict, weights: dict, tier: int, value=None) -> float:
    """单项概念配置计价（score_concept 与 spec_compare_horizontal 共用，/simplify 归一）。
    per_unit→value*unit_price；per_count→tier*per_count；其余→weights[tier]。"""
    w = weights.get(cfg["id"], {})
    if w.get("pricing") == "per_unit" and value is not None and isinstance(value, (int, float)):
        return value * w.get("unit_price", 0)
    elif w.get("pricing") == "per_count":
        return max(0, tier) * w.get("per_count", 0)
    else:
        return w.get("weights", {}).get(str(tier), 0)


def extract_concept(concept_id: str, categories: dict, spec_id: str) -> dict:
    """抽取单项概念配置的值/档位/赋值。
    注：per_unit/per_count 型的 price 在 score_concept 里计算，
    extract_concept 返回的 price 仅供 tier-priced 项使用。"""
    configs = _load_configs()
    cfg = _configs_by_id().get(concept_id)
    if not cfg:
        return {"tier": -1, "value": None, "price": 0}

    pname, raw = _find_param(categories, cfg["ah_category"], cfg["ah_param"], cfg.get("match", "contains"))
    if pname is None:
        return {"tier": -1, "value": None, "price": 0, "note": "快照无此参数"}

    val_str = _extract_value(raw, spec_id)
    if val_str is None:
        return {"tier": -1, "value": None, "price": 0, "note": "该版型无此参数"}

    extract = cfg.get("extract", "exact")
    if extract == "sublist_contains":
        # 复合功能 sublist 包含匹配（Task9 方案1）：检查 sublist 的 subname 列表
        # 是否含关键词（口径归一到 _sublist_hit，与看板/差价 concept_present_cell 共用）。
        # tier_hit/tier_miss 可在 cfg 覆盖（默认 1/0=boolean 口径）；
        # K5 等"命中只能确认到中档"的项设 tier_hit=中档 tier、tier_miss=-1（不入分母）。
        hit = _sublist_hit(cfg, val_str)
        tier = cfg.get("tier_hit", 1) if hit else cfg.get("tier_miss", 0)
        price = 0
        if tier >= 0:
            t = next((x for x in cfg.get("tiers", []) if x.get("tier") == tier), None)
            price = t.get("price", _weight_for(cfg["id"], tier)) if t else _weight_for(cfg["id"], tier)
        return {"tier": tier, "value": _as_str(val_str), "price": price}
    # 其余 extract 类型按字符串处理（list → ' / ' join 归一）
    val_str = _as_str(val_str)
    if extract == "regex_num":
        num = _parse_num(val_str)
        if num is None:
            return {"tier": -1, "value": val_str, "price": 0}
        # 档位归一（注意：tiers 的 value_min/value_max 必须连续无缝隙，
        # 否则缝隙值会落到 tier=-1。JSON 填写时确保覆盖全区间）
        # 跳过无数值区间的纯展示档（如 {"value": null, "tier": -1} "无"）
        for t in cfg.get("tiers", []):
            if "value_min" not in t and "value_max" not in t:
                continue
            if t.get("value_min", 0) <= num <= t.get("value_max", 9999):
                # per_unit 项不在此处定价（由 score_concept 按 value 计算）；
                # 其余取 tier 自带 price，缺失则查 weights（如 A4 价格在 weights）
                price = t.get("price", _weight_for(cfg["id"], t["tier"])) if cfg.get("pricing") != "per_unit" else 0
                return {"tier": t["tier"], "value": num, "raw": val_str, "price": price}
        return {"tier": -1, "value": num, "raw": val_str, "price": 0}
    elif extract == "regex_group":
        m = re.search(cfg.get("extract_pattern", r"(\d+)"), val_str)
        if m:
            captured = m.group(1)
            for t in cfg.get("tiers", []):
                if str(t.get("label", "")).endswith(captured) or captured in str(t.get("label", "")):
                    return {"tier": t["tier"], "value": f"R{captured}", "price": t.get("price", 0), "raw": val_str}
            # 捕获值落在档位表外 → 归不了档：tier=-1 不入分母（P1#11，
            # 原 tier=0 会被 score_concept 当「有效档位 0 分」计入，虚增分母）
            return {"tier": -1, "value": f"R{captured}", "raw": val_str}
        return {"tier": -1, "value": val_str, "price": 0}
    elif extract == "boolean":
        # v8 4 态（根因 A/P1-12）：○ 选配旧被当"无"(tier 0) → 现归中档 tier（≥1，入分母）。
        # 标配→高档；选配→中档；无→0 档；缺采在 _extract_value 阶段已返回 tier=-1。
        state = _state(val_str)
        if state == "标配":
            tier = cfg.get("tier_high", 1)
        elif state == "选配":
            tier = cfg.get("tier_mid", 1)  # 中档，非 0（选配算具备，入分母）
        else:  # 无 / 数值 / 文本（boolean 非典型值，按无处理）
            tier = 0
        return {"tier": tier, "value": val_str,
                "price": _weight_for(cfg["id"], tier)}
    elif extract == "discrete":
        # 离散值映射到 tier（如单电机→0/双电机→1/三电机→2）
        # 两遍匹配：先精确，再子串（最长标签优先，防短标签误匹配）
        tiers = cfg.get("tiers", [])
        # Pass 1: 精确匹配
        for t in tiers:
            if val_str == t.get("label"):
                return {"tier": t["tier"], "value": val_str,
                        "price": t.get("price", _weight_for(cfg["id"], t["tier"]))}
        # Pass 2: 子串匹配，最长标签优先（防短标签误匹配，如"电动"先于"感应电动"）
        best_t, best_len = None, 0
        for t in tiers:
            label = t.get("label", "")
            if label and label in val_str and len(label) > best_len:
                best_t, best_len = t, len(label)
        if best_t:
            return {"tier": best_t["tier"], "value": val_str,
                    "price": best_t.get("price", _weight_for(cfg["id"], best_t["tier"]))}
        # 两遍都匹配不到档位标签 → 归不了档：tier=-1 不入分母（P1#11，
        # 「匹配到参数但归不了档」≠「有效档位 0 分」，原 tier=0 虚增分母）
        return {"tier": -1, "value": val_str, "price": 0}
    else:  # exact
        # 匹配到参数但无 tiers 归档 → 不给兜底 0 档（不入分母，P1#11）
        return {"tier": -1, "value": val_str, "price": 0}


def score_concept(categories: dict, spec_id: str, energy: str = "纯电") -> dict:
    """计算 61 项概念配置评分。能源自适应分母：不在 energy_scope 的项从分母扣除。"""
    configs = _load_configs()
    weights = _load_weights()
    items = {}
    total = 0.0
    denominator_items = 0

    for cfg in configs:
        cid = cfg["id"]
        scope = cfg.get("energy_scope", ["纯电", "增程", "插混"])
        if energy not in scope:
            items[cid] = {"tier": -1, "value": None, "price": 0, "note": "能源不适用"}
            continue
        r = extract_concept(cid, categories, spec_id)
        items[cid] = r
        if r["tier"] >= 0:
            denominator_items += 1
            r["price"] = _price_for(cfg, weights, r["tier"], r.get("value"))
            total += r.get("price", 0)

    return {"total": round(total, 0), "items": items, "denominator": denominator_items}
