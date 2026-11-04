"""市场研究工具：销量、趋势、竞品矩阵、导出、周期调度"""
import asyncio
import json
import csv
import logging
import os
import re
from datetime import datetime
from pathlib import Path

import httpx

from sqlalchemy import func

logger = logging.getLogger(__name__)

EXPORT_DIR = Path("data/exports")

_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.autohome.com.cn/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_shared_client: httpx.AsyncClient | None = None

# 汽车之家段位中文名 → rank 页面 levelid 映射
_LEVEL_NAME_TO_ID = {
    "微型车": 1, "小型车": 2, "紧凑型车": 3, "中型车": 4,
    "中大型车": 5, "大型车": 6,
    "小型SUV": 16, "紧凑型SUV": 17, "中型SUV": 18,
    "中大型SUV": 19, "大型SUV": 20,
    "紧凑型MPV": 21, "中型MPV": 22, "中大型MPV": 23, "大型MPV": 24,
    "微面": 11,
    "跑车": 7, "皮卡": 8, "轻客": 9, "微卡": 10,
}


async def _get_http_client() -> httpx.AsyncClient:
    """获取共享 httpx 客户端"""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            headers=_HTTP_HEADERS,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )
    return _shared_client


def _price_to_range(price_str: str) -> str:
    """将价格字符串转为 rank URL 的价格区间，如 '6.48-9.48万' → '0_9000'"""
    try:
        nums = re.findall(r'[\d.]+', price_str)
        if nums:
            max_price = max(float(n) for n in nums)
            return f"0_{int(max_price * 10000)}"
    except Exception:
        pass
    return "0_900000"  # fallback: 0-900万（覆盖所有）


async def get_sales_data(model_id: str, months: int = 6) -> dict:
    """获取车型月度销量数据和同级排名。

    数据来源：汽车之家排行榜页面 Next.js SSR 内嵌的 __NEXT_DATA__ JSON。
    按车型段位构造排行榜 URL，抓取页面提取销量。

    Args:
        model_id: 车系 ID
        months: 查询月数（默认6个月，实际最多返回页面可用的月份数）

    Returns:
        sales: 月度销量列表 [{month, volume, rank}]
    """
    client = await _get_http_client()
    now = datetime.now()

    # 1. 获取车系段位信息
    level_name = ""
    series_name = ""
    try:
        from src.api.autohome_api import get_autohome_api
        api = await get_autohome_api()
        detail = await api.get_model_detail(model_id)
        if detail and "error" not in detail:
            level_name = detail.get("level", "")
            series_name = detail.get("name", "")
    except Exception as e:
        logger.debug(f"获取车系信息失败: {e}")

    level_id = _LEVEL_NAME_TO_ID.get(level_name, 0)

    # 2. 抓取排行榜页面提取销量（仅最新月份）
    sales_list = []
    used_source = ""
    found_rank = 0

    urls_to_try = [(f"https://www.autohome.com.cn/rank/1", "全车型主榜")]
    if level_id:
        urls_to_try.append(
            (f"https://www.autohome.com.cn/rank/1-1-{level_id}-0_900000-x-x-x/{now.strftime('%Y-%m')}.html",
             f"{level_name}榜")
        )

    for url, label in urls_to_try:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                continue

            match = re.search(
                r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
                resp.text, re.DOTALL
            )
            if not match:
                continue

            page_data = json.loads(match.group(1))
            props = page_data.get("props", {}).get("pageProps", {})
            rank_list = props.get("listRes", {}).get("list", [])
            page_date = props.get("initialValues", {}).get("date", now.strftime("%Y-%m"))

            for item in rank_list:
                if str(item.get("seriesid", "")) == model_id:
                    sales_list.append({
                        "month": page_date,
                        "volume": int(item.get("salecount", 0)),
                        "rank": int(item.get("rank", 0)),
                    })
                    found_rank = item.get("rank", found_rank)
                    series_name = item.get("seriesname", series_name)
                    if not used_source:
                        used_source = f"汽车之家排行榜SSR数据（{label}）"
                    break
        except Exception as e:
            logger.debug(f"排行榜抓取失败 ({label}): {e}")

        if sales_list:
            break

    if sales_list:
        return {
            "model_id": model_id,
            "model_name": series_name,
            "sales": sales_list,
            "rank": found_rank,
            "count": len(sales_list),
            "source": used_source,
            "status": "available",
        }

    return {
        "model_id": model_id,
        "model_name": series_name,
        "sales": [],
        "status": "not_found",
        "note": (
            "该车型未出现在汽车之家排行榜前20名中，"
            "可能是月度销量较低或为新上市车型。"
            "可尝试访问 https://www.autohome.com.cn/rank/1 查看完整排行榜。"
        ),
        "data_source": "autohome_rank_page",
    }


