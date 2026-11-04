"""车型配置查询与对比工具

改进点：
- 优先使用汽车之家内部 API（结构化 JSON，可靠快速）
- Fallback 到 crawl4ai 提取 Markdown
- 页面结构变更时不受影响，LLM 直接理解数据
"""
import asyncio
import copy
import time
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_TRIMS_CACHE: dict[str, tuple[float, dict]] = {}
_TRIMS_CACHE_TTL = 900
_CONFIG_CACHE: dict[str, tuple[float, dict]] = {}
_CONFIG_CACHE_TTL = 900

TRIM_HINTS = {
    "入门": "lowest", "基础": "lowest", "低配": "lowest",
    "顶配": "highest", "最高": "highest", "高配": "highest", "旗舰": "highest",
}


def _render_config_val(val) -> str:
    """Normalize config value for display/LLM: list[{name}] → ' / ' joined;
    dict{spec_id: val} → 'sid: rendered | sid2: rendered2'; str → as-is; None → '-'.

    Task9 的 _value_of 保留 sublist 结构后，配置值可能是 list[{"name": ...}]，
    直接 str(val) 会把 Python list/dict repr 泄漏给 LLM（如 "[{'name': '电动'}]"）。
    此函数统一归一为干净的展示字符串。
    """
    if isinstance(val, list):
        parts = []
        for item in val:
            if item is None:
                continue
            if isinstance(item, dict):
                name = item.get("name", item)
                parts.append(str(name) if name else "")
            else:
                parts.append(str(item))
        return " / ".join(p for p in parts if p) or "-"
    if isinstance(val, dict):
        # 多版本参数 {spec_id: value}：逐 spec 渲染后用 ' | ' 连接
        parts = [f"{k}: {_render_config_val(v)}" for k, v in val.items()]
        return " | ".join(parts) or "-"
    if val is None or val == "" or val == "-":
        return "-"
    return str(val)


def _parse_price(price_str: str) -> float:
    import re
    nums = re.findall(r'[\d.]+', price_str.replace(",", ""))
    return float(nums[0]) if nums else 0.0


async def _fetch_markdown(url: str) -> str:
    """通过 crawl4ai 获取页面 Markdown（fallback）"""
    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
        config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=5,
            excluded_tags=["script", "style", "nav", "footer", "header"],
            page_timeout=30000,
            wait_until="domcontentloaded",
        )
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url, config=config)
        if result and result.success:
            return result.markdown or ""
        return ""
    except ImportError:
        return ""
    except Exception as e:
        logger.debug(f"crawl4ai fetch failed for {url}: {e}")
        return ""


async def _fetch_html(url: str) -> str:
    """httpx fallback"""
    try:
        from src.scraper.fetcher import get_shared_fetcher_async
        fetcher = await get_shared_fetcher_async()
        return await fetcher.fetch_page(url)
    except Exception:
        return ""


async def get_trims(series_id: str) -> dict:
    """获取车系下所有配置版本列表（版本名、指导价、spec_id）。

    Args:
        series_id: 车系 ID

    Returns:
        trims: 版本列表
        count: 版本总数
    """
    cached = _TRIMS_CACHE.get(series_id)
    if cached and (time.time() - cached[0]) < _TRIMS_CACHE_TTL:
        return copy.deepcopy(cached[1])  # P3-38a：深拷贝，防调用方改写污染共享缓存

    try:
        from src.api.autohome_api import get_autohome_api
        api = await get_autohome_api()
        specs = await api.get_series_specs(series_id)
        if specs:
            trims = []
            for s in specs:
                trims.append({
                    "name": s["name"],
                    "price": s.get("price", ""),
                    "spec_id": s.get("spec_id", ""),
                    "series_id": series_id,
                })
            result = {"trims": trims, "series_id": series_id, "count": len(trims),
                    "data_source": f"汽车之家实时数据（{len(trims)}个版本）"}
            _TRIMS_CACHE[series_id] = (time.time(), result)
            return result
    except Exception as e:
        logger.warning(f"API get_trims failed, falling back: {e}")

    result = await _get_trims_fallback(series_id)
    _TRIMS_CACHE[series_id] = (time.time(), result)
    return result


