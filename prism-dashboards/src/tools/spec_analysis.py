"""版型口碑分析工具（优化版）

支持不同版型的对比分析，发现版型偏好和差异
"""

import logging
from typing import Optional
from sqlalchemy import func, and_, distinct
from src.storage.db import session_scope
from src.models.orm import OwnerReview, ReviewTag

logger = logging.getLogger(__name__)


async def get_spec_analysis(model_id: str, spec_name: str = "") -> dict:
    """按版型分析口碑差异

    Args:
        model_id: 车系ID
        spec_name: 版型名称（如"510KM 旗舰型"），为空返回版型对比

    Returns:
        {
            "query_type": "版型分析"或"版型对比",
            "spec_distribution": {
                "510KM 旗舰型": 35,
                "620KM 旗舰型": 28,
                ...
            },
            "spec_insights": [
                {
                    "spec": "510KM 旗舰型",
                    "review_count": 35,
                    "top_pros": ["续航长", "空间大"],
                    "top_cons": ["充电慢", "无座椅通风"],
                    "user_profile": "家庭用户偏好"
                },
                ...
            ]
        }
    """
    # 版型对比（spec_name 为空）只需 spec_name 数量分布、不依赖标签 → 放行
    # 特定版型深度分析（spec_name 非空）需标签 → 归一化 + 守卫
    if spec_name:
        from src.tools._normalize import resolve_spec
        resolved = await resolve_spec(spec_name, model_id)
        if not resolved.get("low_confidence"):
            spec_name = resolved["spec_name"]
        from src.tools.reviews import _ensure_tags_ready
        guard = await _ensure_tags_ready(model_id)
        if guard is not None:
            return guard

    with session_scope() as session:
        base_filter = [OwnerReview.model_id == model_id]

        # 1. 基础数据：各版型的口碑数量分布
        spec_counts = {}
        spec_reviews = session.query(
            OwnerReview.spec_name,
            func.count(OwnerReview.review_id).label('cnt')
        ).filter(
            and_(*base_filter),
            OwnerReview.spec_name.isnot(None)
        ).group_by(OwnerReview.spec_name).all()

        for spec, cnt in spec_reviews:
            if spec:
                spec_counts[spec] = cnt

        # 如果没有版型数据，返回总数量
        if not spec_counts:
            total_count = session.query(func.count(OwnerReview.review_id)).filter(
                and_(*base_filter)
            ).scalar()
            return {
                "query_type": "基础统计",
                "total_reviews": total_count,
                "insufficient_spec_data": True,
                "message": f"暂无版型分布数据，共{total_count}条口碑"
            }

        # 2. 如果指定了版型，返回该版型的详细分析
        if spec_name:
            return await _analyze_specific_spec(session, model_id, spec_name, spec_counts)

        # 3. 否则返回版型对比分析
        return await _analyze_spec_comparison(session, model_id, spec_counts)


async def _analyze_specific_spec(session, model_id: str, target_spec: str,
                               spec_counts: dict) -> dict:
    """分析指定版型的口碑特点"""

    base_filter = [
        OwnerReview.model_id == model_id,
        OwnerReview.spec_name.contains(target_spec)
    ]

    try:
        # 获取该版型的标签分布
        spec_tags = session.query(
            ReviewTag.tag_category,
            ReviewTag.tag_name,
            ReviewTag.sentiment,
            func.count(distinct(ReviewTag.review_id)).label('cnt')
        ).join(
            OwnerReview, ReviewTag.review_id == OwnerReview.review_id
        ).filter(
            and_(*base_filter)
        ).group_by(
            ReviewTag.tag_category,
            ReviewTag.tag_name,
            ReviewTag.sentiment
        ).all()

        # 统计买点和槽点
        pros = {}
        cons = {}
        for cat, tag, sentiment, cnt in spec_tags:
            if sentiment == "pro":
                pros[tag] = pros.get(tag, 0) + cnt
            else:
                cons[tag] = cons.get(tag, 0) + cnt

        # 找出最突出的买点和槽点
        top_pros = sorted(pros.items(), key=lambda x: x[1], reverse=True)[:3]
        top_cons = sorted(cons.items(), key=lambda x: x[1], reverse=True)[:3]

        # 推断用户画像
        user_profile = _infer_user_profile(target_spec, pros, cons)

        # 计算实际匹配的版型总数（支持模糊匹配）
        actual_count = sum(cnt for spec, cnt in spec_counts.items() if target_spec in (spec or ""))

        return {
            "query_type": "特定版型分析",
            "spec": target_spec,
            "review_count": actual_count,
            "top_pros": [f"{tag}({cnt}条)" for tag, cnt in top_pros],
            "top_cons": [f"{tag}({cnt}条)" for tag, cnt in top_cons],
            "user_profile": user_profile,
            "has_detailed_analysis": len(spec_tags) > 0
        }

    except Exception as e:
        logger.warning(f"版型标签分析失败: {e}")
        return {
            "query_type": "版型基础统计",
            "spec": target_spec,
            "review_count": spec_counts.get(target_spec, 0),
            "message": "版型基础数据可用，详细分析暂不可用"
        }


async def _analyze_spec_comparison(session, model_id: str, spec_counts: dict) -> dict:
    """版型对比分析"""

    total_reviews = sum(spec_counts.values())

    # 找出口碑最多的3个版型
    top_specs = sorted(spec_counts.items(), key=lambda x: x[1], reverse=True)[:3]

    return {
        "query_type": "版型对比",
        "total_reviews": total_reviews,
        "spec_distribution": spec_counts,
        "top_specs": [
            {
                "spec": spec,
                "count": count,
                "percentage": f"{count/total_reviews*100:.1f}%"
            }
            for spec, count in top_specs
        ],
        "insights": [
            f"{spec}口碑最多({count}条，占{count/total_reviews*100:.1f}%)"
            for spec, count in top_specs
        ]
    }


def _infer_user_profile(spec_name: str, pros: dict, cons: dict) -> str:
    """推断版型的用户画像"""

    spec_lower = spec_name.lower()

    # 基于版型名称的规则
    if "510km" in spec_lower or "400km" in spec_lower:
        return "城市通勤用户，注重经济性和实用性"
    elif "620km" in spec_lower or "700km" in spec_lower:
        return "家庭用户，注重续航和空间实用性"
    elif "performance" in spec_lower or "高性能" in spec_lower:
        return "驾驶爱好者，注重动力和操控"
    elif "豪华" in spec_lower or "旗舰" in spec_lower:
        return "品质追求者，注重配置和舒适性"
    else:
        return "标准用户群体"