async def get_review_trends(model_id: str, period: str = "6m") -> dict:
    """口碑数量和正面标签的时间变化趋势。

    Args:
        model_id: 车系 ID
        period: 查询周期（如"6m"=6个月）
    """
    try:
        from src.storage.db import session_scope
        from src.models.orm import OwnerReview, ReviewTag

        with session_scope() as session:
            # coalesce: 优先 post_date，fallback 到 fetched_at 格式化为日期字符串
            date_col = func.coalesce(OwnerReview.post_date,
                                     func.strftime("%Y-%m-%d", OwnerReview.fetched_at))
            month_expr = func.strftime("%Y-%m", date_col).label("month")

            reviews = (
                session.query(month_expr, func.count().label("cnt"))
                .filter(OwnerReview.model_id == model_id)
                .group_by("month").order_by("month").all()
            )

            pros_trend = (
                session.query(
                    func.strftime("%Y-%m", date_col).label("month"),
                    func.count().label("cnt")
                )
                .select_from(ReviewTag)
                .join(OwnerReview, ReviewTag.review_id == OwnerReview.review_id)
                .filter(ReviewTag.model_id == model_id, ReviewTag.sentiment == "pro")
                .group_by("month").order_by("month").all()
            )

        return {
            "model_id": model_id,
            "review_volume_by_month": [{"month": r[0], "count": r[1]} for r in reviews],
            "positive_tag_trend": [{"month": p[0], "count": p[1]} for p in pros_trend],
            "note": "趋势数据基于口碑发布时间",
        }
    except Exception as e:
        logger.error(f"get_review_trends error: {e}")
        return {"error": str(e), "model_id": model_id}


async def get_competitive_matrix(segment: str = "") -> dict:
    """生成细分市场竞品矩阵，搜索该级别所有车型并对比口碑。

    Args:
        segment: 细分市场关键词（如"10-15万纯电SUV"、"紧凑型新能源轿车"）
    """
    try:
        from src.tools.search import search_cars
        from src.tools.reviews import get_review_analysis
        keyword = segment.strip() if segment else ""
        if not keyword:
            return {"error": "请提供细分市场关键词，例如：9-12万纯电SUV、紧凑型新能源轿车", "segment": segment}
        search_result = await search_cars(keyword=keyword)
        models = search_result.get("models", [])[:8]

        if not models:
            return {"segment": segment, "models": [], "count": 0,
                    "note": f"未找到与'{keyword}'匹配的车型，请尝试其他关键词"}

        sem = asyncio.Semaphore(4)

        async def _analyze_one(m):
            async with sem:
                mid = m.get("series_id", "")
                if not mid:
                    return None
                try:
                    analysis = await get_review_analysis(mid, skip_background=True)
                    pros = [p["tag"] for p in analysis.get("top_pros", [])[:3]]
                    cons = [c["tag"] for c in analysis.get("top_cons", [])[:3]]
                    return {
                        "model_name": m.get("name", mid),
                        "model_id": mid,
                        "review_count": analysis.get("review_count", 0),
                        "top_pros": pros,
                        "top_cons": cons,
                    }
                except Exception as e:
                    logger.warning(f"分析车型 {mid} 口碑失败: {e}")
                    return {
                        "model_name": m.get("name", mid),
                        "model_id": mid,
                        "review_count": 0,
                        "top_pros": [],
                        "top_cons": [],
                        "note": "口碑分析失败",
                    }

        results = await asyncio.gather(*[_analyze_one(m) for m in models])
        matrix = [r for r in results if r is not None]

        return {"segment": segment, "models": matrix, "count": len(matrix)}
    except Exception as e:
        logger.error(f"get_competitive_matrix error: {e}")
        return {"error": str(e), "segment": segment}


def _sanitize_csv_row(row: dict, headers: list) -> dict:
    """Prevent CSV formula injection by prefixing dangerous chars with single quote."""
    dangerous_prefixes = ("=", "+", "-", "@")
    result = {}
    for h in headers:
        val = row.get(h, "")
        if isinstance(val, str) and val.startswith(dangerous_prefixes):
            val = "'" + val
        result[h] = val
    return result


ALLOWED_EXPORT_FORMATS = {"json", "csv", "xlsx"}