async def _get_trims_fallback(series_id: str) -> dict:
    """crawl4ai + BS4 fallback（内部 API 不可用时）"""
    try:
        url = f"https://car.autohome.com.cn/config/series/{series_id}.html"
        md = await _fetch_markdown(url)
        html = md or await _fetch_html(url)
        if not html:
            return {
                "error": "无法获取配置页面",
                "series_id": series_id, "trims": [],
                "use_knowledge": True,
                "note": "实时数据获取失败，请用你的训练知识提供该车系的配置版本和指导价信息",
            }

        trims = []
        is_markdown = bool(md)

        if is_markdown:
            import re
            for line in html.split("\n"):
                line = line.strip()
                if not line:
                    continue
                price_match = re.search(r'[\d.]+万', line)
                if price_match and len(line) < 200:
                    parts = re.split(r'\s*\|\s*|\s{2,}', line)
                    name = parts[0].strip() if parts else line[:60]
                    price = price_match.group(0)
                    trims.append({"name": name, "price": price, "series_id": series_id})
        else:
            soup = BeautifulSoup(html, "html.parser")
            for item in soup.select("tr, div.config-row, div.trim-item"):
                cells = item.select("td, th, span")
                if len(cells) >= 2:
                    name = cells[0].text.strip()
                    price = cells[1].text.strip() if len(cells) > 1 else ""
                    if name and ("万" in name or "万" in price or "版" in name or "型" in name):
                        trims.append({"name": name, "price": price, "series_id": series_id})

        if not trims:
            trims = [{"name": "配置信息见原始内容", "price": "", "series_id": series_id,
                      "raw_markdown": md[:3000] if md else html[:3000] if isinstance(html, str) else ""}]

        return {"trims": trims, "series_id": series_id, "count": len(trims)}
    except Exception as e:
        logger.error(f"get_trims fallback error: {e}")
        return {"error": str(e), "trims": [], "series_id": series_id}


async def find_trim(series_id: str, description: str = "基础款") -> dict:
    """模糊匹配配置版本名，支持"入门/低配"匹配最低价版本，"顶配/高配/旗舰"匹配最高价版本。

    Args:
        series_id: 车系 ID
        description: 版本描述（如"入门款"、"顶配"、"510KM 旗舰型"）
    """
    try:
        desc_lower = description.lower()
        for kw, strategy in TRIM_HINTS.items():
            if kw in desc_lower:
                result = await get_trims(series_id)
                trims = result.get("trims", [])
                if not trims:
                    return {"error": "无法获取版本列表", "series_id": series_id}
                try:
                    priced = [t for t in trims if t.get("price") and "万" in str(t.get("price", ""))]
                    if strategy == "lowest":
                        match = min(priced, key=lambda t: _parse_price(t["price"])) if priced else trims[0]
                    else:
                        match = max(priced, key=lambda t: _parse_price(t["price"])) if priced else trims[-1]
                except Exception:
                    match = trims[0] if strategy == "lowest" else trims[-1]
                return {"matched_trim": match, "series_id": series_id, "match_type": strategy}

        result = await get_trims(series_id)
        trims = result.get("trims", [])
        for t in trims:
            if desc_lower in t["name"].lower():
                return {"matched_trim": t, "series_id": series_id, "match_type": "name"}

        return {"matched_trim": trims[0] if trims else None, "series_id": series_id,
                "match_type": "fallback", "note": f"未精确匹配'{description}'，返回首个版本"}
    except Exception as e:
        logger.error(f"find_trim error: {e}")
        return {"error": str(e), "series_id": series_id}


async def get_config(model_id: str, spec_id: str | None = None) -> dict:
    """获取车型完整配置参数，按分类返回（基本参数、车身、动力、电池、辅助配置等）。

    Args:
        model_id: 车系 ID（series_id）
        spec_id: 具体版本 ID（可选，按版本筛选展示；不传或该版本端点不可用时返回车系全版本对比配置）

    Returns:
        categories: 各类别配置参数（如 {"基本参数": {"长×宽×高": "...", ...}, ...}）
    """
    # spec_id 端点(GetConfigNew.ashx)已失效，统一用车系级 get_full_config
    # （含全版本参数对比，更适合配置差异查询）；spec_id 仅用于结果标注
    cached = _CONFIG_CACHE.get(model_id)
    if cached and (time.time() - cached[0]) < _CONFIG_CACHE_TTL:
        return copy.deepcopy(cached[1])  # P3-38a：深拷贝，防调用方改写污染共享缓存

    try:
        from src.api.autohome_api import get_autohome_api
        api = await get_autohome_api()
        config = await api.get_full_config(model_id)
        if config and "categories" in config and config["categories"]:
            config["data_source"] = "汽车之家实时配置数据"
            if spec_id:
                config["focus_spec_id"] = spec_id
                config["note"] = f"已聚焦版本 {spec_id}，结果为车系全版本配置对比（spec 级端点已停用）"
            _CONFIG_CACHE[model_id] = (time.time(), config)
            return config
        if config and "error" in config:
            logger.warning(f"API get_config failed: {config.get('error')}")
    except Exception as e:
        logger.warning(f"API get_config failed, falling back: {e}")

    result = await _get_config_fallback(model_id)
    _CONFIG_CACHE[model_id] = (time.time(), result)
    return result


