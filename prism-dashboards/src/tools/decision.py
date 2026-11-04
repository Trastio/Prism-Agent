"""决策支持工具：偏好引出、加权打分、推荐理由"""
import logging

from sqlalchemy import or_, and_

logger = logging.getLogger(__name__)

DEFAULT_DIMENSIONS = ["续航", "安全", "舒适", "颜值", "性价比"]
_session_mgr = None


def _get_session_mgr():
    global _session_mgr
    if _session_mgr is None:
        from src.conversation.manager import SessionManager
        _session_mgr = SessionManager()
    return _session_mgr


async def elicit_preferences(user_id: str = "default", step: int = 0, choice: str = "",
                              preferences: str = "") -> dict:
    """引导用户对 5 个评价维度排序并持久化。支持一次性输入和逐步输入两种模式。

    一次性模式：preferences 参数传入如 "续航>安全>舒适>颜值>性价比" 格式的排序
    逐步模式：step=0 返回首次提问；step>0 记录选择并更新偏好权重
    """
    dims = DEFAULT_DIMENSIONS

    if preferences and preferences.strip():
        parsed = _parse_preference_string(preferences, dims)
        if parsed:
            try:
                mgr = _get_session_mgr()
                mgr.update_preference(user_id, dimension_weights=parsed)
            except Exception:
                pass
            sorted_dims = sorted(parsed.items(), key=lambda x: x[1], reverse=True)
            return {
                "question": "偏好已记录！我将根据您的偏好为您推荐车型。",
                "step": 0,
                "completed": True,
                "preferences": parsed,
                "preference_order": [f"{k}({v:.0%})" for k, v in sorted_dims],
            }

    if step == 0:
        return {
            "question": "为了给您更精准的推荐，请对以下维度按重要性排序（点击箭头调整顺序，或拖拽排序）：",
            "dimensions": dims,
            "step": 1,
            "completed": False,
            "must_wait_for_user": True,
            "instruction": "建议将以上偏好排序问题展示给用户，等待用户回复后再继续后续的车型搜索和推荐。",
            "note": "支持一次性输入偏好排序，或逐步收集",
            "interactive": {
                "type": "preference_sort",
                "items": [
                    {"id": "续航", "label": "🔋 续航/能耗", "desc": "续航里程、能耗表现"},
                    {"id": "安全", "label": "🛡️ 安全性", "desc": "主动/被动安全配置"},
                    {"id": "舒适", "label": "🛋️ 舒适性/空间", "desc": "乘坐空间、座椅舒适度"},
                    {"id": "颜值", "label": "🎨 外观/颜值", "desc": "外观设计、内饰质感"},
                    {"id": "性价比", "label": "💰 性价比", "desc": "配置丰富度、价格优势"},
                ],
                "confirm_text": "确认排序",
                "hint": "点击 ⬆⬇ 调整顺序，排在前面的维度权重更高",
            },
        }

    if choice and choice in dims:
        try:
            mgr = _get_session_mgr()
            rank = min(step, 5)
            weight_value = max(0.05, 0.4 - (rank - 1) * 0.08)
            current = mgr.get_preference(user_id).dimension_weights
            current[choice] = weight_value
            mgr.update_preference(user_id, dimension_weights=current)
        except Exception:
            pass

    remaining = [d for d in dims if d != choice] if step >= 5 else dims[step:]

    if step >= 5 or not remaining:
        return {
            "question": "好的，维度排序已完成！我会根据您的偏好为您推荐车型。",
            "step": 0,
            "completed": True,
        }

    return {
        "question": f"好的，接下来第{step + 1}重要的是什么？（剩余维度：{', '.join(remaining)}）",
        "step": step + 1,
        "completed": False,
        "must_wait_for_user": True,
        "instruction": "建议将以上问题展示给用户，等待用户回复后再继续。",
        "dimensions": remaining,
    }


def _parse_preference_string(pref_str: str, dims: list[str]) -> dict | None:
    """解析用户一次性输入的偏好排序，如 "续航>安全>舒适>颜值>性价比" """
    separators = [">", "＞", ">", ">", "、", ",", "，"]
    parts = None
    for sep in separators:
        if sep in pref_str:
            parts = [p.strip() for p in pref_str.split(sep) if p.strip()]
            break
    if not parts or len(parts) < 2:
        return None

    matched = []
    for p in parts:
        for d in dims:
            if d in p or p in d:
                matched.append(d)
                break

    if len(matched) < 2:
        return None

    weights = {}
    for i, d in enumerate(matched):
        weights[d] = max(0.05, 0.4 - i * 0.08)

    for d in dims:
        if d not in weights:
            weights[d] = 0.05

    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}

    return weights