async def export_data(data: dict, format: str = "json") -> dict:
    """导出结构化数据为 JSON/CSV/Excel"""
    if format not in ALLOWED_EXPORT_FORMATS:
        return {"error": f"不支持的格式: {format}，支持: {', '.join(sorted(ALLOWED_EXPORT_FORMATS))}"}

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    import time
    ts = int(time.time())

    if format == "csv":
        path = EXPORT_DIR / f"export_{ts}.csv"
        rows = data.get("rows", [])
        headers = data.get("headers", [])
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows([_sanitize_csv_row(r, headers) for r in rows])
    elif format == "xlsx":
        try:
            import openpyxl
            path = EXPORT_DIR / f"export_{ts}.xlsx"
            wb = openpyxl.Workbook()
            ws = wb.active
            rows = data.get("rows", [])
            headers = data.get("headers", [])
            if headers:
                ws.append(headers)
            for row in rows:
                ws.append([row.get(h, "") for h in headers] if headers else list(row.values()))
            wb.save(str(path))
        except ImportError:
            return {"error": "openpyxl 未安装，请安装后重试: pip install openpyxl"}
    else:
        path = EXPORT_DIR / f"export_{ts}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return {"format": format, "path": str(path), "filename": path.name}


async def schedule_task(task_type: str = "", model_id: str = "", frequency: str = "weekly",
                         action: str = "create", task_id: str = "") -> dict:
    """创建/查询/暂停/删除周期性任务。持久化到 SQLite TaskRecord。

    注意：后台定时执行暂未实现，任务仅记录配置。如需立即采集，请调用 fetch_reviews。
    """
    from src.storage.db import session_scope
    from src.models.orm import TaskRecord

    if action == "create":
        tid = f"sched_{model_id or 'task'}_{frequency}"
        with session_scope() as s:
            existing = s.query(TaskRecord).filter_by(task_id=tid).first()
            if existing:
                existing.status = "active"
                existing.progress = f"{task_type} | {frequency}"
            else:
                s.add(TaskRecord(task_id=tid, status="active", progress=f"{task_type} | {frequency}"))
        return {
            "task_id": tid, "status": "active",
            "message": f"已创建{frequency}采集任务",
            "note": "后台调度暂未实现，任务配置已持久化。",
        }
    elif action == "list":
        return {"tasks": [], "note": "使用 task_id 查询具体任务状态"}
    elif action == "pause":
        if not task_id:
            return {"error": "请提供有效的 task_id"}
        with session_scope() as s:
            t = s.query(TaskRecord).filter_by(task_id=task_id).first()
            if t is None:
                return {"error": "任务不存在"}
            t.status = "paused"
        return {"status": "paused", "task_id": task_id}
    elif action == "delete":
        if not task_id:
            return {"error": "请提供有效的 task_id"}
        with session_scope() as s:
            t = s.query(TaskRecord).filter_by(task_id=task_id).first()
            if t is None:
                return {"error": "任务不存在"}
            t.status = "deleted"
        return {"status": "deleted", "task_id": task_id}
    return {"error": "未知操作，支持: create/list/pause/delete"}


