"""地域口碑分析工具（优化版）

支持多维度交叉分析：地域×版型、地域×关注点、特定地域深度分析
"""

import logging
from typing import Optional
from sqlalchemy import func, and_, or_, distinct
from src.storage.db import session_scope
from src.models.orm import OwnerReview, ReviewTag

logger = logging.getLogger(__name__)


# 地域映射：城市 → 区域
_REGION_MAPPING = {
    "北京": "华北", "天津": "华北", "石家庄": "华北", "太原": "华北", "济南": "华北", "青岛": "华北",
    "上海": "华东", "南京": "华东", "杭州": "华东", "苏州": "华东", "合肥": "华东", "宁波": "华东", "无锡": "华东",
    "广州": "华南", "深圳": "华南", "东莞": "华南", "佛山": "华南", "珠海": "华南",
    "成都": "西南", "重庆": "西南", "西安": "西北", "武汉": "华中", "长沙": "华中", "郑州": "华中",
    "沈阳": "东北", "大连": "东北", "长春": "东北", "哈尔滨": "东北"
}


def _map_to_region(city: str) -> str:
    """将城市映射到区域"""
    if not city:
        return "其他"
    city_clean = city.replace("市", "").strip()
    return _REGION_MAPPING.get(city_clean, "其他")


async def get_regional_analysis(model_id: str, region: str = "",
                               spec_name: str = "") -> dict:
    """按地域分析口碑差异（支持版型交叉分析）

    Args:
        model_id: 车系ID
        region: 区域名称（如"华北"、"华南"、"北京"），为空返回全国对比
        spec_name: 版型名称（如"510KM 旗舰型"），支持地域×版型交叉分析

    Returns:
        {
            "query_type": "地域分析"或"地域×版型分析",
            "regional_distribution": {"华北": 15, "华南": 12, ...},
            "regional_insights": [
                {
                    "region": "华北",
                    "review_count": 15,
                    "top_concerns": ["续航", "空间"],
                    "top_complaints": ["充电慢", "后备箱小"],
                    "spec_preference": {"510KM": 8, "620KM": 7},  # 版型偏好
                    "unique_insights": ["续航关注度全国最高(25条 vs 全国平均15条)"]
                },
                ...
            ]
        }
    """
    # 全国地域对比（region 为空）只需 city 数量分布、不依赖标签 → 放行
    # 特定地域分析（region 非空）需标签 → 守卫
    if region:
        from src.tools.reviews import _ensure_tags_ready
        guard = await _ensure_tags_ready(model_id)
        if guard is not None:
            return guard

    with session_scope() as session:
        # 基础过滤条件
        base_filter = [OwnerReview.model_id == model_id]
        if spec_name:
            base_filter.append(OwnerReview.spec_name.contains(spec_name))

        # 1. 基础数据：各地域的口碑数量分布
        regional_counts = {}
        city_reviews = session.query(
            OwnerReview.city,
            OwnerReview.spec_name,
            func.count(OwnerReview.review_id).label('cnt')
        ).filter(
            and_(*base_filter),
            OwnerReview.city.isnot(None)
        ).group_by(
            OwnerReview.city,
            OwnerReview.spec_name
        ).all()

        for city, spec, cnt in city_reviews:
            region_name = _map_to_region(city)
            key = f"{region_name}#{spec}" if spec_name else region_name
            regional_counts[key] = regional_counts.get(key, 0) + cnt

        # 如果没有地域数据，返回真实数量分析
        if not regional_counts:
            total_count = session.query(func.count(OwnerReview.review_id)).filter(
                and_(*base_filter)
            ).scalar()
            return {
                "query_type": "基础统计",
                "total_reviews": total_count,
                "insufficient_regional_data": True,
                "message": f"暂无地域分布数据（city 字段缺失），共{total_count}条口碑。不要编造地域差异结论。",
                "stop_answering": True
            }

        # 2. 如果指定了区域，返回该区域的详细分析
        if region:
            return await _analyze_specific_region(session, model_id, region,
                                                 regional_counts, spec_name)

        # 3. 否则返回全国对比分析
        return await _analyze_regional_comparison(session, model_id,
                                                   regional_counts, spec_name)