async def score_models(model_ids: list[str], weights: dict | None = None) -> dict:
    """基于偏好权重 + 口碑标签 + 独特配置亮点对候选车型打分排序。

    Args:
        model_ids: 车系 ID 列表
        weights: 维度权重（如 {"续航": 0.3, "安全": 0.25, ...}），为空则均等权重

    Returns:
        rankings: 按综合评分排序的车型列表（含 overall、dimensions、unique_highlights）
        recommendation: 推荐摘要文本
        interactive: 雷达图数据
    """
    if weights is None:
        weights = {d: 0.2 for d in DEFAULT_DIMENSIONS}

    config_cache = {}
    for mid in model_ids:
        try:
            from src.tools.config import get_config
            config_cache[mid] = await get_config(mid)
        except Exception:
            config_cache[mid] = {}

    unique_bonus = _compute_unique_config_bonus(model_ids, config_cache)

    scores = {}
    for mid in model_ids:
        try:
            from src.tools.reviews import get_review_analysis
            cur_analysis = await get_review_analysis(mid, top_n=5, skip_background=True)
            cur_config = config_cache.get(mid, {})

            review_count = cur_analysis.get("review_count", 0)
            dimension_scores = {}
            for dim, weight in weights.items():
                dim_score = _score_dimension_weighted(dim, cur_analysis)
                config_boost = _config_boost(dim, cur_config)
                dimension_scores[dim] = round(dim_score * weight * 10 * config_boost, 2)

            overall = sum(dimension_scores.values())
            if review_count > 5:
                overall = round(overall * (1 + 0.1 * (1 - 1 / max(1, review_count / 10))), 2)

            bonus = unique_bonus.get(mid, 0)
            overall = round(overall + bonus, 2)

            scores[mid] = {
                "name": cur_analysis.get("model_name", mid),
                "overall": max(0, round(overall, 2)),
                "dimensions": dimension_scores,
                "unique_config_bonus": bonus,
                "unique_highlights": _get_config_highlights(cur_config),
                "review_count": review_count,
                "insufficient_data": cur_analysis.get("insufficient_data", True),
            }
        except Exception as e:
            logger.error(f"score_models error for {mid}: {e}")
            scores[mid] = {"name": mid, "overall": 0, "error": str(e)}

    ranked = sorted(scores.items(), key=lambda x: x[1].get("overall", 0), reverse=True)
    total_reviews = sum(s.get("review_count", 0) for s in scores.values())

    recommendation = ""
    if ranked:
        winner = ranked[0]
        winner_data = winner[1]
        winner_name = winner_data.get("name", winner[0])
        winner_highlights = winner_data.get("unique_highlights", [])
        winner_bonus = winner_data.get("unique_config_bonus", 0)

        recommendation = f"推荐车型：{winner_name}（综合评分 {winner_data.get('overall', 0):.1f}/10）"
        if winner_highlights:
            highlight_str = "、".join(winner_highlights)
            recommendation += f"。独特配置亮点：{highlight_str}"
        if winner_bonus > 0:
            recommendation += f"。独特配置加分：+{winner_bonus:.1f}分"

        if len(ranked) > 1:
            runner_up = ranked[1]
            runner_data = runner_up[1]
            recommendation += f"。第二名：{runner_data.get('name', runner_up[0])}（{runner_data.get('overall', 0):.1f}分）"

        recommendation += "。rankings 已按综合评分排序，可作为推荐参考。"

    return {
        "rankings": [{"model_id": mid, **data} for mid, data in ranked],
        "weights": weights,
        "recommendation": recommendation,
        "data_source": f"基于{len(model_ids)}款车型 + {total_reviews}条口碑数据综合评分",
        "interactive": {
            "type": "score_radar",
            "models": [
                {
                    "name": r.get("name", r.get("model_id", "")),
                    "overall": r.get("overall", 0),
                    "dimensions": r.get("dimensions", {}),
                    "unique_highlights": r.get("unique_highlights", []),
                    "unique_config_bonus": r.get("unique_config_bonus", 0),
                    "review_count": r.get("review_count", 0),
                }
                for r in [{"model_id": mid, **data} for mid, data in ranked]
            ],
            "dimension_names": list(weights.keys()),
            "data_source": f"基于{len(model_ids)}款车型 + {total_reviews}条口碑数据综合评分",
        },
    }


