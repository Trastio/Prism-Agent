"""Platform-specific collection strategies.

OneAPI 时代（2026-09-10 起）：社媒四平台走转售 API，不再有 CDP 风控/
登录态约束。策略语义从"风控规避"改为"按调用次数（计费）控制"：
max_keywords 直接决定每平台的搜索调用次数（评论另有 top-N 帖上限，
见 TikHubCollector 默认值）；inter_request_delay 只是节奏礼貌位。
"""

from dataclasses import dataclass

from pipeline.platforms import _FULL_TO_SHORT

# ── Platform name → short code mapping ──────────────────────────────────────
# 引用 platforms 单一真理源，避免重复维护映射（主题 B 治根）
PLATFORM_MAP = dict(_FULL_TO_SHORT)


# ── Strategy dataclass ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class PlatformStrategy:
    """Single-platform collection policy."""

    risk_level: str           # none / low / medium / high
    max_keywords: int         # max keywords per collection run
    max_pages: int            # max search result pages
    inter_request_delay: int  # seconds between requests（礼貌位，非风控位）

    @property
    def is_safe(self) -> bool:
        return self.risk_level == "none"


# ── Concrete strategies ─────────────────────────────────────────────────────

NEWS = PlatformStrategy(
    risk_level="none",
    max_keywords=10,
    max_pages=10,
    inter_request_delay=0,
)

XIAOHONGSHU = PlatformStrategy(
    risk_level="low",
    # 2026-10-15 舆情降本（R32/R43）：15→6。6 词构成（由 _build_collection_keywords
    # 拼序保证）= 核心1 + 双关键词2 + 缺陷词3（P1 轮换，DEFECT_ROTATE_DAYS=2）。
    # ⚠️ max_keywords 若回调 <6，缺陷词会被挤出选区（拼序核心/双词在前）。
    max_keywords=6,
    max_pages=1,
    inter_request_delay=1,
)

WEIBO = PlatformStrategy(
    risk_level="low",
    max_keywords=15,
    max_pages=2,
    inter_request_delay=1,
)

DOUYIN = PlatformStrategy(
    risk_level="low",
    # 同 XIAOHONGSHU：2026-10-15 15→6（舆情降本 R32/R43），构成见上。
    max_keywords=6,
    max_pages=2,
    inter_request_delay=1,
)

KUAISHOU = DOUYIN  # 同 douyin（v3 补测通过，2026-09-10）——2026-10-15 停采归档（R23）

# 车质网（A5）：HTML 直采，无风控无计费；按车系 seriesId 抓列表，max_keywords
# 语义不适用（一车一 seriesId），max_pages 控制翻页深度。
CHEZHIWANG = PlatformStrategy(
    risk_level="none",
    max_keywords=1,
    max_pages=3,
    inter_request_delay=1,
)


# ── Registry ────────────────────────────────────────────────────────────────

# 2026-10-15 停采摘除（舆情降本方案 R23/R31）：news/weibo/kuaishou 移出注册表，
# 策略对象（NEWS/WEIBO/KUAISHOU）与 collector 代码保留归档；get_strategy 对
# 已停采平台回落 _DEFAULT（保守）。采集调度入口见 platforms.SOCIAL_PLATFORMS。
PLATFORM_STRATEGIES: dict[str, PlatformStrategy] = {
    "xiaohongshu": XIAOHONGSHU,
    "douyin": DOUYIN,
    "chezhiwang": CHEZHIWANG,
}


_DEFAULT = PlatformStrategy(
    risk_level="high", max_keywords=1, max_pages=1, inter_request_delay=8,
)


def get_strategy(platform: str) -> PlatformStrategy:
    """Get strategy for a platform. Defaults to conservative (high-risk, 1 kw)."""
    return PLATFORM_STRATEGIES.get(platform, _DEFAULT)
