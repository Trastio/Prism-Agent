"""年款口碑分析工具

按购买时间推算年款，分析产品演进和口碑变化。
"""

import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import func, extract, distinct
from src.storage.db import session_scope
from src.models.orm import OwnerReview, ReviewTag

logger = logging.getLogger(__name__)


def _estimate_model_year(purchase_date) -> str:
    """从购买日期推算年款

    规则：
    - 2024-01-01后购车 → 2024款
    - 2023-01-01后购车 → 2023款
    - 2022-01-01后购车 → 2022款
    """
    if not purchase_date:
        return "未知年款"

    try:
        if isinstance(purchase_date, str):
            purchase_date = datetime.strptime(purchase_date, "%Y-%m-%d")

        year = purchase_date.year
        month = purchase_date.month

        # 汽车年款通常在前一年年底发布
        if month >= 9:  # 9月后购车可能是次年款
            return f"{year + 1}款"
        else:
            return f"{year}款"

    except (ValueError, TypeError):
        return "未知年款"


async def get_year_over_year_analysis(model_id: str, year: str = "") -> dict:
    """按年款分析口碑演进

    Args:
        model_id: 车系ID
        year: 年款（如"2024款"），为空返回年款对比

    Returns:
        {
            "year_distribution": {"2024款": 45, "2023款": 32, ...},
            "evolution_insights": ["2024款 vs 2023款：续航评价提升 N 条(...)", ...],
            "insufficient_trend_data": true  # 仅当样本不足/无显著变化时出现
        }
    """
    from src.tools.reviews import _ensure_tags_ready
    guard = await _ensure_tags_ready(model_id)
    if guard is not None:
        return guard

    # 归一化年款输入（新款/老款/2024 → 标准年款；解析失败回退全国对比，不 crash）
    if year:
        from src.tools._normalize import resolve_year
        resolved = await resolve_year(year, model_id)
        year = resolved if resolved else ""

    with session_scope() as session:
        # 1. 基础数据：各年款的口碑数量分布
        year_counts = {}

        # 获取所有有购买日期的口碑
        reviews = session.query(
            OwnerReview.review_id,
            OwnerReview.purchase_date
        ).filter(
            OwnerReview.model_id == model_id,
            OwnerReview.purchase_date.isnot(None)
        ).all()

        for review_id, purchase_date in reviews:
            model_year = _estimate_model_year(purchase_date)
            year_counts[model_year] = year_counts.get(model_year, 0) + 1

        # 2. 如果指定了年款，返回该年款的详细分析
        if year:
            return await _analyze_specific_year(session, model_id, year, year_counts)

        # 3. 否则返回年款演进对比
        return await _analyze_year_evolution(session, model_id, year_counts)


async def _analyze_specific_year(session, model_id: str, target_year: str, year_counts: dict) -> dict:
    """分析指定年款的口碑特点"""

    # 找出该年款的时间范围
    base_year = int(target_year.replace("款", ""))
    start_date = f"{base_year - 1}-09-01"  # 前一年9月开始
    end_date = f"{base_year}-12-31"

    # 获取该年段的标签分布
    year_tags = session.query(
        ReviewTag.tag_category,
        ReviewTag.tag_name,
        ReviewTag.sentiment,
        func.count(distinct(ReviewTag.review_id)).label('cnt')
    ).join(
        OwnerReview, ReviewTag.review_id == OwnerReview.review_id
    ).filter(
        OwnerReview.model_id == model_id,
        OwnerReview.purchase_date >= start_date,
        OwnerReview.purchase_date <= end_date
    ).group_by(
        ReviewTag.tag_category,
        ReviewTag.tag_name,
        ReviewTag.sentiment
    ).all()

    # 统计该年款的维度表现（归一化到 V3 业务维度，与 get_review_analysis 一致）
    from src.tools.reviews import _map_to_business_dim
    dimension_performance = {}
    for cat, tag, sentiment, cnt in year_tags:
        dim = _map_to_business_dim(cat, tag)
        if sentiment == "pro":
            dimension_performance[dim] = dimension_performance.get(dim, 0) + cnt
        else:
            dimension_performance[dim] = dimension_performance.get(dim, 0) - cnt

    # 排序找出最佳和最差维度
    sorted_dims = sorted(dimension_performance.items(), key=lambda x: x[1], reverse=True)
    best_dims = sorted_dims[:3] if sorted_dims else []
    worst_dims = sorted_dims[-3:] if len(sorted_dims) > 3 else []

    return {
        "year": target_year,
        "review_count": year_counts.get(target_year, 0),
        "best_dimensions": [f"{dim}({score:+d})" for dim, score in best_dims],
        "worst_dimensions": [f"{dim}({score:+d})" for dim, score in reversed(worst_dims)],
        "dimension_performance": dimension_performance,
        "insight": f"{target_year}共有{year_counts.get(target_year, 0)}条口碑，"
                  f"最佳维度是{best_dims[0][0] if best_dims else '综合'}"
    }