async def _analyze_specific_region(session, model_id: str, target_region: str,
                                 regional_counts: dict, spec_name: str) -> dict:
    """分析指定区域的口碑特点"""

    # 用归一化层解析地域（支持 北方/南方/江浙沪/大湾区/东北/大区/单城市）
    from src.tools._normalize import resolve_region
    resolved = resolve_region(target_region)
    target_cities = resolved["cities"]
    low_confidence = resolved.get("low_confidence", False)
    if resolved["regions"]:
        target_region = resolved["regions"][0]

    # 基础过滤
    base_filter = [OwnerReview.model_id == model_id]
    if spec_name:
        base_filter.append(OwnerReview.spec_name.contains(spec_name))

    # 获取该区域的标签分布（如果有标签数据）
    try:
        region_tags = session.query(
            ReviewTag.tag_category,
            ReviewTag.tag_name,
            ReviewTag.sentiment,
            func.count(distinct(ReviewTag.review_id)).label('cnt')
        ).join(
            OwnerReview, ReviewTag.review_id == OwnerReview.review_id
        ).filter(
            and_(*base_filter),
            OwnerReview.city.in_(target_cities)
        ).group_by(
            ReviewTag.tag_category,
            ReviewTag.tag_name,
            ReviewTag.sentiment
        ).all()

        # 统计买点和槽点（维度归一化到 V3 业务维度，与 get_review_analysis 一致）
        from src.tools.reviews import _map_to_business_dim
        pros = {}
        cons = {}
        for cat, tag, sentiment, cnt in region_tags:
            dim = _map_to_business_dim(cat, tag)
            if sentiment == "pro":
                pros[dim] = pros.get(dim, 0) + cnt
            else:
                cons[dim] = cons.get(dim, 0) + cnt

        # 版型偏好分析
        spec_preference = {}
        actual_review_count = 0
        if len(target_cities) > 0:
            spec_dist = session.query(
                OwnerReview.spec_name,
                func.count(OwnerReview.review_id).label('cnt')
            ).filter(
                and_(*base_filter),
                OwnerReview.city.in_(target_cities)
            ).group_by(OwnerReview.spec_name).all()

            for spec, cnt in spec_dist:
                if spec:
                    spec_preference[spec] = cnt
                actual_review_count += cnt

        # 找出最受关注的维度和最大槽点
        top_concerns = sorted(pros.items(), key=lambda x: x[1], reverse=True)[:3]
        top_complaints = sorted(cons.items(), key=lambda x: x[1], reverse=True)[:3]

        return {
            "query_type": "特定地域分析",
            "region": target_region,
            "review_count": actual_review_count,
            "top_concerns": [f"{dim}({cnt}条)" for dim, cnt in top_concerns],
            "top_complaints": [f"{dim}({cnt}条)" for dim, cnt in top_complaints],
            "spec_preference": spec_preference,
            "has_detailed_analysis": len(region_tags) > 0
        }

    except Exception as e:
        # 如果标签分析失败，至少返回基础统计
        logger.warning(f"地域标签分析失败: {e}")
        return {
            "query_type": "地域基础统计",
            "region": target_region,
            "review_count": regional_counts.get(target_region, 0),
            "message": "地域基础数据可用，详细分析暂不可用。不要基于基础统计编造地域口碑差异。",
            "stop_answering": True
        }


async def _analyze_regional_comparison(session, model_id: str,
                                 regional_counts: dict, spec_name: str) -> dict:
    """全国地域对比分析"""

    total_reviews = sum(regional_counts.values())

    # 简化版：只返回基础分布数据
    regions = {}
    for key, count in regional_counts.items():
        if "#" in key:
            region, spec = key.split("#")
            regions[region] = regions.get(region, 0) + count
        else:
            regions[key] = count

    # 找出口碑最多的3个地区
    top_regions = sorted(regions.items(), key=lambda x: x[1], reverse=True)[:3]

    return {
        "query_type": "全国地域对比",
        "total_reviews": total_reviews,
        "regional_distribution": regions,
        "top_regions": [
            {
                "region": region,
                "count": count,
                "percentage": f"{count/total_reviews*100:.1f}%"
            }
            for region, count in top_regions
        ],
        "insights": [
            f"{region}地区口碑最多({count}条，占总数的{count/total_reviews*100:.1f}%)"
            for region, count in top_regions
        ]
    }