async def generate_report(series_id: str, report_type: str = "purchase") -> dict:
    """生成车型购车分析报告，整合配置、口碑、评分等数据

    report_type: purchase（购车建议报告）, compare（对比报告，需配合 compare_configs 使用）, market（市场分析报告）
    """
    try:
        from src.tools.search import get_model_detail
        from src.tools.config import get_trims, get_config
        from src.tools.reviews import get_review_analysis
        from src.tools.decision import score_models

        detail = await get_model_detail(series_id)
        if "error" in detail and "name" not in detail:
            return {"error": f"无法获取车型信息: {detail.get('error', '')}", "series_id": series_id}

        model_name = detail.get("name", series_id)
        price_range = detail.get("price_range", "暂无")
        level = detail.get("level", "未知")
        energy_type = detail.get("energy_type", "未知")

        trims_result = await get_trims(series_id)
        trims = trims_result.get("trims", [])

        analysis = await get_review_analysis(series_id, skip_background=True)
        review_count = analysis.get("review_count", 0)
        top_pros = analysis.get("top_pros", [])
        top_cons = analysis.get("top_cons", [])

        config_result = await get_config(series_id)
        config_data = config_result if "error" not in config_result else None

        score_result = await score_models([series_id])
        rankings = score_result.get("rankings", [])
        model_score = rankings[0] if rankings else None

        report_sections = []
        report_sections.append(f"# {model_name} 购车分析报告\n")
        report_sections.append(f"## 一、车型概览\n")
        report_sections.append(f"- **车型名称**: {model_name}")
        report_sections.append(f"- **级别**: {level}")
        report_sections.append(f"- **能源类型**: {energy_type}")
        report_sections.append(f"- **指导价**: {price_range}")
        report_sections.append(f"- **在售版本数**: {len(trims)}")
        report_sections.append("")

        if trims:
            report_sections.append("## 二、版本价格一览\n")
            report_sections.append("| 版本 | 指导价 |")
            report_sections.append("|------|--------|")
            for t in trims[:10]:
                name = t.get("name", "")
                price = t.get("price", "暂无")
                report_sections.append(f"| {name} | {price} |")
            report_sections.append("")

        if top_pros or top_cons:
            report_sections.append("## 三、车主口碑分析\n")
            report_sections.append(f"> 📊 基于 **{review_count}条** 车主真实评价\n")
            if review_count < 5:
                report_sections.append("> ⚠️ 口碑样本不足，分析结果仅供参考\n")
            if top_pros:
                report_sections.append("### ✅ 买点 Top5")
                for i, p in enumerate(top_pros[:5], 1):
                    report_sections.append(f"{i}. **{p['tag']}** — 提及{p['count']}次")
                report_sections.append("")
            if top_cons:
                report_sections.append("### ❌ 槽点 Top5")
                for i, c in enumerate(top_cons[:5], 1):
                    report_sections.append(f"{i}. **{c['tag']}** — 提及{c['count']}次")
                report_sections.append("")

        if config_data:
            report_sections.append("## 四、核心配置参数\n")
            categories = config_data.get("categories", {})
            spec_name_map = {}
            for t in trims:
                sid = str(t.get("spec_id", ""))
                if sid:
                    spec_name_map[sid] = t.get("name", sid)
            key_categories = ["基本参数", "车身", "发动机", "电动机", "电池/充电", "变速箱", "底盘转向", "车轮制动", "辅助/操控配置", "外部/防盗配置", "内部/舒适配置"]
            for cat_name in key_categories:
                if cat_name in categories:
                    params = categories[cat_name]
                    report_sections.append(f"### {cat_name}")
                    for k, v in list(params.items())[:15]:
                        if isinstance(v, str):
                            report_sections.append(f"- {k}: {v}")
                        elif isinstance(v, dict):
                            vals = []
                            for sid, val in list(v.items())[:3]:
                                name = spec_name_map.get(str(sid), str(sid))
                                short_name = name.replace("UP 2025款 ", "").replace("UP 2026款 ", "")
                                vals.append(f"{short_name}={val}")
                            report_sections.append(f"- {k}: {', '.join(vals)}")
                    report_sections.append("")

        if model_score:
            report_sections.append("## 五、综合评分\n")
            report_sections.append(f"**综合得分**: {model_score.get('overall', 0):.1f}/10\n")
            dims = model_score.get("dimensions", {})
            if dims:
                report_sections.append("| 维度 | 得分 |")
                report_sections.append("|------|------|")
                for dim, score in dims.items():
                    report_sections.append(f"| {dim} | {score:.1f} |")
                report_sections.append("")

        report_sections.append("## 六、购买建议\n")
        if review_count > 5 and top_pros:
            best_pro = top_pros[0]["tag"]
            report_sections.append(f"基于 **{review_count}条** 车主真实反馈，{model_name}的最大优势是**{best_pro}**。")
        if top_cons:
            worst_con = top_cons[0]["tag"]
            report_sections.append(f"需注意的主要槽点是**{worst_con}**。")
        if trims and len(trims) > 1:
            priced = [t for t in trims if t.get("price") and "万" in str(t.get("price", ""))]
            if priced:
                import re
                def _extract_price(price_str):
                    nums = re.findall(r'[\d.]+', str(price_str).replace(",", ""))
                    return float(nums[0]) if nums else 0.0

                lowest = min(priced, key=lambda t: _extract_price(t["price"]))
                highest = max(priced, key=lambda t: _extract_price(t["price"]))
                report_sections.append(f"预算有限推荐**{lowest['name']}**（{lowest['price']}），追求全面配置推荐**{highest['name']}**（{highest['price']}）。")
        report_sections.append("")
        report_sections.append("> 📊 数据来源：" + f"{review_count}条车主口碑 + 汽车之家配置数据")

        report_text = "\n".join(report_sections)

        return {
            "series_id": series_id,
            "model_name": model_name,
            "report_type": report_type,
            "report_markdown": report_text,
            "data_source": f"{review_count}条车主口碑 + 汽车之家配置数据",
            "summary": {
                "name": model_name,
                "price_range": price_range,
                "level": level,
                "energy_type": energy_type,
                "review_count": review_count,
                "trim_count": len(trims),
                "top_pros": [p["tag"] for p in top_pros[:3]],
                "top_cons": [c["tag"] for c in top_cons[:3]],
                "overall_score": model_score.get("overall", 0) if model_score else 0,
            },
        }
    except Exception as e:
        logger.error(f"generate_report error: {e}")
        return {"error": str(e), "series_id": series_id}
