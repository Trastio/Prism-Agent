"""健康分等口径计算的单一真相源（#1/#26 审查修复）。

3 处健康分实现（dashboard /overview、fleet-overview、reports dashboard-summary）
统一调此函数，避免公式/口径漂移。
"""


def compute_health_score(pos: int, neg: int, total: int) -> float:
    """健康分 = 50 + (正面 - 负面) / 总量 × 50。

    - total=0 返回 50（无数据居中）
    - clamp 0-100
    - 分母 total 应为已分析帖数（SELF_ONLY + AUTHENTIC_AUTHOR 口径）
    """
    if total <= 0:
        return 50.0
    return max(0, min(100, round(50 + (pos - neg) / total * 50, 1)))