async def _analyze_year_evolution(session, model_id: str, year_counts: dict) -> dict:
    """年款演进对比分析"""

    evolution_insights = []

    # 获取相邻年款的对比
    sorted_years = sorted(year_counts.keys(), reverse=True)

    for i in range(len(sorted_years) - 1):
        current_year = sorted_years[i]
        prev_year = sorted_years[i + 1]

        current_count = year_counts.get(current_year, 0)
        prev_count = year_counts.get(prev_year, 0)

        if current_count < 5 or prev_count < 5:  # 样本太少跳过
            continue

        # 获取两个年款的维度对比
        current_year_num = int(current_year.replace("款", ""))
        prev_year_num = int(prev_year.replace("款", ""))

        current_start = f"{current_year_num - 1}-09-01"
        current_end = f"{current_year_num}-12-31"
        prev_start = f"{prev_year_num - 1}-09-01"
        prev_end = f"{prev_year_num}-12-31"

        # 获取当前年款的维度分布
        current_dims = session.query(
            ReviewTag.tag_category,
            func.count(distinct(ReviewTag.review_id)).label('cnt')
        ).join(
            OwnerReview, ReviewTag.review_id == OwnerReview.review_id
        ).filter(
            OwnerReview.model_id == model_id,
            OwnerReview.purchase_date >= current_start,
            OwnerReview.purchase_date <= current_end
        ).group_by(
            ReviewTag.tag_category
        ).all()

        current_dim_dist = {cat: cnt for cat, cnt in current_dims}

        # 获取之前年款的维度分布
        prev_dims = session.query(
            ReviewTag.tag_category,
            func.count(distinct(ReviewTag.review_id)).label('cnt')
        ).join(
            OwnerReview, ReviewTag.review_id == OwnerReview.review_id
        ).filter(
            OwnerReview.model_id == model_id,
            OwnerReview.purchase_date >= prev_start,
            OwnerReview.purchase_date <= prev_end
        ).group_by(
            ReviewTag.tag_category
        ).all()

        prev_dim_dist = {cat: cnt for cat, cnt in prev_dims}

        # 发现演进趋势
        for dim, current_cnt in current_dim_dist.items():
            prev_cnt = prev_dim_dist.get(dim, 0)

            if current_cnt > prev_cnt * 1.3:  # 提升超过30%
                evolution_insights.append(
                    f"{current_year} vs {prev_year}：{dim}评价提升{current_cnt - prev_cnt}条({current_cnt} vs {prev_cnt})"
                )
            elif current_cnt < prev_cnt * 0.7:  # 下降超过30%
                evolution_insights.append(
                    f"{current_year} vs {prev_year}：{dim}评价下降{prev_cnt - current_cnt}条({current_cnt} vs {prev_cnt})"
                )

    result = {
        "year_distribution": year_counts,
        "total_reviews": sum(year_counts.values()),
        "evolution_insights": evolution_insights,
    }
    if not evolution_insights:
        result["insufficient_trend_data"] = True
        result["stop_answering"] = True
        result["note"] = "各年款样本不足或变化不显著，无法给出可靠演进结论，不要编造趋势。"
    return result