async def _get_config_fallback(model_id: str) -> dict:
    """crawl4ai + BS4 fallback（内部 API 不可用时）"""
    try:
        url = f"https://car.autohome.com.cn/config/series/{model_id}.html"
        md = await _fetch_markdown(url)

        if md:
            return {
                "model_id": model_id,
                "url": url,
                "config_markdown": md[:10000],
                "format": "markdown",
                "source": "crawl4ai",
            }

        html = await _fetch_html(url)
        if not html:
            return {
                "error": "无法获取配置页面", "model_id": model_id, "url": url,
                "use_knowledge": True,
                "note": "实时配置数据获取失败，请用你的训练知识提供该车型的配置参数",
            }

        soup = BeautifulSoup(html, "html.parser")
        config = {"model_id": model_id, "url": url, "categories": {}, "format": "html_parsed"}

        current_category = "基本参数"
        for table in soup.select("table"):
            for row in table.select("tr"):
                cat_el = row.select_one("th.category, .group-title")
                if cat_el:
                    current_category = cat_el.text.strip()
                    config["categories"].setdefault(current_category, {})
                    continue
                cells = row.select("td, th")
                if len(cells) >= 2:
                    k, v = cells[0].text.strip(), cells[1].text.strip()
                    if k and v and len(k) < 50:
                        config["categories"].setdefault(current_category, {})[k] = v

        if not config["categories"]:
            config["note"] = "配置页解析未获取到结构化数据"
            config["page_text"] = soup.get_text()[:8000]

        return config
    except Exception as e:
        logger.error(f"get_config fallback error: {e}")
        return {"error": str(e), "model_id": model_id}

def _build_compare_table_data(filtered_diff: dict, model_names: dict, configs: dict,
                               spec_to_series: dict | None = None) -> list:
    """将差异配置数据转换为前端对比表格所需的格式

    filtered_diff 中的值 dict 可能有两种 key:
    - series_id (单值参数，如 "厂商")
    - 版本名称 (多值参数，如 "PLUS 2025款 智驾 430KM 领先型")
    spec_to_series 用于将版本名称映射回 series_id
    """
    key_cats = ["基本参数", "车身", "电动机", "电池/充电", "辅助/操控配置", "外部/防盗配置", "内部/舒适配置"]
    categories = []
    for cat in key_cats:
        if cat not in filtered_diff:
            continue
        items = []
        for k, vals in list(filtered_diff[cat].items())[:15]:
            row = {"param": k, "values": []}
            for mid in configs.keys():
                name = model_names.get(mid, mid)
                val = vals.get(mid, "-")
                if val == "-":
                    if spec_to_series:
                        matched_vals = [v for spec_name, v in vals.items()
                                        if spec_to_series.get(spec_name) == mid]
                        if matched_vals:
                            val = matched_vals[0]
                        else:
                            val = vals.get(name, "-")
                    else:
                        val = vals.get(name, "-")
                row["values"].append({"model": name, "value": _render_config_val(val)})
            items.append(row)
        if items:
            categories.append({"name": cat, "items": items})
    return categories