def _compute_unique_config_bonus(model_ids: list[str], config_cache: dict) -> dict[str, float]:
    """计算每款车型的独特配置加分（其他候选车型没有的配置给予额外加分）"""
    high_value_keywords = {
        "激光雷达": 3.0,
        "双零重力": 2.5,
        "零重力": 1.5,
        "4纳米": 1.2,
        "4nm": 1.2,
        "HUD": 0.8,
        "抬头显示": 0.8,
        "自动泊车": 0.6,
        "座椅通风": 0.6,
        "哨兵模式": 0.5,
        "外放电": 0.3,
        "电动尾门": 0.3,
    }

    config_texts = {}
    for mid in model_ids:
        cfg = config_cache.get(mid, {})
        text = ""
        if cfg.get("config_markdown"):
            text = cfg["config_markdown"]
        if not text and "categories" in cfg:
            for cat, params in cfg["categories"].items():
                for k, v in params.items():
                    text += f"{k}: {v} "
        config_texts[mid] = text

    bonus = {}
    for mid in model_ids:
        total = 0.0
        my_text = config_texts.get(mid, "")
        for kw, score in high_value_keywords.items():
            if kw in my_text:
                has_in_others = any(kw in config_texts.get(other, "") for other in model_ids if other != mid)
                if not has_in_others:
                    total += score
        bonus[mid] = round(total, 2)

    return bonus


def _get_config_highlights(config: dict) -> list[str]:
    """从配置数据中提取亮点关键词"""
    highlights = []
    text = ""
    if config.get("config_markdown"):
        text = config["config_markdown"]
    if not text and "categories" in config:
        for cat, params in config["categories"].items():
            for k, v in params.items():
                text += f"{k}: {v} "

    keywords = ["激光雷达", "零重力", "双零重力", "4纳米", "4nm", "HUD", "抬头显示",
                "自动泊车", "座椅通风", "哨兵模式", "外放电", "电动尾门", "全景天幕"]
    for kw in keywords:
        if kw in text:
            highlights.append(kw)
    return highlights


async def explain_decision(winner_id: str, ranked: list[dict]) -> dict:
    """生成推荐理由，引用配置数据、口碑标签和车主原话作为证据。

    Args:
        winner_id: 推荐车型的车系 ID
        ranked: score_models 返回的 rankings 列表

    Returns:
        explanation: 推荐理由文本
        unique_highlights: 独特配置亮点
        interactive: 亮点卡片数据
    """
    if not ranked:
        return {"explanation": "没有足够的车型数据进行推荐"}

    winner = next((r for r in ranked if r["model_id"] == winner_id), ranked[0])

    pros = []
    for dim, score in winner.get("dimensions", {}).items():
        if score >= 2.0:
            pros.append(f"{dim}维度得分 {score:.1f}/10")

    unique_highlights = await _extract_unique_highlights(winner_id, ranked)

    explanation = (
        f"**推荐 {winner.get('name', winner_id)}**\n"
        f"综合评分 {winner.get('overall', 0):.1f}/10\n\n"
        f"核心优势：{'；'.join(pros) if pros else '数据收集中'}\n\n"
    )

    if unique_highlights:
        explanation += "独特亮点：\n"
        for h in unique_highlights:
            explanation += f"- {h}\n"
        explanation += "\n"

    if winner.get("insufficient_data"):
        explanation += "⚠️ 该车型口碑数据不足（<5条），评分仅供参考。建议先采集更多口碑数据以获得更准确的分析。\n"

    if len(ranked) > 1:
        runner_up = ranked[1]
        explanation += f"对比第二名 {runner_up.get('name', '?')}（{runner_up.get('overall', 0):.1f}分）"

    # 构建亮点卡片数据
    highlight_items = await _build_highlight_items(winner_id, winner, ranked)

    return {
        "explanation": explanation,
        "recommended_model_id": winner_id,
        "unique_highlights": unique_highlights,
        "data_source": f"基于偏好权重加权评分（{winner.get('review_count', 0)}条口碑数据）",
        "interactive": {
            "type": "highlight_card",
            "model_name": winner.get("name", winner_id),
            "overall_score": winner.get("overall", 0),
            "highlights": highlight_items,
            "data_source": f"基于偏好权重加权评分（{winner.get('review_count', 0)}条口碑数据）",
        },
    }


