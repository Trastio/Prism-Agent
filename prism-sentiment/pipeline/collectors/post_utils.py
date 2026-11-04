"""Post/comment dict 构造与清洗的共享工具。

2026-09-15 从 cdp_collector.py 抽出（CDP 退役清理）：TikHub/OneAPI collector
复用同一套 post/comment dict 契约，dealer 判定供 scheduler 入库过滤使用。
历史注释原样保留（中文日期分支与营销号模式均为实测定稿）。
"""

from __future__ import annotations

import html as _html
import re
from datetime import date as _date
from datetime import datetime, timedelta, timezone

from utils.config import env_int


# ── Defect keyword expansion (T1.1) ──────────────────────────────────────
# 缺陷帖采不到的根因：只搜车名返回评测/提车帖，"风云T7 仪表盘"类故障帖
# 搜不到。每车拼"车名+故障词"组合让缺陷帖被搜索命中。2026-09-28 T1
# 全量启用：12 个通用故障词全部组合（去 [:8] 截断），配合社媒
# max_keywords=13 让核心词 + 12 故障词全进搜索。brand 当前未用，保留参数
# 以便后续按品牌特化（电车多"续航/充电"、燃油车多"异响/生锈"）。
DEFECT_SEED_KEYWORDS = [
    "投诉", "故障", "缺陷", "问题", "质量", "售后",
    "维修", "退车", "召回", "异响", "卡死", "黑屏",
]

# 负面词表（2026-10-15 舆情降本 T2，方案 L1）：负面帖评论追加的预筛判据。
# 与 DEFECT_SEED_KEYWORDS 同源维护——缺陷词全集 + 4 个非缺陷类负面词
# （维权/自燃/起火/断裂）。选帖侧用它对标题/正文做 LIKE 预筛（采集时点
# GLM"负面"标签尚不存在，只能词表预筛——R28 拍板的机制），命中且不在
# top-N/缺陷词已选列表的帖，每平台取互动降序前 COMMENT_NEGATIVE_EXTRA_N
# 追加抓评论——topN 按互动排序会漏掉低互动的负面集中帖，而"帖子正面/
# 评论区翻车"正是舆情板核心洞察（不补则该能力安静退化）。
NEGATIVE_PRESET_WORDS = tuple(DEFECT_SEED_KEYWORDS) + ("维权", "自燃", "起火", "断裂")


def expand_defect_keywords(vehicle_name: str, brand: str = "") -> list[str]:
    """车名 + 故障词组合（每车 12 个），让缺陷帖被搜索命中。

    Returns ``["{车名} 投诉", "{车名} 故障", ...]`` 形式的组合词。
    主关键词（车名本身）不在其中——由调用方的主关键词列表提供，本函数
    只补缺陷维度。空车名返回 []。
    """
    if not vehicle_name:
        return []
    return [f"{vehicle_name} {w}" for w in DEFECT_SEED_KEYWORDS]


def strip_html(text: str | None) -> str | None:
    """剥 HTML 标签——微博 title 常含 <a href> 超话链接，入库前清洗。

    轻量正则实现。本函数是 _store_posts 入库前的统一安全网，对所有微博帖
    生效，防止任何上游路径漏剥污染热帖榜/词云。
    """
    if not text:
        return text
    return re.sub(r'<[^>]+>', '', text).strip()


def _safe_int(val, default: int = 0) -> int:
    """Coerce *val* to int; return *default* on failure or None."""
    try:
        return int(val or default)
    except (ValueError, TypeError):
        return default


