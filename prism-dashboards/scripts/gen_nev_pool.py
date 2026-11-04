#!/usr/bin/env python3
"""新能源车池名单生成器 + autohome series_id 绑定器（T1，change「新能源车池采集」）。

从 sales_trim 程序化生成 25 万以下在售新能源 SUV/三厢/MPV 车池名单并绑定汽车之家
series_id（红线#6：禁止人工转写名称、禁止子串静默绑定）。

口径（上游方案《Prism-Agent-新能源车池扩容方案-v1》§3.1）：
- 窗口 = 库内最新 3 个「有零售」的月末批（month LIKE '%月末' 按年+月倒序取前三；
  零售全空的属性批——如 CAM 月末批已导入但零售未落——跳过并记录在 window 里，
  防止窗口退化成 2 个月、3000 深采门槛失真；完全动态，无硬编码年月）
- 行过滤：retail > 0 且 prod_status='在产'；body 含 SUV/三厢/MPV（映射 SUV/SD/MPV）；
  energy_type 含子串 纯电/插电/增程/燃料电池（库实际值='纯电动'/'插电式混合'/'增程式混合'）
- 车系聚合：中位数(msrp) ≤ 250000（中位数对窗口内合格行计算）
- 双断言（不过 fail-closed 不出文件）：
  ① 能源构成：纯电/插混/增程三类计数均 >0 且各桶合计=盘子数（§3.2 勘误防线）
  ② 盘子数环比：对上一份 nev_pool.json（读旧件，写新件前旧件转 .prev），
     |Δ|>10% 拦截；--force 豁免并在输出注明；首次生成（无旧件）跳过并注明
- tier：existing=本地口碑(owner_reviews.model_id 计数)≥100；deep=本地<100 且窗口
  零售合计>3000；longtail=本地<100 且零售合计≤3000；未绑定项 tier 置空不进计数
- ID 绑定：build_series_index() 精确名匹配（去空格+casefold，含 品牌名+车系名 形态）
  优先 → 未命中走规则化绑定（T1b）：rule_alias（显式转写对 ALIAS_PAIRS + 品牌/希腊
  字母/前缀变体）→ rule_merged_shell（去动力后缀基名精确命中，动力分壳兄弟壳歧义
  不自动绑）→ 未命中走 search_series(车系名) 兜底（调用间隔 ≥1s 限速）→ 仍歧义/
  未命中进 manual_review 清单，不做子串猜测绑定；所有阶段唯一命中还须过价带一致性
  守卫（CAM 中位价 ∉ 之家指导价带 → manual_review(price_mismatch) 并列同族候选，
  拦「同名不同壳」错绑，如 CAM'传祺E8'插电 vs 之家'传祺E8'燃油）；规则绑定的同壳
  共享以 shared_shell 字段披露（秦PLUS DM-i 与 秦PLUS EV 同绑一 id 互列兄弟），
  exact/search 的同 id 冲突仍全员降级 manual_review
- 缓存：绑定结果写进 nev_pool.json；重跑对已 exact/search 绑定项直接复用（不逐项
  出网；索引仍拉取一次用于价带守卫复核，失检的缓存绑定价弃用重走绑定）
- --skip-binding：完全离线，不出网，绑定字段留空（tier 因此不判定）

对 autohome.db 只读（sqlite uri mode=ro 打开）；只写 json 输出，不写库。

用法（运行目录=prism-dashboards）：
    python scripts/gen_nev_pool.py --skip-binding     # 离线出名单，验证断言与计数
    python scripts/gen_nev_pool.py                    # 带绑定真实生成
    python scripts/gen_nev_pool.py --force            # 环比断言豁免（输出留痕）

可作模块导入（单测用）：build_pool / assert_energy_composition / assert_prev_delta /
assign_tiers / detect_shared_shells / bind_pool（注入 fake api，不出网）。
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sqlite3
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_DB = ROOT / "data" / "autohome.db"
DEFAULT_OUT = ROOT / "data" / "nev_pool.json"

WINDOW_SIZE = 3            # 窗口=最近 3 个月末批
PRICE_CAP = 250000.0       # 中位数(msrp) 上限
DEEP_RETAIL_MIN = 3000     # deep: 窗口零售合计 > 3000
EXISTING_MIN_LOCAL = 100   # existing: 本地口碑条数 >= 100
PREV_TOLERANCE = 0.10      # 盘子环比容忍带 ±10%
BIND_DELAY_S = 1.0         # search_series 兜底调用间隔（限速）

# body 子串 → 车型类别（顺序即优先级）
BODY_RULES = (("SUV", "SUV"), ("三厢", "SD"), ("MPV", "MPV"))
# energy_type 子串 → 能源桶（注意库值是 '纯电动'/'插电式混合'/'增程式混合'；
# 子串必须比库值短——§3.2 勘误的根因就是拿全词当子串用）
ENERGY_RULES = (("纯电", "纯电"), ("插电", "插混"), ("增程", "增程"),
                ("燃料电池", "燃料电池"))
ENERGY_THREE = ("纯电", "插混", "增程")  # 断言①的三类

SERIES_KEYS = ("sales_name", "body_cat", "retail_3m", "msrp_p50", "energy_type",
               "tier", "series_id", "binding", "manufacturer", "level",
               "local_review_count", "source_review_count",
               "shared_shell", "binding_evidence")

# 判定为「已绑定」的 binding 取值（规则绑定与 exact/search 同权参与 tier/口碑计数；
# 共壳检测 detect_shared_shells 仍只看 exact/search——规则绑定的同壳共享是刻意的，
# 用 shared_shell 字段披露而非降级）
BOUND_KINDS = ("exact", "search", "rule_merged_shell", "rule_alias")

# 编码守卫：GBK 控制台下中文 print 会 UnicodeEncodeError（同 recollect 脚本形态）
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ---------- 基础分类 ----------

def classify_body(body: str | None) -> str | None:
    """body 含 SUV/三厢/MPV → SUV/SD/MPV；其余（两厢/掀背/跑车…）→ None。"""
    if not body:
        return None
    for sub, cat in BODY_RULES:
        if sub in body:
            return cat
    return None


def classify_energy(energy_type: str | None) -> str | None:
    """energy_type 子串匹配 → 纯电/插混/增程/燃料电池；传统能源/油电混合等 → None。"""
    if not energy_type:
        return None
    for sub, bucket in ENERGY_RULES:
        if sub in energy_type:
            return bucket
    return None


def norm_name(s: str | None) -> str:
    """精确名比对归一：去全部空白 + casefold（不做任何子串猜测）。"""
    return re.sub(r"\s+", "", str(s or "")).casefold()


# ---------- 规则化绑定词表（T1b；只收本轮 manual_review 实际出现形态，不预猜全量） ----------
# CAM 侧动力后缀词表（casefold 存放）。两个用途：①not_found 项的 shell_hint 线索；
# ②规则1（合并壳）：去后缀基名与之家索引精确命中。后缀形态来源=2026-10-16 轮
# manual_review 165 项 not_found 实测：空格形（秦PLUS DM-i / 海豹06 EV / 坦克300 Hi4-T /
# 问界M5 EVR / smart精灵#5 EHD / 大家7 DMH / 魏牌 摩卡 DHT PHEV / 途观L ePro）+
# 粘着形（唐DM-i / 汉EV / 帕萨特ePro / 启辰大V DD-i超混动）。
_POWERTRAIN_TOKENS = {"ev", "bev", "dm-i", "dm-p", "dm", "phev", "em-i", "em-p",
                      "idd", "c-dm", "cem", "纯电", "纯电动", "增程", "插混", "混动",
                      "reev", "evr", "ehd", "dmh", "dht", "hi4", "hi4-t",
                      "epro", "e:phev"}
# 粘着形剥离表（长词优先；按 endswith 匹配）：唐DM-i→唐、汉EV→汉、帕萨特ePro→帕萨特、
# 秦PLUS→不受影响；「超混动」对应 启辰大V DD-i超混动→启辰大V DD-i
_POWERTRAIN_ATTACHED = ("Hi4-T", "Hi4", "DM-i", "DM-p", "PHEV", "REEV", "EVR",
                        "EM-i", "EM-P", "EHD", "DMH", "iDD", "C-DM", "CEM",
                        "BEV", "EV", "DM", "DHT", "超混动", "纯电", "增程",
                        "插混", "混动", "ePro")
# 之家按动力分壳时的壳名尾巴：base 精确命中之外若存在「base+尾巴」兄弟壳，
# 说明 之家 侧同名义拆了动力壳（宋Pro/宋Pro新能源、途观L/途观L插电混动），
# 去后缀 CAM 项绑到哪个壳有歧义 → 拦下进人工（除非转写表显式指定）
_NEV_TWIN_TAILS = frozenset({"新能源", "插电混动", "phev", "ev", "dm-i", "dmh",
                             "增程", "纯电", "智电idd"})

# 品牌/名称转写（本轮 manual_review 实际出现的品牌形态，逐条注明证据）：
BRAND_TOKEN_ALIAS = (
    ("昊铂Hyper", "昊铂"),    # 之家壳名不带 Hyper：昊铂GT 7084/昊铂HT 7395/昊铂A800 8246
    ("ARCFOX", "极狐"),       # 之家 brand=ARCFOX极狐，壳名=极狐 阿尔法S5(7327)/贝塔S3(8190)
    ("埃安", "AION"),         # 之家壳名用 AION：AION Y 5976/AION RT 7860/AION V 5622…
    ("Honda", "本田"),        # 广汽Honda P7 → 之家 广汽本田P7(7677)
)
# 希腊字母 → 之家中文形态（极狐系：α→阿尔法、β→贝塔；本轮仅 α/β 出现）
GREEK_LETTER_ALIAS = (("α", "阿尔法"), ("β", "贝塔"))
# CAM 名带集团/品牌前缀而之家壳名不带：风行星海V9→星海V9(7400)、五菱星光L→星光L(8468)、
# 宝骏华境S→华境S(8283)
CAM_PREFIX_STRIP = ("风行", "五菱", "宝骏")
# 之家壳名带品牌前缀而 CAM 名不带：北京越野BJ40增程←BJ40增程(7696)、
# 东风风神L7←风神L7(7323)、长安启源Q05←启源Q05(8241)、别克至境E7←至境E7(8510)、
# 极狐 考拉S←考拉S(7797)、福特智趣烈马←智趣烈马(8213)、风行雷霆←雷霆(6633)
INDEX_PREFIX_STRIP = ("北京越野", "东风", "长安", "别克", "极狐", "福特", "风行")
# 大众 ID. 系列：之家立壳不带 ID. 前缀（ID.与众06→与众06 7628 / ID.与众08→与众08 8429）
ID_DOT_PREFIX = "ID."

# 全名显式转写对：CAM sales_name → 之家壳名（键按归一名匹配；值在绑定阶段对索引
# 精确解析，解析不到即该对失效不绑）。只收本轮 manual_review 实际形态，逐条注明依据：
ALIAS_PAIRS = {
    # —— 本田 e:PHEV 命名 vs 之家「新能源」壳 ——
    "本田 CR-V e:PHEV": "本田CR-V新能源",        # 5892（22.59-26.99万）
    "皓影 e:PHEV": "皓影新能源",                  # 5994（22.59-26.99万）
    "雅阁 e:PHEV": "雅阁新能源",                  # 7127（无价带）
    # —— 大众 ePro 命名 vs 之家「插电混动」壳（燃油壳同名并存，故须显式指定）——
    "帕萨特ePro": "帕萨特插电混动",               # 4904（21.59-25.59万）
    "途观L ePro": "途观L插电混动",                # 4746（19.19-20.79万）
    # —— 之家同名义按动力分双壳：CAM NEV 项对应新能源/插电混动壳 ——
    "魏牌 摩卡 DHT PHEV": "魏牌 摩卡新能源",      # 6011（燃油壳 摩卡 并存）
    "领裕 PHEV": "领裕新能源",                    # 7743
    "领睿 PHEV": "领睿新能源",                    # 7744
    "大通 G50 混动": "大通G50插电混动",           # 7924
    "哈弗大狗PLUS PHEV": "哈弗大狗 PLUS 新能源",  # 6900
    "五菱星光560 EV": "星光560新能源",            # 8216（燃油壳 星光560 8217 并存）
    "五菱星光560 PHEV": "星光560新能源",          # 同上（价带守卫兜底）
    "五菱星光730 EV": "星光730新能源",            # 8187（燃油壳 星光730 8188 并存）
    "五菱星光730 PHEV": "星光730新能源",          # 同上（价带守卫兜底）
    "欧尚Z6 iDD": "长安欧尚Z6新能源",             # 6670
    "凯翼昆仑 iHD": "凯翼昆仑新能源",             # 7077
    "哈弗猛龙": "哈弗猛龙新能源",                 # 7298（燃油壳 哈弗猛龙燃油 7746 并存）
    "坦克300L Hi4-T": "坦克300L新能源",           # 8723
    "锐胜M8 纯电": "锐胜M8新能源",                # 8214
    "锐胜M8 增程": "锐胜M8新能源",                # 同上（共壳，shared_shell 披露）
    "荣威 iMAX8 DMH": "荣威iMAX8新能源",          # 6641
    "比亚迪 唐DM-i": "唐新能源",                  # 3430（壳 唐 4802 并存）
    "比亚迪 宋Pro DM-i": "宋Pro新能源",           # 5279（壳 宋Pro 5178 并存）
    "长安 UNI-K iDD": "长安UNI-K 智电iDD",        # 6264
    "长安 UNI-Z iDD": "长安UNI-Z新能源",          # 7512
    # —— 后缀/车系名差异 ——
    "银河A7 EM-i": "银河A7 EM",                   # 8158（EV 壳 8666 独立）
    "iCAR V23": "iCAR 超级V23",                   # 7649（V23皮卡 8114 非同类）
    "捷途旅行者 PLUS C-DM": "捷途旅行者C-DM",     # 7345（燃油壳 捷途旅行者 6606 并存）
    "瑞风M3 PLUS PHEV": "瑞风M3 PHEV",            # 7930
    "e:NS2 猎光": "猎光e:NS2",                    # 7244（词序相反）
    "哈弗猛龙 Plus": "长城猛龙 PLUS",             # 8545（之家用长城猛龙 PLUS 命名）
    "银河星耀7 MAX": "银河星耀7",                 # 8313（MAX=壳内版本命名，价带守卫兜底）
    "埃安 Y Plus": "AION Y",                      # 5976（Plus 为壳内版本命名）
}
ALIAS_PAIRS_NORM = {norm_name(k): v for k, v in ALIAS_PAIRS.items()}


def strip_powertrain_tokens(name: str, max_strips: int = 3) -> str:
    """去掉尾部动力后缀 token（按空白分词，逐个剥离）。"""
    tokens = str(name or "").split()
    stripped = 0
    while tokens and stripped < max_strips:
        if tokens[-1].casefold() in _POWERTRAIN_TOKENS:
            tokens.pop()
            stripped += 1
        else:
            break
    return " ".join(tokens).strip()


def strip_powertrain_attached(name: str, max_strips: int = 1) -> str:
    """去掉最后 token 尾部粘着的动力后缀（唐DM-i→唐、帕萨特ePro→帕萨特）。

    与 strip_powertrain_tokens 串联使用：先剥整 token 再剥粘着尾巴。
    剥完剩纯符号（如 'e:'）视为剥离失败回退，防止产生垃圾基名。
    """
    tokens = str(name or "").split()
    stripped = 0
    while tokens and stripped < max_strips:
        last = tokens[-1]
        hit = None
        for suf in _POWERTRAIN_ATTACHED:
            if last.endswith(suf) and len(last) > len(suf):
                cand = last[:-len(suf)]
                # 剥完须仍含字母数字/汉字（'e:PHEV'→'e:' 这类纯符号视为剥离失败）
                if re.search(r"[0-9A-Za-z一-鿿]", cand):
                    hit = cand
                    break
        if hit is None:
            break
        tokens[-1] = hit
        stripped += 1
    return " ".join(tokens).strip()


def strip_powertrain_all(name: str) -> str:
    """规则1 基名：整 token 后缀 + 粘着后缀 都剥净。"""
    return strip_powertrain_attached(strip_powertrain_tokens(name))


def apply_text_alias(name: str) -> str:
    """品牌/希腊字母转写（规则2 变体之一）：ARCFOX αS5 → 极狐 阿尔法S5。"""
    out = str(name or "")
    for a, b in BRAND_TOKEN_ALIAS:
        out = out.replace(a, b)
    for a, b in GREEK_LETTER_ALIAS:
        out = out.replace(a, b)
    return out


def _month_num(month: str) -> int:
    """'8月末' → 8；异常形态排最前（sort 时视为最旧）。"""
    try:
        return int(str(month).replace("月末", "").strip())
    except ValueError:
        return 0


# ---------- 库读取（只读） ----------

def open_db_ro(db_path: str | Path) -> sqlite3.Connection:
    """只读打开 autohome.db（uri mode=ro，绝不写库）。"""
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"库不存在: {path}")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def latest_retail_window(conn: sqlite3.Connection, size: int = WINDOW_SIZE) -> dict:
    """最新 size 个「有零售」的月末批。零售全空的属性批跳过并记录（动态，无硬编码年月）。"""
    rows = conn.execute(
        "SELECT year, month, SUM(CASE WHEN retail IS NOT NULL AND retail > 0 "
        "THEN 1 ELSE 0 END) AS retail_rows "
        "FROM sales_trim WHERE month LIKE '%月末' GROUP BY year, month").fetchall()
    batches = sorted(((r["year"], r["month"], r["retail_rows"] or 0) for r in rows),
                     key=lambda b: (b[0], _month_num(b[1])), reverse=True)
    picked: list[tuple[int, str]] = []
    skipped: list[dict] = []
    for year, month, retail_rows in batches:
        if len(picked) >= size:
            break
        if retail_rows <= 0:
            skipped.append({"year": year, "month": month, "reason": "retail_all_empty"})
            continue
        picked.append((year, month))
    if len(picked) < size:
        raise RuntimeError(f"库内有零售的月末批不足 {size} 个：picked={picked}")
    picked_oldest_first = list(reversed(picked))
    return {
        "year": picked[0][0],
        "months": [m for _, m in picked_oldest_first],
        "batches": [{"year": y, "month": m} for y, m in picked_oldest_first],
        "skipped_empty_retail": skipped,
    }


def load_window_rows(conn: sqlite3.Connection, window: dict) -> list[dict]:
    """取窗口内全部 sales_trim 行（含零售空行——行过滤在 build_pool 做并计数）。"""
    conds, params = [], []
    for b in window["batches"]:
        conds.append("(year = ? AND month = ?)")
        params += [b["year"], b["month"]]
    sql = ("SELECT series, year, month, body, energy_type, retail, msrp, "
           "manufacturer, level, prod_status FROM sales_trim WHERE " + " OR ".join(conds))
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def local_review_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """owner_reviews.model_id（=车系 id）→ 本地口碑条数。"""
    return {r[0]: r[1] for r in conn.execute(
        "SELECT model_id, COUNT(*) FROM owner_reviews GROUP BY model_id")}


def source_review_counts(conn: sqlite3.Connection, series_ids: list[str]) -> dict[str, int]:
    """series_summaries.review_count（源站口碑量壳表值，§附A 同源）。分批 IN 查询。"""
    out: dict[str, int] = {}
    ids = list(series_ids)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = ("SELECT series_id, review_count FROM series_summaries "
             "WHERE series_id IN (%s)" % ",".join("?" * len(chunk)))
        out.update({r[0]: r[1] for r in conn.execute(q, chunk).fetchall()})
    return out


# ---------- 名单构建（纯函数，可单测） ----------

def build_pool(rows: list[dict]) -> tuple[list[dict], dict]:
    """§3.1 过滤 + 按车系聚合。返回 (entries, stats)。

    entry 字段与输出 schema 对齐（tier/绑定类字段初始为空）。
    """
    groups: dict[str, list[dict]] = {}
    stats = {"rows_in_window": len(rows), "rows_dropped_not_onsale": 0,
             "rows_dropped_no_retail": 0, "rows_dropped_body": 0,
             "rows_dropped_energy": 0, "rows_kept": 0,
             "dropped_over_price": 0, "dropped_no_msrp": []}
    for r in rows:
        if r.get("prod_status") != "在产":
            stats["rows_dropped_not_onsale"] += 1
            continue
        retail = r.get("retail")
        if retail is None or retail <= 0:
            stats["rows_dropped_no_retail"] += 1
            continue
        bcat = classify_body(r.get("body"))
        if bcat is None:
            stats["rows_dropped_body"] += 1
            continue
        ecat = classify_energy(r.get("energy_type"))
        if ecat is None:
            stats["rows_dropped_energy"] += 1
            continue
        stats["rows_kept"] += 1
        rr = dict(r)
        rr["_bcat"] = bcat
        rr["_ecat"] = ecat
        groups.setdefault(r["series"], []).append(rr)

    def _recency(row: dict) -> tuple[int, int]:
        return (row["year"], _month_num(row["month"]))

    entries: list[dict] = []
    for name, rs in groups.items():
        msrps = [r["msrp"] for r in rs if r.get("msrp") is not None]
        if not msrps:
            stats["dropped_no_msrp"].append(name)
            continue
        p50 = statistics.median(msrps)
        if p50 > PRICE_CAP:
            stats["dropped_over_price"] += 1
            continue
        rs_sorted = sorted(rs, key=_recency, reverse=True)
        meta: dict[str, str] = {}
        for f in ("manufacturer", "energy_type", "level"):
            meta[f] = next((r.get(f) or "" for r in rs_sorted if r.get(f)), "")
        entries.append({
            "sales_name": name,
            "body_cat": rs_sorted[0]["_bcat"],
            "retail_3m": int(sum(r["retail"] for r in rs)),
            "msrp_p50": round(float(p50), 2),
            "energy_type": meta["energy_type"],
            "tier": None,
            "series_id": None,
            "binding": None,
            "manufacturer": meta["manufacturer"],
            "level": meta["level"],
            "local_review_count": None,
            "source_review_count": None,
        })
    stats["dropped_no_msrp"] = sorted(stats["dropped_no_msrp"])
    return entries, stats


# ---------- 断言 ----------

def assert_energy_composition(pool: list[dict]) -> dict:
    """断言①：三类（纯电/插混/增程）计数均>0 且各桶合计=盘子数（§3.2 勘误防线）。"""
    buckets: dict[str, int] = {}
    for e in pool:
        b = classify_energy(e.get("energy_type")) or "未分类"
        buckets[b] = buckets.get(b, 0) + 1
    three_pos = all(buckets.get(k, 0) > 0 for k in ENERGY_THREE)
    classified = sum(v for k, v in buckets.items() if k != "未分类")
    sum_eq = bool(pool) and classified == len(pool)
    return {"universe": len(pool), "buckets": buckets,
            "three_categories_positive": three_pos,
            "sum_equals_universe": sum_eq,
            "passed": bool(three_pos and sum_eq)}


def assert_prev_delta(new_total: int, prev_total: int | None, force: bool = False,
                      prev_status: str = "ok",
                      tolerance: float = PREV_TOLERANCE) -> dict:
    """断言②：盘子数环比 |Δ|≤10%；--force 豁免留痕；首生成/旧件不可读 → 跳过并注明。"""
    a: dict = {"prev_total": prev_total, "new_total": new_total,
               "tolerance": tolerance, "forced": bool(force)}
    if prev_status != "ok" or prev_total is None:
        a.update({"passed": True, "skipped": prev_status})
        return a
    delta_pct = abs(new_total - prev_total) / prev_total if prev_total else 0.0
    passed = bool(force or delta_pct <= tolerance)
    a.update({"delta_pct": round(delta_pct, 4), "passed": passed})
    return a


# ---------- ID 绑定（红线#6：禁止子串静默绑定） ----------

def load_prev_doc(out_path: Path) -> tuple[dict | None, str]:
    """读上一份名单用于环比基线与绑定缓存：优先 nev_pool.json（最近一次），
    其次 .prev。返回 (doc, status)；status ∈ ok/no_prev/prev_unreadable。"""
    for p in (out_path, Path(str(out_path) + ".prev")):
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f), "ok"
            except Exception as ex:
                print(f"WARN: 上一份名单 {p.name} 读取失败({ex})，按首次生成处理环比")
                return None, "prev_unreadable"
    return None, "no_prev"


def parse_price_range(s) -> tuple[float, float] | None:
    """之家价带 '17.98-17.98万' / '9.88-25.98万' → (lo, hi) 元；解析不了 → None。"""
    m = re.match(r"^([\d.]+)(?:-([\d.]+))?万$", str(s or "").strip())
    if not m:
        return None
    lo = float(m.group(1)) * 10000
    hi = float(m.group(2) or m.group(1)) * 10000
    return lo, hi


def price_consistent(entry: dict, index_row: dict | None) -> bool:
    """绑定质量守卫：CAM 窗口中位价 vs 之家指导价带（缺价带/缺价 → 放行）。

    拦的是「同名不同壳」错绑（如 CAM'传祺E8'插电 vs 之家'传祺E8'燃油）与
    价格口径明显相悖的绑定；不一致 → 降级 manual_review，不做自动换绑。
    """
    r = parse_price_range((index_row or {}).get("price_range"))
    if r is None:
        return True
    p50 = entry.get("msrp_p50")
    if p50 is None:
        return True
    lo, hi = r
    return lo <= p50 <= hi


def load_binding_cache(prev_doc: dict | None) -> dict[str, dict]:
    """上一份名单里的 exact/search 绑定结果 → 缓存（键=归一 sales 名）。"""
    cache: dict[str, dict] = {}
    for e in (prev_doc or {}).get("series", []):
        if e.get("binding") in ("exact", "search") and e.get("series_id"):
            cache[norm_name(e.get("sales_name"))] = {
                "series_id": e["series_id"],
                "binding": e["binding"],
                "source_review_count": e.get("source_review_count"),
            }
    return cache


async def bind_pool(pool: list[dict], cache: dict[str, dict], api,
                    delay: float = BIND_DELAY_S) -> dict:
    """exact（索引精确名）→ rule_alias（显式转写）→ rule_merged_shell（合并壳）→
    search_series 兜底 → manual_review。原地写 entry 字段。

    api 需提供 async build_series_index() -> {sid: {name, brand_name, price_range, ...}}
    和 async search_series(keyword) -> [{series_id, name, brand_name}, ...]。
    单测注入 fake api，不出网。

    绑定质量守卫：所有阶段（含缓存复用与两条规则）唯一命中均须过价带一致性
    （price_consistent），不过 → 降级 manual_review(price_mismatch) 并列候选；
    规则绑定额外证据写 entry['_binding_evidence']，同壳共享写 'shared_shell'。
    规则1（rule_merged_shell）：CAM 名去动力后缀（strip_powertrain_all）→ 基名与之家
    索引精确命中；命中多条、或存在动力分壳兄弟壳（_NEV_TWIN_TAILS）、或价带不符
    → 不自动绑。
    规则2（rule_alias）：ALIAS_PAIRS 显式转写对 + 品牌/希腊字母/前缀变体，命中唯一
    且无兄弟壳歧义、价带过检才绑。
    """
    stats = {"reused": 0, "exact": 0, "search": 0, "manual_review": 0}
    by_name: dict[str, set] = {}
    by_brand_name: dict[str, set] = {}
    by_idx_prefix: dict[str, set] = {}
    index_rows: dict[str, dict] = {}

    def _family_candidates(name_part: str, limit: int = 5) -> list[dict]:
        """同族候选（仅人审线索）：之家壳名以给定名开头/相等的条目。"""
        np = norm_name(name_part)
        fam = [(sid, s) for sid, s in index_rows.items()
               if norm_name(s.get("name")) == np or norm_name(s.get("name")).startswith(np)]
        fam.sort(key=lambda t: t[0])
        return [{"series_id": sid, "name": s.get("name"), "brand_name": s.get("brand_name"),
                 "price_range": s.get("price_range")} for sid, s in fam[:limit]]

    # 阶段零：缓存复用（exact/search 才可信；复用项也要过价带守卫 → 需要索引）
    need_index = bool(cache or pool)
    pending: list[dict] = []
    if pool:
        if need_index:
            index = await api.build_series_index()
            for sid, s in index.items():
                index_rows[sid] = s
                by_name.setdefault(norm_name(s.get("name")), set()).add(sid)
                bn = norm_name(str(s.get("brand_name") or "") + str(s.get("name") or ""))
                by_brand_name.setdefault(bn, set()).add(sid)
            # 之家壳名带品牌前缀的反查形态（别克至境E7 → 至境E7）
            for sid, s in index_rows.items():
                nm_full = norm_name(s.get("name"))
                for p in INDEX_PREFIX_STRIP:
                    np_ = norm_name(p)
                    if len(nm_full) > len(np_) and nm_full.startswith(np_):
                        by_idx_prefix.setdefault(nm_full[len(np_):], set()).add(sid)
        for e in pool:
            c = cache.get(norm_name(e["sales_name"]))
            if (c and c.get("binding") in ("exact", "search") and c.get("series_id")):
                if not price_consistent(e, index_rows.get(c["series_id"])):
                    pending.append(e)  # 缓存绑定价带失检 → 弃缓存重走绑定
                    continue
                e["series_id"] = c["series_id"]
                e["binding"] = c["binding"]
                e["source_review_count"] = c.get("source_review_count")
                stats["reused"] += 1
            else:
                pending.append(e)

    def _lookup(variant: str) -> dict[str, dict]:
        nv = norm_name(variant)
        if not nv:
            return {}
        ids = (by_name.get(nv, set()) | by_brand_name.get(nv, set())
               | by_idx_prefix.get(nv, set()))
        return {sid: index_rows[sid] for sid in ids}

    def _nev_twins(variant: str) -> dict[str, dict]:
        """动力分壳兄弟壳：之家壳名 = 变体名 + 新能源/插电混动/… 尾巴。"""
        nv = norm_name(variant)
        if not nv:
            return {}
        out: dict[str, dict] = {}
        for sid, s in index_rows.items():
            nn = norm_name(s.get("name"))
            if len(nn) > len(nv) and nn.startswith(nv) and nn[len(nv):] in _NEV_TWIN_TAILS:
                out[sid] = s
        return out

    def _bind_rule(e: dict, kind: str, sid: str, variant: str) -> None:
        row = index_rows.get(sid) or {}
        e["series_id"] = sid
        e["binding"] = kind
        e["_binding_evidence"] = {
            "rule": kind,
            "base_or_variant": variant,
            "matched_name": row.get("name"),
            "matched_price_range": row.get("price_range"),
            "cam_msrp_p50": e.get("msrp_p50"),
        }

    def _manual(e: dict, reason: str, rows: dict[str, dict]) -> None:
        e["binding"] = "manual_review"
        e["_review_reason"] = reason
        e["_candidates"] = [{"series_id": h, "name": r.get("name"),
                             "brand_name": r.get("brand_name"),
                             "price_range": r.get("price_range")}
                            for h, r in sorted(rows.items())[:5]]

    def _rule_variants(e: dict) -> tuple[str | None, list[str]]:
        """规则2 候选变体（有序去重；只含文本变换形——纯基名归规则1）：
        显式对 → 基名/原名的 品牌转写/前缀剥离/ID.剥离。"""
        name = e["sales_name"]
        pair_target = ALIAS_PAIRS_NORM.get(norm_name(name))
        base = strip_powertrain_all(name)
        forms: list[str] = []
        for src in (base, name):
            forms.extend(_alias_variants(src))
        if pair_target:
            forms.insert(0, pair_target)
        seen: set[str] = set()
        ordered: list[str] = []
        for v in forms:
            if v and v != name and norm_name(v) not in seen:
                seen.add(norm_name(v))
                ordered.append(v)
        return pair_target, ordered

    def _try_rules(e: dict) -> bool:
        """规则2（rule_alias）→ 规则1（rule_merged_shell）。绑上或已降级 manual → True。"""
        name = e["sales_name"]
        base = strip_powertrain_all(name)
        # —— 规则2a：显式对 + 文本变换变体（之家索引名/品牌名+索引名/前缀反查全试）——
        pair_target, variants = _rule_variants(e)
        mismatch_rows: dict[str, dict] = {}
        for v in variants:
            hits = _lookup(v)
            twins = _nev_twins(v)
            if len(hits) == 1 and not twins:
                sid = next(iter(hits))
                if price_consistent(e, index_rows.get(sid)):
                    _bind_rule(e, "rule_alias", sid, v)
                    return True
                mismatch_rows.update({sid: index_rows[sid]})
            elif hits or twins:
                rows = dict(hits)
                rows.update(twins)
                _manual(e, "ambiguous_rule", rows)
                return True
        # —— 规则2b：纯形（原名/基名）只查「之家壳名带品牌前缀」反查表——
        # （纯形若走全量查找会与规则1 抢归属，如 秦PLUS DM-i→秦PLUS 应是 rule_merged_shell）
        for src in (name, base):
            if not src:
                continue
            ns = norm_name(src)
            if ns in {norm_name(name)} and src is not name:
                continue  # base 与原名同形时只试一次
            pref_ids = by_idx_prefix.get(ns, set())
            if len(pref_ids) == 1:
                sid = next(iter(pref_ids))
                twins = _nev_twins(src)
                if twins:
                    rows = {sid: index_rows[sid]}
                    rows.update(twins)
                    _manual(e, "ambiguous_rule", rows)
                    return True
                if price_consistent(e, index_rows.get(sid)):
                    _bind_rule(e, "rule_alias", sid, f"{src} (之家前缀剥离)")
                    return True
                mismatch_rows.update({sid: index_rows[sid]})
            elif len(pref_ids) > 1:
                _manual(e, "ambiguous_rule", {h: index_rows[h] for h in sorted(pref_ids)[:5]})
                return True
        if mismatch_rows:
            _manual(e, "price_mismatch", mismatch_rows)
            return True
        # —— 规则1：去动力后缀基名精确命中（纯索引名/品牌名+索引名形态）——
        if base and base != name:
            nb = norm_name(base)
            hit_ids = by_name.get(nb, set()) | by_brand_name.get(nb, set())
            twins = _nev_twins(base)
            if len(hit_ids) == 1 and not twins:
                sid = next(iter(hit_ids))
                if price_consistent(e, index_rows.get(sid)):
                    _bind_rule(e, "rule_merged_shell", sid, base)
                    return True
                _manual(e, "price_mismatch", {sid: index_rows[sid]})
                return True
            if len(hit_ids) > 1 or twins:
                rows = {h: index_rows[h] for h in hit_ids}
                rows.update(twins)
                _manual(e, "ambiguous_rule", rows)
                return True
        return False

    # 阶段一：build_series_index 精确名匹配（车系名 或 品牌名+车系名，归一后全等）
    still: list[dict] = []
    for e in pending:
        nm = norm_name(e["sales_name"])
        hits = by_name.get(nm, set()) | by_brand_name.get(nm, set())
        if len(hits) == 1:
            sid = next(iter(hits))
            if price_consistent(e, index_rows.get(sid)):
                e["series_id"] = sid
                e["binding"] = "exact"
                stats["exact"] += 1
                continue
            e["binding"] = "manual_review"
            e["_review_reason"] = "price_mismatch"
            e["_candidates"] = _family_candidates(e["sales_name"])
            stats["manual_review"] += 1
        elif len(hits) > 1:
            e["binding"] = "manual_review"
            e["_review_reason"] = "ambiguous_exact"
            e["_candidates"] = [{"series_id": h, "name": index_rows[h].get("name"),
                                 "price_range": index_rows[h].get("price_range")}
                                for h in sorted(hits)[:5]]
            stats["manual_review"] += 1
        else:
            still.append(e)
    pending = still

    # 阶段一点五：规则绑定（T1b：转写表 + 合并壳；不出网，纯索引匹配）
    pending = [e for e in pending if not _try_rules(e)]

    # 阶段二：search_series 兜底（每次调用间隔 ≥delay 秒；只认归一全等命中）
    for i, e in enumerate(pending):
        if i > 0 and delay > 0:
            await asyncio.sleep(delay)
        results = await api.search_series(e["sales_name"]) or []
        nm = norm_name(e["sales_name"])
        exact_hits = {r["series_id"] for r in results
                      if norm_name(r.get("name")) == nm
                      or norm_name(str(r.get("brand_name") or "") + str(r.get("name") or "")) == nm}
        if len(exact_hits) == 1:
            sid = next(iter(exact_hits))
            if price_consistent(e, index_rows.get(sid)):
                e["series_id"] = sid
                e["binding"] = "search"
                stats["search"] += 1
                continue
            e["binding"] = "manual_review"
            e["_review_reason"] = "price_mismatch"
            e["_candidates"] = _family_candidates(e["sales_name"])
            stats["manual_review"] += 1
        elif len(exact_hits) > 1:
            e["binding"] = "manual_review"
            e["_review_reason"] = "ambiguous_search"
            res_by_id: dict = {}
            for r in results:
                res_by_id.setdefault(r.get("series_id"), r)
            e["_candidates"] = [{"series_id": h,
                                 "name": (res_by_id.get(h) or index_rows.get(h) or {}).get("name"),
                                 "price_range": (res_by_id.get(h) or index_rows.get(h) or {}).get("price_range")}
                                for h in sorted(exact_hits)[:5]]
            stats["manual_review"] += 1
        else:
            e["binding"] = "manual_review"
            e["_review_reason"] = "not_found"
            e["_candidates"] = [{"series_id": r.get("series_id"), "name": r.get("name")}
                                for r in list(results)[:5]]
            # 人审线索（非绑定）：去动力后缀后的精确名命中——之家合并壳族定位用
            base = norm_name(strip_powertrain_tokens(e["sales_name"]))
            if base and base != nm:
                hint_ids = by_name.get(base, set()) | by_brand_name.get(base, set())
                e["_shell_hints"] = [{"series_id": h, "name": index_rows[h].get("name"),
                                      "brand_name": index_rows[h].get("brand_name"),
                                      "price_range": index_rows[h].get("price_range")}
                                     for h in sorted(hint_ids)[:5]]
            stats["manual_review"] += 1
    # 规则阶段的 manual 降级（ambiguous_rule/price_mismatch）统一并入计数，
    # 以 pool 终态为准（与 compute_totals 口径一致）
    stats["manual_review"] = sum(1 for e in pool if e.get("binding") == "manual_review")
    return stats


def _alias_variants(name: str) -> list[str]:
    """规则2 文本变体（有顺序）：品牌/希腊字母转写 → CAM 前缀剥离 → ID. 前缀剥离。
    每级变换叠加在上一级结果上（ARCFOX αS5：转写→极狐 阿尔法S5）。"""
    out: list[str] = []
    cur = str(name or "")
    aliased = apply_text_alias(cur)
    if aliased != cur:
        out.append(aliased)
        cur = aliased
    for p in CAM_PREFIX_STRIP:
        if cur.startswith(p) and len(cur) > len(p):
            out.append(cur[len(p):])
    if cur.startswith(ID_DOT_PREFIX) and len(cur) > len(ID_DOT_PREFIX):
        out.append(cur[len(ID_DOT_PREFIX):])
    return out


def detect_shared_shells(pool: list[dict]) -> list[dict]:
    """共壳检测：同一 series_id 被多个 sales 名绑定 → 全员降级 manual_review。"""
    by_sid: dict[str, list[dict]] = {}
    for e in pool:
        if e.get("binding") in ("exact", "search") and e.get("series_id"):
            by_sid.setdefault(e["series_id"], []).append(e)
    shells: list[dict] = []
    for sid, es in sorted(by_sid.items()):
        if len(es) > 1:
            names = sorted(e["sales_name"] for e in es)
            for e in es:
                e["binding"] = "manual_review"
                e["_review_reason"] = "shared_shell"
                e["_peers"] = names
            shells.append({"series_id": sid, "sales_names": names})
    return shells


# ---------- tier / 汇总 ----------

def attach_local_counts(conn: sqlite3.Connection, pool: list[dict]) -> None:
    counts = local_review_counts(conn)
    for e in pool:
        if e.get("binding") in BOUND_KINDS:
            e["local_review_count"] = counts.get(e["series_id"], 0)


def attach_source_counts(conn: sqlite3.Connection, pool: list[dict]) -> None:
    ids = [e["series_id"] for e in pool if e.get("binding") in BOUND_KINDS]
    counts = source_review_counts(conn, ids)
    for e in pool:
        if e.get("binding") in BOUND_KINDS:
            e["source_review_count"] = counts.get(e["series_id"])


def assign_tiers(pool: list[dict]) -> None:
    """existing=本地≥100；deep=本地<100 且零售>3000；longtail=其余。只判已绑定项。"""
    for e in pool:
        if e.get("binding") in BOUND_KINDS:
            lc = e.get("local_review_count") or 0
            e["tier"] = ("existing" if lc >= EXISTING_MIN_LOCAL
                         else "deep" if e["retail_3m"] > DEEP_RETAIL_MIN
                         else "longtail")


def attach_shared_shells(pool: list[dict]) -> None:
    """同壳共享披露（如 秦PLUS DM-i 与 秦PLUS EV 同绑 5964）：一 id 多 sales 名时
    互列兄弟名，不限 binding 类别（rule 绑定与 exact/search 绑定同壳同样列出——
    如 CAM'小鹏G6'exact 与'小鹏G6 增程'rule 同绑 7162）。

    exact/search 之间新出现的同 id 冲突仍由 detect_shared_shells 降级人审；
    规则绑定的同壳是刻意的合并壳语义，只披露不降级。
    """
    by_sid: dict[str, list[dict]] = {}
    for e in pool:
        if e.get("binding") in BOUND_KINDS and e.get("series_id"):
            by_sid.setdefault(e["series_id"], []).append(e)
    for es in by_sid.values():
        if len(es) < 2:
            continue
        names = sorted(x["sales_name"] for x in es)
        for x in es:
            x["shared_shell"] = [n for n in names if n != x["sales_name"]]


def compute_totals(pool: list[dict]) -> dict:
    tiers = {"deep": 0, "longtail": 0, "existing": 0}
    manual = unbound = 0
    for e in pool:
        if e.get("binding") == "manual_review":
            manual += 1
        elif e.get("binding") is None:
            unbound += 1
        if e.get("tier"):
            tiers[e["tier"]] += 1
    return {"universe": len(pool), **tiers,
            "manual_review": manual, "unbound": unbound}


def public_entry(e: dict) -> dict:
    out = {k: e.get(k) for k in SERIES_KEYS}
    if e.get("_binding_evidence") is not None:
        out["binding_evidence"] = e["_binding_evidence"]
    return out


def manual_review_list(pool: list[dict]) -> list[dict]:
    out = []
    for e in pool:
        if e.get("_review_reason"):
            out.append({
                "sales_name": e["sales_name"],
                "reason": e["_review_reason"],
                "retail_3m": e["retail_3m"],
                "tier_by_retail": ("deep" if e["retail_3m"] > DEEP_RETAIL_MIN else "longtail"),
                "series_id": e.get("series_id"),
                "candidates": e.get("_candidates") or [],
                "peers": e.get("_peers") or [],
                "shell_hints": e.get("_shell_hints") or [],
            })
    return out


def write_pool(out_path: Path, doc: dict) -> None:
    """断言全过才落盘：旧件先转 .prev（环比基线逐次滚动）。"""
    if out_path.exists():
        os.replace(str(out_path), str(out_path) + ".prev")
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 真实绑定入口（唯一出网点；单测不经过此处） ----------

async def _bind_with_real_api(pool: list[dict], cache: dict[str, dict],
                              delay: float) -> dict:
    from src.api.autohome_api import get_autohome_api, close_autohome_api
    api = await get_autohome_api()
    try:
        return await bind_pool(pool, cache, api, delay=delay)
    finally:
        await close_autohome_api()


# ---------- main ----------

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    import argparse
    p = argparse.ArgumentParser(description="新能源车池名单生成器 + ID 绑定器（T1）")
    p.add_argument("--skip-binding", action="store_true",
                   help="离线模式：不出网，绑定字段留空（tier 不判定）")
    p.add_argument("--force", action="store_true",
                   help="盘子环比断言豁免（输出 assertions.prev_delta.forced=true 留痕）")
    p.add_argument("--db", default=str(DEFAULT_DB), help="autohome.db 路径（只读）")
    p.add_argument("--output", default=str(DEFAULT_OUT), help="输出 json 路径")
    p.add_argument("--delay", type=float, default=BIND_DELAY_S,
                   help="search_series 兜底调用间隔秒数（限速，默认 1.0）")
    args = p.parse_args(argv)

    out_path = Path(args.output).resolve()
    conn = open_db_ro(args.db)

    window = latest_retail_window(conn)
    skipped_desc = [f"{b['year']}-{b['month']}" for b in window["skipped_empty_retail"]] or "无"
    print(f"窗口: {window['year']} {window['months']}（跳过零售空批: {skipped_desc}）")
    rows = load_window_rows(conn, window)
    pool, pool_stats = build_pool(rows)
    print(f"行过滤: 窗口 {pool_stats['rows_in_window']} 行 → 合格 {pool_stats['rows_kept']} 行"
          f"（非在产 {pool_stats['rows_dropped_not_onsale']} / 无零售 {pool_stats['rows_dropped_no_retail']}"
          f" / 车型 {pool_stats['rows_dropped_body']} / 能源 {pool_stats['rows_dropped_energy']}）")
    print(f"盘子: {len(pool)} 系（超价剔除 {pool_stats['dropped_over_price']}"
          f" / 无价剔除 {len(pool_stats['dropped_no_msrp'])}）")

    energy_assert = assert_energy_composition(pool)
    prev_doc, prev_status = load_prev_doc(out_path)
    prev_total = (prev_doc or {}).get("totals", {}).get("universe") if prev_doc else None
    prev_assert = assert_prev_delta(len(pool), prev_total, force=args.force,
                                    prev_status=prev_status)

    doc: dict = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "offline" if args.skip_binding else "bound",
        "window": window,
        "totals": {},
        "assertions": {"energy_composition": energy_assert, "prev_delta": prev_assert},
        "series": [],
        "manual_review": [],
    }

    if args.skip_binding:
        print("--skip-binding：离线模式，绑定字段留空，tier 不判定")
        totals = compute_totals(pool)
    else:
        cache = load_binding_cache(prev_doc)
        print(f"绑定: 缓存复用 {len(cache)} 项可用，"
              f"其余 {sum(1 for e in pool if not e.get('binding'))} 项走出网绑定…")
        stats = asyncio.run(_bind_with_real_api(pool, cache, args.delay))
        shells = detect_shared_shells(pool)
        attach_shared_shells(pool)
        attach_local_counts(conn, pool)
        attach_source_counts(conn, pool)
        assign_tiers(pool)
        totals = compute_totals(pool)
        kinds = Counter(e.get("binding") for e in pool)
        print(f"绑定结果: 复用 {stats['reused']} / exact {stats['exact']} / "
              f"search {stats['search']} / rule_merged_shell {kinds.get('rule_merged_shell', 0)} / "
              f"rule_alias {kinds.get('rule_alias', 0)} / manual_review {stats['manual_review']}")
        for sh in shells:
            print(f"  共壳降级: {sh['series_id']} ← {sh['sales_names']}")

    doc["totals"] = totals
    doc["series"] = [public_entry(e) for e in
                     sorted(pool, key=lambda e: (-e["retail_3m"], e["sales_name"]))]
    doc["manual_review"] = manual_review_list(pool)

    if not (energy_assert["passed"] and prev_assert["passed"]):
        print("ASSERT FAIL → fail-closed，不落盘")
        print(f"  能源构成: {json.dumps(energy_assert, ensure_ascii=False)}")
        print(f"  盘子环比: {json.dumps(prev_assert, ensure_ascii=False)}")
        return 2

    write_pool(out_path, doc)
    print(f"断言: 能源构成 pass={energy_assert['passed']} "
          f"{energy_assert['buckets']}；盘子环比 pass={prev_assert['passed']} "
          f"prev={prev_assert['prev_total']} Δ={prev_assert.get('delta_pct')}"
          f"{' (FORCED)' if prev_assert['forced'] else ''}")
    print(f"tier: deep={totals['deep']} longtail={totals['longtail']} "
          f"existing={totals['existing']} manual_review={totals['manual_review']}"
          f" unbound={totals['unbound']}")
    print(f"已写出: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