async def _build_highlight_items(winner_id: str, winner: dict, ranked: list[dict]) -> list[dict]:
    """为推荐车型构建亮点卡片数据，每个亮点包含标题、表现描述、车主原话"""
    items = []

    # 从维度得分中提取优势维度
    dimensions = winner.get("dimensions", {})
    sorted_dims = sorted(dimensions.items(), key=lambda x: x[1], reverse=True)

    # 获取车主原话
    owner_quotes = await _get_owner_quotes(winner_id, limit=6)

    for dim_name, score in sorted_dims[:4]:
        if score < 1.5:
            continue

        # 根据维度名称匹配原话
        dim_quotes = [q for q in owner_quotes if _quote_matches_dimension(q, dim_name)]
        if not dim_quotes:
            dim_quotes = owner_quotes[:2]

        # 构建表现描述
        if score >= 3.0:
            performance = f"该维度得分 {score:.1f}/10，车主评价突出"
        elif score >= 2.0:
            performance = f"该维度得分 {score:.1f}/10，整体表现良好"
        else:
            performance = f"该维度得分 {score:.1f}/10"

        items.append({
            "title": f"{dim_name}优秀",
            "score": round(score, 1),
            "performance": performance,
            "quotes": dim_quotes[:3],
        })

    # 添加独特配置亮点
    unique_highlights = winner.get("unique_highlights", [])
    for hl in unique_highlights[:2]:
        items.append({
            "title": hl,
            "score": None,
            "performance": "同级罕见配置",
            "quotes": [],
        })

    return items


async def _get_owner_quotes(model_id: str, limit: int = 6) -> list[str]:
    """从口碑数据中获取代表性车主原话（best 和 worst 都查）"""
    try:
        from src.storage.db import session_scope
        from src.models.orm import OwnerReview
        with session_scope() as session:
            reviews = session.query(OwnerReview).filter(
                OwnerReview.model_id == model_id,
                or_(
                    and_(OwnerReview.best_review_text != None, OwnerReview.best_review_text != ""),
                    and_(OwnerReview.worst_review_text != None, OwnerReview.worst_review_text != ""),
                )
            ).order_by(OwnerReview.fetched_at.desc()).limit(limit).all()

            quotes = []
            for r in reviews:
                # 优先取 best_review_text，fallback 到 worst_review_text
                text = (r.best_review_text or "").strip()
                if not text:
                    text = (r.worst_review_text or "").strip()
                if text and len(text) > 10:
                    # 截取前60字作为原话
                    snippet = text[:60] + ("..." if len(text) > 60 else "")
                    quotes.append(snippet)
            return quotes
    except Exception as e:
        logger.warning(f"获取车主原话失败: {e}")
        return []


def _quote_matches_dimension(quote: str, dim_name: str) -> bool:
    """判断原话是否与某维度相关"""
    dim_keywords = {
        "外观": ["外观", "颜值", "好看", "设计", "造型"],
        "空间": ["空间", "大", "后排", "后备箱", "宽敞"],
        "配置": ["配置", "功能", "智能", "车机", "辅助"],
        "动力": ["动力", "加速", "提速", "快", "推背"],
        "续航": ["续航", "电池", "能耗", "充电", "电耗"],
        "舒适": ["舒适", "座椅", "隔音", "安静", "减震"],
        "操控": ["操控", "方向盘", "转向", "底盘"],
        "性价比": ["性价比", "价格", "实惠", "值得", "划算"],
        "安全": ["安全", "刹车", "制动", "气囊"],
        "内饰": ["内饰", "用料", "做工", "质感"],
    }
    keywords = dim_keywords.get(dim_name, [])
    return any(kw in quote for kw in keywords)