async def compare_configs(model_ids: list[str]) -> dict:
    """2-4款车型配置横向对比，自动提取差异项并生成对比总结。

    Args:
        model_ids: 车系 ID 列表（2-4个）

    Returns:
        differences: 仅包含存在差异的参数
        summary_markdown: 关键差异摘要
        interactive: 前端对比表格数据
    """
    if len(model_ids) < 2 or len(model_ids) > 4:
        return {"error": "请提供 2-4 个车型 ID", "model_ids": model_ids}

    try:
        from src.api.autohome_api import get_autohome_api
        api = await get_autohome_api()
        results = await asyncio.gather(*[api.get_full_config(mid) for mid in model_ids])

        configs, errors = {}, []
        for mid, cfg in zip(model_ids, results):
            if "error" in cfg and "categories" not in cfg:
                errors.append(mid)
            else:
                configs[mid] = cfg

        if configs:
            all_mids = list(configs.keys())
            specs_results = await asyncio.gather(*[api.get_series_specs(mid) for mid in all_mids])
            info_results = await asyncio.gather(*[api.get_series_info(mid) for mid in all_mids])

            spec_name_map = {}
            spec_to_series = {}
            for mid, specs in zip(all_mids, specs_results):
                for s in specs:
                    sid = str(s.get("spec_id", ""))
                    sname = s.get("name", sid)
                    if sid:
                        spec_name_map[sid] = sname
                        spec_to_series[sname] = mid

            model_names = {}
            for mid, info in zip(all_mids, info_results):
                model_names[mid] = info.get("name", mid)

            diff = {}
            for cfg in configs.values():
                mid = cfg.get("series_id", cfg.get("model_id", "?"))
                for cat, params in cfg.get("categories", {}).items():
                    diff.setdefault(cat, {})
                    for k, v in params.items():
                        if isinstance(v, dict):
                            named_v = {}
                            for sid, val in v.items():
                                name = spec_name_map.get(str(sid), str(sid))
                                named_v[name] = val
                            diff[cat].setdefault(k, {}).update(named_v)
                        else:
                            diff[cat].setdefault(k, {})[mid] = v

            filtered_diff = {}
            for cat, params in diff.items():
                for k, vals in params.items():
                    if isinstance(vals, dict):
                        unique_vals = set(_render_config_val(v) for v in vals.values())
                        if len(unique_vals) > 1:
                            filtered_diff.setdefault(cat, {})[k] = vals

            summary_parts = []
            summary_parts.append("## 对比总结\n")
            key_diff_cats = ["基本参数", "车身", "发动机", "电动机", "电池/充电", "辅助/操控配置"]
            for cat in key_diff_cats:
                if cat in filtered_diff:
                    items = filtered_diff[cat]
                    if items:
                        summary_parts.append(f"### {cat}差异")
                        for k, vals in list(items.items())[:8]:
                            val_str = " | ".join(f"{n}: {_render_config_val(v)}" for n, v in vals.items())
                            summary_parts.append(f"- **{k}**: {val_str}")
                        summary_parts.append("")

            all_markdown = "---\n".join(
                f"## {model_names.get(cfg.get('series_id', cfg.get('model_id', '')), cfg.get('series_id', cfg.get('model_id', '')))}\n"
                + "\n".join(
                    f"### {cat}\n"
                    + "\n".join(f"- {k}: {_render_config_val(v)}" for k, v in params.items())
                    for cat, params in cfg.get("categories", {}).items()
                )
                for cfg in configs.values()
            )

            result = {
                "model_ids": model_ids,
                "model_names": model_names,
                "differences": filtered_diff,
                "summary_markdown": "\n".join(summary_parts) if summary_parts else "",
                "combined_markdown": all_markdown[:15000] if all_markdown else "",
                "source": "autohome_api",
                "data_source": f"汽车之家实时配置数据（{len(configs)}款车型对比）",
                "note": "仅展示存在差异的参数行；summary_markdown 为关键差异总结",
                "interactive": {
                    "type": "config_compare",
                    "models": [{"id": mid, "name": model_names.get(mid, mid)} for mid in configs.keys()],
                    "categories": _build_compare_table_data(filtered_diff, model_names, configs, spec_to_series),
                    "data_source": f"汽车之家实时配置数据（{len(configs)}款车型对比）",
                },
            }
            if errors:
                result["errors"] = {mid: "获取配置失败" for mid in errors}
            return result
    except Exception as e:
        logger.warning(f"API compare_configs failed, falling back: {e}")

    return await _compare_configs_fallback(model_ids)


async def _compare_configs_fallback(model_ids: list[str]) -> dict:
    """crawl4ai fallback 对比方案"""
    results = await asyncio.gather(*[_get_config_fallback(mid) for mid in model_ids])
    configs, errors = {}, []
    for mid, cfg in zip(model_ids, results):
        if "error" in cfg:
            errors.append(mid)
        else:
            configs[mid] = cfg

    all_markdown = "---\n".join(
        f"## {cfg.get('model_id', '')}\n{cfg.get('config_markdown', '')}"
        for cfg in configs.values()
    )

    diff = {}
    for cfg in configs.values():
        mid = cfg.get("model_id", "?")
        for cat, params in cfg.get("categories", {}).items():
            diff.setdefault(cat, {})
            for k, v in params.items():
                diff[cat].setdefault(k, {})[mid] = v

    filtered_diff = {}
    for cat, params in diff.items():
        for k, vals in params.items():
            unique_vals = set(_render_config_val(v) for v in vals.values())
            if len(unique_vals) > 1:
                filtered_diff.setdefault(cat, {})[k] = vals

    result = {
        "model_ids": model_ids,
        "differences": filtered_diff,
        "combined_markdown": all_markdown[:15000] if all_markdown else "",
        "source": "crawl4ai_fallback",
        "data_source": f"汽车之家配置页面（{len(configs)}款车型对比，crawl4ai解析）",
        "note": "仅展示存在差异的参数行；Markdown 包含完整配置供 LLM 深度分析",
    }
    if errors:
        result["errors"] = {mid: "获取配置失败" for mid in errors}
    return result