def _ts_to_iso(ts) -> str:
    """Convert a Unix timestamp (seconds or ms) to ISO-8601 string.

    Returns an empty string when *ts* is falsy or unparseable.
    """
    if ts:
        try:
            val = int(ts)
            # > 1e12 → millisecond timestamp
            if val > 1e12:
                val = val // 1000
            return datetime.fromtimestamp(val, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
        except (ValueError, TypeError, OSError):
            pass
    return ""


def _parse_datetime(raw) -> str:
    """Parse any timestamp format into a clean ISO-8601 string.

    Handles Unix seconds/ms, ISO-8601, and Weibo's English format
    ("Sun Jun 29 10:00:00 +0800 2025"). Returns "" on any failure so
    callers never crash and posts are never dropped for a bad timestamp.
    """
    if not raw:
        return ""
    # 1. Numeric timestamp (Unix seconds or ms)
    try:
        return _ts_to_iso(int(float(raw)))
    except (ValueError, TypeError):
        pass
    # 2. ISO-8601 (news sources / already-normalised)
    try:
        return datetime.fromisoformat(str(raw)).strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        pass
    # 3. Weibo English: "Sun Jun 29 10:00:00 +0800 2025"
    try:
        return datetime.strptime(str(raw), "%a %b %d %H:%M:%S %z %Y").strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        pass
    # 4. 小红书/微博相对/部分日期（含地点后缀）："06-07 浙江" / "7天前浙江" /
    #    "昨天 08:59山西" / "44分钟前" / "今天09:00" / "09月09日 19:38"（无年份）
    s = str(raw).strip()
    m = re.search(r'(\d+)\s*分钟前', s)
    if m:
        # 分钟精度（比"小时前近似采集时刻"细一档），秒归零
        dt = datetime.now() - timedelta(minutes=int(m.group(1)))
        return dt.replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S")
    m = re.search(r'(\d+)\s*小时前', s)
    if m:
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")  # 小时级精度近似（采集时刻）
    m = re.search(r'(\d+)\s*天前', s)
    if m:
        return (_date.today() - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%dT00:00:00")
    # 微博相对日："今天09:00" / "昨天 08:59"（冒号前可能无空格）。必须在无时分的
    # '昨天' 兜底之前匹配，否则被截胡丢掉时分精度
    m = re.search(r'今天\s*(\d{1,2}):(\d{2})', s)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return (f"{_date.today():%Y-%m-%d}T"
                f"{int(m.group(1)):02d}:{int(m.group(2)):02d}:00")
    m = re.search(r'昨天\s*(\d{1,2}):(\d{2})', s)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return (f"{_date.today() - timedelta(days=1):%Y-%m-%d}T"
                f"{int(m.group(1)):02d}:{int(m.group(2)):02d}:00")
    # 微博高级搜索 "MM月DD日 HH:MM"（无年份）：默认当年；跨年边界（1 月看到
    # "12月28日"——当年值在未来）回退上一年。需在 MM-DD 兜底之前匹配
    m = re.search(r'(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})', s)
    if m:
        mo, da, hh, mi = (int(g) for g in m.groups())
        if 1 <= mo <= 12 and 1 <= da <= 31 and hh < 24 and mi < 60:
            try:
                dt = datetime(_date.today().year, mo, da, hh, mi)
            except ValueError:
                dt = None  # 2月30日 等非法日期 → 落到后面兜底
            if dt is not None:
                if dt > datetime.now():
                    dt = dt.replace(year=_date.today().year - 1)
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
    if '昨天' in s:
        return (_date.today() - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")
    m = re.search(r'(\d{1,2})-(\d{1,2})', s)
    if m:
        mo, da = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= da <= 31:
            return f"{_date.today().year}-{mo:02d}-{da:02d}T00:00:00"
    return ""


def _make_post(
    title: str,
    content: str,
    author: str,
    url: str,
    likes,
    comments_count,
    shares,
    platform: str,
    published_at: str = "",
) -> dict:
    """Build a standardised post dict. Callers override ``source`` afterwards."""
    if not title and content:
        title = content[:40] + ("..." if len(content) > 40 else "")
    return {
        "title": title,
        "content": content,
        "author": author,
        "url": url,
        "likes": _safe_int(likes),
        "comments": _safe_int(comments_count),
        "shares": _safe_int(shares),
        "platform": platform,
        "source": "cdp",
        "published_at": _parse_datetime(published_at),
    }


def _make_comment(
    content: str,
    author: str,
    likes,
    platform: str,
    post_url: str,
    post_note_id: str = "",
    published_at: str = "",
) -> dict:
    """Build a standardised comment dict."""
    return {
        "post_url": post_url,
        "post_note_id": post_note_id,
        "content": content,
        "author": author,
        "likes": _safe_int(likes),
        "platform": platform,
        "published_at": _parse_datetime(published_at),
    }


def derive_comment_sentiment(
    dim_sentiment: dict | str | None, comment_polarity: str | None = None,
) -> str:
    """评论整体情感派生——双轨（2026-10-16 舆情降本 T4，方案 §4）。

    轨 1（新评论，极性直出）：*comment_polarity* 为 "1"/"0"/"-1" 时直接映射
    positive/neutral/negative——模型直出，不经维度均值（口径断点：切换日后
    新评论全走此轨，历史评论保持轨 2 不重标）。
    轨 2（老评论，回退）：从评论 ABSA dim_sentiment 均值派生。

    阈值 >0.3=positive / <-0.3=negative / 否则=neutral。零分维度（模型边界
    未覆盖）不计入均值分母——与 analysis 层 ABSA 口径一致（2026-09-13 已
    改正：均分只算非零维度，否则零分稀释让所有评论偏 neutral）。

    *dim_sentiment* 可能是 dict（已解析）、JSON 字符串或 None（评论未走
    ABSA / 解析失败）。任何异常态都回退 neutral，绝不抛错——派生字段不能
    让入库链路崩。两轨皆空（未打标/哨兵"none"）同样回退 neutral——NULL→neutral
    语义是 2026-10-03 spec 钉过的既有口径，"跳过未打标"由端点层的 unanalyzed
    检查承担（两列皆空即不计入），不由本函数返回 None 表达。
    """
    _polarity_map = {"1": "positive", "0": "neutral", "-1": "negative"}
    if comment_polarity in _polarity_map:
        return _polarity_map[comment_polarity]
    if not dim_sentiment:
        return "neutral"
    if isinstance(dim_sentiment, str):
        try:
            import json
            dim_sentiment = json.loads(dim_sentiment)
        except (json.JSONDecodeError, TypeError):
            return "neutral"
    if not isinstance(dim_sentiment, dict):
        return "neutral"
    vals = [v for v in dim_sentiment.values()
            if isinstance(v, (int, float)) and v != 0]
    if not vals:
        return "neutral"
    avg = sum(vals) / len(vals)
    if avg > 0.3:
        return "positive"
    if avg < -0.3:
        return "negative"
    return "neutral"


# ── Dealer-post filter ──────────────────────────────────────────────────────

_DEALER_RE = re.compile(
    r"4[Ss]店|经销商|汽贸|海洋网|王朝网|"
    r"(?:比亚迪|长安|吉利|奇瑞|长城|广汽|上汽|一汽|东风|北汽|小鹏|蔚来|理想|问界|零跑|极氪|领克|宝骏)"
    r".{0,10}(?:海洋|王朝|体验|交付|销售|直营|授权|服务|售后|4S|店|汽车)|"
    # 营销号模式（2026-09-12 情感抽样实锤补充，保守——只加高置信词）：
    # "xx小鹏贩卖机"/"你在小鹏的唯一人脉"=门店导购号；准新车/二手车行=车商
    r"贩卖机|你的唯一人脉|唯一人脉|准新车|二手车行|汽车贸易|车行优选",
    re.IGNORECASE,
)


def _is_dealer_post(author: str, title: str) -> bool:
    """Return True if the post appears to be from a car dealership."""
    if _DEALER_RE.search(author):
        return True
    if "4S" in title and ("优惠" in title or "促销" in title or "报价" in title):
        return True
    return False


# ── 作者类型分层（2026-09-15 Q5：打标不删除，口碑口径层排除）─────────────────

# 营销号行为背调（B1）：历史帖汽车营销信号词。一个号可能给多个车型发软文，
# 跨车型合计历史帖；≥3 帖且 ≥70% 命中信号词→marketing_account。
# 保守选高置信词，宁漏勿错——博主黑吹稿本身是舆情事件的一部分。
_MARKETING_SIGNAL_WORDS = (
    "试驾", "评测", "上市", "价格", "配置", "续航", "对比",
    "提车", "订单", "交付", "实测", "体验", "导购", "行情",
)


def profile_author_behavior(author: str, historical_posts: list) -> str | None:
    """查该作者全库（跨车型）近 90 天历史帖，判定营销号。

    同步函数——只接历史帖 list（调用方负责批量查 DB 防止 N+1）。
    阈值：库内 ≥3 帖且 ≥70% 含汽车营销信号词→``marketing_account``。
    """
    if not historical_posts or len(historical_posts) < 3:
        return None
    auto_count = sum(
        1 for p in historical_posts
        if any(w in (p.get("title") or "") or w in (p.get("content") or "")
               for w in _MARKETING_SIGNAL_WORDS)
    )
    if auto_count / len(historical_posts) >= 0.7:
        return "marketing_account"
    return None


# 汽车媒体/博主的保守高置信 token（实测样本：车圈朵教主Dora/橘子选车指南/
# 带锤看车/易车榜/汽车洋葱圈……）。宁漏勿错：博主黑吹稿本身是舆情事件的一
# 部分，误标 auto_media 只影响后续可选过滤（当前口径不排除），误杀则失样本。
_AUTO_MEDIA_RE = re.compile(
    r"车评|说车|选车|车圈|车志|车界|车市|懂车帝|易车|汽车",
)

# 导流号信号词（D-3）：auto_media 帖 title/content 命中即 is_promo=True。
# 这些是导流话术（非正经车评内容）。只对 auto_media 判（普通用户帖即使含
# "优惠"也不标——他们不是导流号）。
# 注意（code-review 修正）：落地价/报价/贷款/分期/免息等是常见车评词，
# 不能作为导流信号——会误杀正经车评。只保留强导流特征词。
_PROMO_SIGNAL_RE = re.compile(
    r"低首付|零首付|首付.?万|找我|加微信|加微|私信.*车|"
    r"帮提车|代提车|全国提车|各店提车|找郝姐|找.*提车|"
    r"现车.*找|优惠.*找|降价.*找|"
    r"微信.*提车|留资|留电话|扫码.*车"
)


def _compact_name(s: str) -> str:
    """作者名紧凑化：去空白与常见分隔符，用于官号精确比对。"""
    return re.sub(r"[\s｜|·\-_/／]+", "", s or "")


def _official_candidates(brand: str, vehicle_name: str) -> set[str]:
    """从品牌/车型名派生官号名候选（紧凑态）。

    实测官号名形如 "特斯拉"（=brand）、"小鹏MONA"（=brand+车系词）、
    "小米汽车"（=brand）。车系词取车型名去品牌前缀后的字母/数字段，
    避免把中文短名（如 "星愿"）再拆出更短的高误伤候选。
    """
    b, v = _compact_name(brand), _compact_name(vehicle_name)
    out = set()
    if b:
        out.add(b)
        if not b.endswith("汽车"):
            out.add(b + "汽车")
    if v:
        out.add(v)
        rest = v[len(b):] if b and v.startswith(b) else v
        if rest and rest != v:
            # 官号名常为品牌+车系词前缀（实测 "小鹏MONA" ⊂ "小鹏MONA M03"）。
            # 字母数字连续段无法可靠切词（MONAM03 切不出 MONA），取全部前缀，
            # 候选量个位数、精确匹配，无误伤面。
            out.update(b + rest[:i] for i in range(1, len(rest) + 1))
    return out


def classify_author_type(author: str, title: str = "",
                         brand: str = "", vehicle_name: str = "") -> str:
    """作者分层：brand_official / dealer / auto_media / organic。

    优先级：官号 > 经销商 > 汽车媒体 > 普通用户；识别不出一律 organic。
    """
    a = _compact_name(author)
    if not a:
        return "organic"
    if a in _official_candidates(brand, vehicle_name):
        return "brand_official"
    if _is_dealer_post(author, title):
        return "dealer"
    if _AUTO_MEDIA_RE.search(author.replace("車", "车")):  # 繁体"車"归一
        return "auto_media"
    return "organic"


# ── TikHub 采集工具函数（2026-09-27 OneAPI 退役后唯一下游）──────────────────
# 历史上 OneAPI/TikHub 两个 collector 共用；现仅 tikhub_collector 消费。

# 单帖评论翻页上限默认值（env COMMENT_MAX_PAGES_DEFAULT 整数覆盖）。
# comment_max_pages() 调用时读取（非 import 时），测试可
# monkeypatch.setenv。2026-10-15 舆情降本（R41）：3→2（评论只判极性后覆盖深度
# 让位成本；负面追加走 batch_runner 负面词表预筛通道）。
_COMMENT_MAX_PAGES_DEFAULT = env_int("COMMENT_MAX_PAGES_DEFAULT", 3)  # 2026-10-16 R46：2→3 页


def comment_max_pages() -> int:
    """单帖评论翻页上限（env COMMENT_MAX_PAGES 整数覆盖，非法回退 2）。"""
    return env_int("COMMENT_MAX_PAGES", _COMMENT_MAX_PAGES_DEFAULT)


def _truthy(val) -> bool:
    """OneAPI/TikHub 各接口的布尔/翻页标记类型不统一（True / 1 / '1' / 'True'），统一判定。"""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes")
    return bool(val)


_HTML_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """剥 HTML 标签：微博正文 text 带 <a href=...>#话题#</a>、<br />。

    与本模块的 ``strip_html`` 互补但职责不同：后者只去标签（_store_posts 入库
    前的统一安全网）；本函数还处理 <br>→换行与 html.unescape 实体，针对微博
    正文富化（OneAPI/TikHub 采集路径用）。
    """
    if not text:
        return ""
    s = _HTML_BR_RE.sub("\n", text)
    s = _HTML_TAG_RE.sub("", s)
    return _html.unescape(s).strip()


def _path_tail(url: str) -> str:
    """URL 末段 id：/video/{id}、/explore/{id}?xsec_token=...、/status/{id}。

    与 scheduler._store_comments 的 note_id 推导同款约定，
    保证评论 post_note_id 能命中帖子的 note_id 映射。
    """
    return url.rsplit("/", 1)[-1].split("?")[0].split("#")[0]


# 抖音 publish_time：window_days → 能覆盖的最小档（schema 是字符串 "0"/"1"/"7"/"180"）
def _dy_publish_time(window_days: int) -> str:
    for days, val in ((1, "1"), (7, "7"), (180, "180")):
        if window_days <= days:
            return val
    return "0"  # 不限
