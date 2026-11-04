"""Platform 命名单一真理源（主题 B 治根）。

规范值=全名（DB 存储 / API 交互 / 前端显示的唯一标准）；缩写
(xhs/wb/dy/ks) 为遗留别名，经 normalize_platform() 统一收敛。

新增平台只需修改本文件一处，全栈自动一致。
"""
from __future__ import annotations

# 规范全名（canonical）—— 所有层应使用这些常量，禁止散落字符串字面量
XIAOHONGSHU = "xiaohongshu"
WEIBO = "weibo"
DOUYIN = "douyin"
KUAISHOU = "kuaishou"
NEWS = "news"
# 车质网（12365auto.com）—— 质量投诉主阵地，独立于新闻源与社媒（A5）
CHEZHIWANG = "chezhiwang"

ALL_PLATFORMS = (XIAOHONGSHU, WEIBO, DOUYIN, KUAISHOU, NEWS, CHEZHIWANG)
# 2026-10-15 停采微博/快手（舆情降本方案 R23：渠道收敛 4→2 平台）——调度遍历
# 本常量决定"今天采哪些社媒"；身份映射/标签/历史数据查询不受影响（用 ALL_PLATFORMS）。
SOCIAL_PLATFORMS = (XIAOHONGSHU, DOUYIN)

# 遗留缩写 → 规范全名（数据迁移与输入兼容用）
_SHORT_TO_FULL = {"xhs": XIAOHONGSHU, "wb": WEIBO, "dy": DOUYIN, "ks": KUAISHOU}
# 规范全名 → 缩写（仅历史接口/采集器内部需要时使用）
_FULL_TO_SHORT = {v: k for k, v in _SHORT_TO_FULL.items()}

_LABELS = {
    XIAOHONGSHU: "小红书",
    WEIBO: "微博",
    DOUYIN: "抖音",
    KUAISHOU: "快手",
    NEWS: "新闻源",
    CHEZHIWANG: "车质网",
}


def normalize_platform(p: str | None) -> str | None:
    """任意输入（缩写 / 全名 / 大小写）→ 规范全名。

    - None / 空串 → None
    - 已知缩写 → 对应全名
    - 已知全名 / 未知值 → 小写原样返回（宽松兼容，不做枚举校验）
    """
    if not p:
        return None
    pl = p.lower()
    return _SHORT_TO_FULL.get(pl, pl)


def platform_label(p: str | None) -> str:
    """platform 值 → 中文标签；未知值原样返回，None → 空串。"""
    return _LABELS.get(normalize_platform(p), p or "")


def platform_query_values(p: str | None) -> tuple[str, ...]:
    """查询用：返回某 platform 在 DB 中应匹配的所有存储值（规范全名 + 遗留缩写）。

    过渡期库内缩写/全名混存，``in_`` 同时命中两者；数据迁移为全名后，
    缩写值不再存在，多匹配一个空集无害。一次到位，不依赖迁移顺序，
    无需调用方手写 OR 双查。

    枚举校验（2026-09-29 R-1）：未知平台值（如前端误传 'all'）返回空元组，
    避免 RawPost.platform.in_(('all',)) 静默全空——未知值明确不匹配任何帖。
    """
    if not p:
        return ()
    norm = normalize_platform(p)
    if norm not in ALL_PLATFORMS:  # 未知平台（如 'all'）→ 空元组，不静默全空
        return ()
    vals = {norm}
    short = _FULL_TO_SHORT.get(norm)
    if short:
        vals.add(short)
    return tuple(vals)