async def _extract_unique_highlights(winner_id: str, ranked: list[dict]) -> list[str]:
    """从配置数据中提取推荐车型的独特亮点（其他候选车型没有的配置）"""
    highlights = []
    try:
        from src.tools.config import get_config
        winner_config = await get_config(winner_id)

        config_text = ""
        if winner_config.get("config_markdown"):
            config_text = winner_config["config_markdown"]
        if not config_text and "categories" in winner_config:
            for cat, params in winner_config["categories"].items():
                for k, v in params.items():
                    config_text += f"{k}: {v} "

        unique_keywords = {
            "激光雷达": "搭载激光雷达（同级罕见）",
            "零重力": "配备零重力座椅（越级配置）",
            "双零重力": "配备双零重力座椅（同级唯一）",
            "4纳米": "搭载4纳米座舱芯片（同级领先）",
            "4nm": "搭载4nm座舱芯片（同级领先）",
            "HUD": "配备HUD抬头显示",
            "抬头显示": "配备HUD抬头显示",
            "全景天幕": "配备全景天幕",
            "电动尾门": "配备电动尾门",
            "座椅通风": "配备座椅通风",
            "座椅加热": "配备座椅加热",
            "无线充电": "配备无线充电",
            "360全景": "配备360°全景影像",
            "自动泊车": "支持自动泊车",
            "哨兵模式": "配备哨兵模式",
            "V2L": "支持V2L外放电",
            "外放电": "支持外放电功能",
        }

        for kw, desc in unique_keywords.items():
            if kw in config_text:
                highlights.append(desc)

        other_ids = [r["model_id"] for r in ranked if r["model_id"] != winner_id]
        for other_id in other_ids[:2]:
            other_config = await get_config(other_id)
            other_text = ""
            if other_config.get("config_markdown"):
                other_text = other_config["config_markdown"]
            if not other_text and "categories" in other_config:
                for cat, params in other_config["categories"].items():
                    for k, v in params.items():
                        other_text += f"{k}: {v} "

            truly_unique = []
            for kw, desc in unique_keywords.items():
                if kw in config_text and kw not in other_text:
                    truly_unique.append(f"{desc}——其他候选车型不具备")
            if truly_unique:
                highlights.extend(truly_unique)
                break

    except Exception as e:
        logger.warning(f"extract_unique_highlights error: {e}")

    return list(dict.fromkeys(highlights))[:5]


def _config_boost(dimension: str, config: dict) -> float:
    """Return a multiplier (0.9–1.15) based on config data backing the dimension."""
    if "error" in config:
        return 1.0
    markdown = config.get("config_markdown", "")
    if not markdown and "categories" in config:
        for cat, params in config["categories"].items():
            for k, v in params.items():
                markdown += f"{k}: {v} "
    if not markdown:
        return 1.0
    markdown_lower = markdown.lower()

    dim_keywords = {
        "续航": ["续航", "电池容量", "kwh", "工信部纯电续航", "nedc", "cltc"],
        "安全": ["气囊", "esp", "abs", "主动刹车", "车道保持", "碰撞", "安全", "激光雷达"],
        "舒适": ["轴距", "空间", "座椅", "悬挂", "空调", "天窗", "零重力"],
        "颜值": ["外观", "颜色", "轮毂", "大灯", "led", "天窗"],
        "性价比": ["指导价", "保修", "质保", "保养", "激光雷达", "零重力", "4纳米", "4nm",
                   "hud", "抬头显示", "电动尾门", "座椅通风", "座椅加热", "自动泊车",
                   "全景天幕", "无线充电", "哨兵模式", "外放电"],
    }
    keywords = dim_keywords.get(dimension, [])
    if not keywords:
        return 1.0
    matches = sum(1 for kw in keywords if kw.lower() in markdown_lower)
    return 0.9 + min(matches * 0.05, 0.25)


def _score_dimension_weighted(dimension: str, analysis: dict) -> float:
    """根据口碑数据为某维度打分（0-1），使用置信度加权。"""
    tag_map = {
        "续航": ["续航", "电池", "能耗", "用电", "充电", "电耗"],
        "安全": ["安全", "刹车", "碰撞", "气囊", "主动刹车", "激光雷达"],
        "舒适": ["空间", "舒适", "座椅", "隔音", "悬挂", "减震", "空调", "静谧", "零重力"],
        "颜值": ["外观", "颜值", "设计", "好看", "内饰", "造型", "颜色"],
        "性价比": ["性价比", "价格", "实惠", "值得", "便宜", "划算", "保值", "配置丰富"],
    }
    keywords = tag_map.get(dimension, [dimension])

    pros_weighted = 0.0
    for tag in analysis.get("top_pros", []):
        if any(kw in tag["tag"] for kw in keywords):
            confidence = tag.get("avg_confidence", 0.5)
            pros_weighted += tag["count"] * max(0.1, confidence)

    cons_weighted = 0.0
    for tag in analysis.get("top_cons", []):
        if any(kw in tag["tag"] for kw in keywords):
            confidence = tag.get("avg_confidence", 0.5)
            cons_weighted += tag["count"] * max(0.1, confidence)

    total = pros_weighted + cons_weighted
    if total == 0:
        return 0.5
    return pros_weighted / total
