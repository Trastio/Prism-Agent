"""value_diff — 配置差价共享引擎（配置赋值口径改造，design.md D2）。

口径唯一实现：看板前端（dash_config.html §02 tfoot）与 agent 工具
（compare_configs_valued，M3）都经本函数出数字，前端不再自算（原
_computeDiffCells JS 实现已删，parity 由单测锁公式）。

单价来源优先级（proposal D5 手填覆盖优先）：
  manual_prices[param] → diff_pricing.items[id] → 无（未定价）
legacy_mode=True 时单价源= rows 自带 price（concept_weights 兜底）——仅供
parity 单测锁 JS 旧公式，生产不传（锁公式不锁单价源，见 self-check Gap1）。

真值表 data/diff_pricing.json（插拔：换文件+重启生效，version 随响应回传）。
本模块零路由依赖、零 DB 依赖，可独立单测。"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

_TABLE: dict | None = None
_FULL_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")

_ABSENT_TOKENS = ("-", "—", "–", "无", "✕", "×", "x", "X", "none", "null", "N/A")


def load_pricing_table() -> dict:
    """加载 diff_pricing.json（模块级缓存，进程内单例；换表重启服务）。"""
    global _TABLE
    if _TABLE is None:
        p = Path(__file__).parent.parent.parent / "data" / "diff_pricing.json"
        with open(p, "r", encoding="utf-8") as f:
            _TABLE = json.load(f)
    return _TABLE


def _cell_state(cell) -> str:
    """生产口径的单元格三态：present / absent / missing。
    与 JS 旧口径的差异（拍板的口径升级）：○ 选装按"无"（absent）判——
    proposal 决策"○选装=无"；legacy_mode 不走本函数（用 rows 自带 present）。"""
    if cell is None:
        return "missing"
    s = str(cell).strip()
    if s == "" or s == "缺采":
        return "missing"
    if s == "该车系无此项" or s in _ABSENT_TOKENS:
        return "absent"
    if s.startswith("○"):
        return "absent"  # ○选装=无
    return "present"


def _item_num(cell, item: dict | None):
    """按 item 配置取数值：sum_numbers=true 时取全部匹配之和（USB"前排3个/后排2个"=5），
    否则首个匹配（含 group(1) 语义）。"""
    pat = (item or {}).get("num_pattern")
    if pat and (item or {}).get("sum_numbers"):
        ms = list(re.finditer(pat, str(cell)))
        return sum(float(m.group(0)) for m in ms) if ms else None
    return _extract_num(cell, pat)


def _extract_num(cell, pattern: str | None):
    """数值提取：有 num_pattern 走正则 group(1)；否则整串纯数值（与 JS _numOf
    同口径，含千分位/km 容差仅在 pattern 缺省时有限放宽——保持可复算）。"""
    s = str(cell).strip()
    if pattern:
        m = re.search(pattern, s)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, IndexError):
                return None
        return None
    t = s.replace(",", "")
    if _FULL_NUM.match(t):
        return float(t)
    return None


def _band_value(cell: str, item: dict) -> tuple[bool, float | None]:
    """band 落档：absent 侧由调用方按 0 计；present 侧按 bands 顺序匹配
    （range 数值档需 num_pattern 提取；contains/all/any 文本档）。
    返回 (matched, value)；未匹配且无 fallback → (False, None) → missing_rules。"""
    num = _extract_num(cell, item.get("num_pattern")) if item.get("num_pattern") else None
    for b in item.get("bands", []):
        if "range" in b:
            if num is not None and b["range"][0] <= num <= b["range"][1]:
                return True, float(b["val"])
            continue
        s = str(cell)
        if "contains" in b:
            if b["contains"] in s:
                return True, float(b["val"])
        elif "all" in b:
            if all(x in s for x in b["all"]):
                return True, float(b["val"])
        elif "any" in b:
            if any(x in s for x in b["any"]):
                return True, float(b["val"])
    fb = item.get("fallback")
    if fb is None:
        return False, None
    return True, float(fb)


def _js_num(v):
    """JS `_numOf` 的 Python 复刻：整串纯数字才返回 float，否则 None。"""
    if v is None:
        return None
    s = str(v).strip()
    return float(s) if _FULL_NUM.match(s) else None


def _fmt_amount(amount: float) -> str:
    """JS `¥${Math.round(Math.abs(amount)).toLocaleString("en-US")}` 复刻。
    Math.round 是 half-up，Python round 是 banker's（round(10000.5)=10000）——
    用 floor(x+0.5) 对齐（审查 P2-1）。"""
    return f"{int(math.floor(abs(amount) + 0.5)):,}"


def _col_text(k: int, amount, total_n: int, priced_n: int, comparable: int,
              missing_n: int) -> tuple[bool, str]:
    """汇总文案。legacy：JS 四态逐字复刻；production 增缺规则态（self-check Gap：
    缺规则拒绝汇总——照 carkit 不脑补）。返回 (available, text)。"""
    if missing_n:
        return True, f"待定价（缺规则 {missing_n} 项，已列出于 missing_rules）"
    if comparable == 0:
        return False, "差价值不可用（该列概念配置无可比数据）"
    if total_n == 0:
        return True, "无差价项"
    if priced_n == 0:
        return True, f"未定价（共 {total_n} 项）"
    sign = "+" if amount >= 0 else "-"
    return True, (f"列{k + 1} 比列1 {sign}¥{_fmt_amount(amount)}"
                  f"（已定价 {priced_n} / 共 {total_n} 项）")


def _row_sig(states: list[str], cells: list) -> set:
    """行级语义签名（审查 P1-2）：absent/missing 态折叠为状态本身（"○"与"—"同
    为无，写法不同不算差异）；present 保留去空格原文。"""
    sigs = set()
    for s, c in zip(states, cells):
        sigs.add(s if s != "present" else f"present:{str(c).strip()}")
    return sigs


def _blank_cols(n_cols: int) -> list[dict]:
    cols = [{"k": 0, "available": True, "text": "基准", "amount": 0,
             "priced_n": 0, "total_n": 0, "comparable": 0}]
    cols.extend({"k": k, "available": True, "text": "", "amount": 0.0,
                 "priced_n": 0, "total_n": 0, "comparable": 0}
                for k in range(1, n_cols))
    return cols


def compute_value_diff(rows: list[dict], pricing_table: dict,
                       manual_prices: dict | None = None,
                       legacy_mode: bool = False) -> dict:
    """差价主计算。rows = spec_compare_horizontal 输出的 rows（is_concept/
    id/name/param/cells/present[/price]）。返回见模块 docstring。

    legacy_mode：逐字复刻 dash_config.html 原 `_computeDiffCells` JS 公式
    （presence±1×单价 + 双方纯数值差×单价，缺采整行跳过，未定价只计数，
    文本差异不计价），单价= rows.price（concept_weights 兜底）。"""
    manual = {str(k): v for k, v in (manual_prices or {}).items()}
    items_meta = (pricing_table or {}).get("items", {})
    excluded_ids = set((pricing_table.get("excluded") or {}).get("ids") or [])

    concept_rows = [r for r in (rows or []) if r.get("is_concept")]
    # 列数取全行最大（含非概念行）——JS 用 data.cols.length，与行是否概念无关
    n_cols = 0
    for r in (rows or []):
        n_cols = max(n_cols, len(r.get("present") or r.get("cells") or []))
    if n_cols == 0:
        n_cols = 1
    cols = _blank_cols(n_cols)
    diff_items: dict[str, dict] = {}
    missing_rules: list[str] = []

    def note(id_, **kw):
        cur = diff_items.setdefault(id_, {"verdict": "同", "amount": None,
                                          "unit_price": None, "price_source": "none",
                                          "note": ""})
        cur.update({k: v for k, v in kw.items() if v is not None})

    if legacy_mode:
        for r in concept_rows:
            pres = r.get("present") or []
            if len(pres) < n_cols:
                pres = pres + [None] * (n_cols - len(pres))
            cells = r.get("cells") or []
            price = r.get("price")
            if manual:
                price = manual.get(str(r.get("param")), price)
            for k in range(1, n_cols):
                c = cols[k]
                p0, pk = pres[0], pres[k]
                if p0 is None or pk is None:
                    continue  # 缺采整行跳过
                c["comparable"] += 1
                if p0 != pk:
                    delta = pk - p0                     # ① 有无差异 → ±1
                elif p0 == 1:
                    v0 = _js_num(cells[0] if cells else None)
                    vk = _js_num(cells[k] if len(cells) > k else None)
                    if v0 is None or vk is None or v0 == vk:
                        continue                        # 非数值行 / 取值相同 → 不计价
                    delta = vk - v0                     # ② 数值型差异 → 数值差
                else:
                    continue                            # 双方都不具备 → 不计价
                c["total_n"] += 1
                if price is None:
                    continue                            # 可定价但未定价 → 只计数
                c["priced_n"] += 1
                c["amount"] += price * delta
        for k in range(1, n_cols):
            c = cols[k]
            c["available"], c["text"] = _col_text(
                k, c["amount"], c["total_n"], c["priced_n"], c["comparable"], 0)
        config_adv = (cols[1]["amount"]
                      if (n_cols == 2 and cols[1]["available"]) else None)
        return {"columns": cols, "items": {}, "missing_rules": [],
                "blocked": False, "config_adv": config_adv, "flat_adv": None,
                "legacy": True}

    # ---------- 生产模式 ----------
    for r in concept_rows:
        id_ = str(r.get("id"))
        cells = r.get("cells") or []
        if len(cells) < n_cols:
            cells = cells + [None] * (n_cols - len(cells))
        states = [_cell_state(c) for c in cells]
        param = str(r.get("param") or "")
        item = items_meta.get(id_)
        manual_unit = manual.get(param)
        basis = (item or {}).get("basis", "")

        if any(s == "missing" for s in states):
            note(id_, verdict="不计", note="缺采，整行不计价")
            continue  # 不计 comparable（与 JS 一致）
        for k in range(1, n_cols):
            cols[k]["comparable"] += 1

        # 行级是否有任何差异（语义口径：_row_sig，非原始字符串——审查 P1-2）
        has_diff = len(_row_sig(states, cells)) > 1

        # 清单外项（excluded.ids）：参与比较不计价（carkit '/' 语义；补项 K1 激光雷达等）
        if id_ in excluded_ids:
            note(id_, verdict="不计", note="清单外项，不计价")
            continue

        # 手填价：整行退化为"单价×(有无/数值差)"的旧口径（与看板手填语义一致）
        if manual_unit is not None:
            manual_unit = float(manual_unit)
            row_amounts: list[float | None] = [None] * n_cols
            counted = False
            for k in range(1, n_cols):
                s0, sk = states[0], states[k]
                if s0 != sk:
                    delta = (1 if sk == "present" else 0) - (1 if s0 == "present" else 0)
                elif s0 == "present":
                    v0 = _extract_num(cells[0], (item or {}).get("num_pattern"))
                    vk = _extract_num(cells[k], (item or {}).get("num_pattern"))
                    if v0 is None or vk is None or v0 == vk:
                        continue
                    delta = vk - v0
                else:
                    continue
                cols[k]["total_n"] += 1
                cols[k]["priced_n"] += 1
                cols[k]["amount"] += manual_unit * delta
                row_amounts[k] = manual_unit * delta
                counted = True
            if not counted and has_diff:
                note(id_, verdict="不计", note="手填单价下无数值/有无差可计",
                     unit_price=manual_unit, price_source="manual", basis=basis)
            else:
                v1 = row_amounts[1] if n_cols == 2 else None
                vrd = ("同" if not counted else
                       ("多" if (v1 or 0) > 0 else ("少" if (v1 or 0) < 0 else "同"))) \
                    if n_cols == 2 else "不计"
                note(id_, verdict=vrd,
                     amount=v1, unit_price=manual_unit, price_source="manual", basis=basis,
                     note="手填覆盖（仅当次对比内存态）" if counted else "")
            continue

        if item is None:
            # 无规则项：有差异 → missing（不脑补，照 carkit）；无差异 → 同
            if has_diff:
                missing_rules.append(id_)
                note(id_, verdict="待定价", note="差价表无此项目规则")
            else:
                note(id_, verdict="同", note="")
            continue

        pricing = item.get("pricing")
        unit_price = None
        try:
            if pricing == "flat":
                unit_price = float(item["val"])
            elif pricing == "per_unit":
                unit_price = float(item["unit_price"])
        except (KeyError, TypeError, ValueError):
            # 规则字段缺失与未知 pricing 同命运：missing fail-closed（审查 P2-4）
            missing_rules.append(id_)
            note(id_, verdict="待定价", basis=basis, note="规则字段缺失")
            continue

        row_amounts: list[float | None] = [None] * n_cols
        row_units: list[tuple[float | None, str]] = [(None, "none")] * n_cols
        row_missing = False
        counted = False
        for k in range(1, n_cols):
            s0, sk = states[0], states[k]
            c = cols[k]
            if pricing == "flat":
                if s0 != sk:
                    delta = (1 if sk == "present" else 0) - (1 if s0 == "present" else 0)
                    c["total_n"] += 1
                    c["priced_n"] += 1
                    c["amount"] += unit_price * delta
                    row_amounts[k] = unit_price * delta
                    row_units[k] = (unit_price, "table")
                    counted = True
                # 双方都具备的文本差异：flat 无档位 → 不计价（不计 total_n，同 JS 语义）
            elif pricing == "per_unit":
                if s0 != sk:
                    delta = (1 if sk == "present" else 0) - (1 if s0 == "present" else 0)
                    c["total_n"] += 1
                    c["priced_n"] += 1
                    c["amount"] += unit_price * delta
                    row_amounts[k] = unit_price * delta
                    row_units[k] = (unit_price, "table")
                    counted = True
                elif s0 == "present":
                    v0 = _item_num(cells[0], item)
                    vk = _item_num(cells[k], item)
                    if v0 is None or vk is None or v0 == vk:
                        continue
                    c["total_n"] += 1
                    c["priced_n"] += 1
                    c["amount"] += unit_price * (vk - v0)
                    row_amounts[k] = unit_price * (vk - v0)
                    row_units[k] = (unit_price, "table")
                    counted = True
            elif pricing == "band":
                if s0 == "absent" and sk == "absent":
                    continue
                ok0, val0 = (True, 0.0) if s0 == "absent" else _band_value(cells[0], item)
                okk, valk = (True, 0.0) if sk == "absent" else _band_value(cells[k], item)
                if not ok0 or not okk:
                    row_missing = True
                    continue
                if valk == val0:
                    continue  # 落档相减为 0（含 0 元档 vs 无）即非差异（对齐 carkit 0−0=同）
                c["total_n"] += 1
                c["priced_n"] += 1
                c["amount"] += valk - val0
                row_amounts[k] = valk - val0
                row_units[k] = (None, "table")
                counted = True
            elif pricing == "threshold":
                try:
                    thr = float(item["threshold"])
                    tprice = float(item["price"])
                except (KeyError, TypeError, ValueError):
                    row_missing = True  # 字段缺失 fail-closed（审查 P2-4）
                    continue
                if s0 != sk:
                    delta = (1 if sk == "present" else 0) - (1 if s0 == "present" else 0)
                    c["total_n"] += 1
                    c["priced_n"] += 1
                    c["amount"] += tprice * delta
                    row_amounts[k] = tprice * delta
                    row_units[k] = (None, "table")
                    counted = True
                elif s0 == "present":
                    v0 = _item_num(cells[0], item)
                    vk = _item_num(cells[k], item)
                    if v0 is None or vk is None or v0 == vk:
                        continue
                    if abs(vk - v0) < thr:
                        continue
                    c["total_n"] += 1
                    c["priced_n"] += 1
                    c["amount"] += (tprice if vk > v0 else -tprice)
                    row_amounts[k] = tprice if vk > v0 else -tprice
                    row_units[k] = (None, "table")
                    counted = True
            else:
                # 未知 pricing 类型 → fail-closed
                row_missing = True

        if row_missing:
            missing_rules.append(id_)
            note(id_, verdict="待定价", basis=basis, note="落不了档/规则缺失")
            continue
        if n_cols == 2:
            amt = row_amounts[1]
            if counted and amt:
                note(id_, verdict=("多" if amt > 0 else "少"), amount=amt,
                     unit_price=row_units[1][0], price_source=row_units[1][1],
                     basis=basis, note="")
            else:
                same_all = len(_row_sig(states, cells)) == 1
                note(id_, verdict="同" if same_all else "不计", amount=None,
                     unit_price=unit_price, price_source="table" if unit_price else "none",
                     basis=basis, note="" if same_all else "文本差异不计价")
        else:
            # 多列：行级判定塌陷为不计，但金额随行下发（审查 P2-2 缓解）
            note(id_, verdict="不计", basis=basis,
                 amounts=[round(a, 2) if a is not None else None for a in row_amounts])

    blocked = bool(missing_rules)
    for k in range(1, n_cols):
        c = cols[k]
        if blocked:
            c["amount"] = None
            c["available"], c["text"] = _col_text(
                k, 0, c["total_n"], c["priced_n"], c["comparable"], len(missing_rules))
        else:
            c["available"], c["text"] = _col_text(
                k, c["amount"], c["total_n"], c["priced_n"], c["comparable"], 0)
    # 不可用列（comparable==0）不出 config_adv——"差价值不可用"不能被当 0（审查 P1-1）
    config_adv = (cols[1]["amount"]
                  if (n_cols == 2 and not blocked and cols[1]["available"]) else None)
    return {"columns": cols, "items": diff_items, "missing_rules": missing_rules,
            "blocked": blocked, "config_adv": config_adv, "flat_adv": None,
            "legacy": False}
