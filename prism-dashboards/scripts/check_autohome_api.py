"""汽车之家上游 API 存活检查

逐个实测本项目依赖的全部汽车之家端点（走 src/api/autohome_api.py 真实代码路径），
用于回答"API 现在还能不能调"。用法：
    .venv/Scripts/python.exe scripts/check_autohome_api.py [series_id]
"""
from __future__ import annotations

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.api.autohome_api import get_autohome_api, close_autohome_api

SERIES_ID = sys.argv[1] if len(sys.argv) > 1 else "6998"  # 默认铂智3X


async def main():
    api = await get_autohome_api()
    results: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str):
        results.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'} | {name} | {detail}")

    # 1. 品牌/车系字母索引页（search_cars / 车系索引的数据源）
    series_list = await api._fetch_series_by_letter("A")
    record("字母索引页 grade/carhtml/A.html", bool(series_list),
           f"{len(series_list)} 个车系，示例: {series_list[0]['name'] if series_list else '-'}")

    # 2. 车系配置页（get_series_info / get_trims / get_full_config 数据源）
    info = await api.get_series_info(SERIES_ID)
    has_config = "config_data" in info and "error" not in info
    record("车系配置页 config/series/{id}.html", has_config,
           f"name={info.get('name')} config嵌入={('config_data' in info)} option嵌入={('option_data' in info)}")

    # 3. 版本列表（配置页衍生）
    specs = await api.get_series_specs(SERIES_ID)
    record("版本列表 get_series_specs", bool(specs), f"{len(specs)} 个版本，首个: {specs[0]['name'] if specs else '-'}")

    # 4. GetConfigNew.ashx 结构化配置
    if specs:
        spec_id = specs[0]["spec_id"]
        cfg = await api.get_config_by_specid(spec_id, "base")
        data = cfg.get("data")
        ok = isinstance(data, dict) and "error" not in cfg
        record("GetConfigNew.ashx", ok,
               f"specid={spec_id} 返回keys={list(data.keys())[:5] if isinstance(data, dict) else data}")
    else:
        record("GetConfigNew.ashx", False, "无版本可测（上游失败）")

    # 5. 口碑汇总（口碑 API 页级数据）
    summary = await api.get_series_summary(SERIES_ID)
    ok = "error" not in summary and summary.get("review_count", 0) >= 0 and summary.get("series_name")
    record("口碑汇总 koubeiipv6 series/list", ok,
           f"{summary.get('series_name')} 口碑数={summary.get('review_count')} 均分={summary.get('average_score')}")

    # 6. 口碑列表采集（fetch_reviews 数据源）
    page = await api.fetch_koubei_page(SERIES_ID, 1, 5)
    items = page.get("list", []) if page else []
    sample_txt = ""
    if items:
        parsed = api.parse_koubei_item(items[0])
        sample_txt = (parsed.get("best_review_text", "") or "")[:30]
    record("口碑列表采集 fetch_koubei_page", bool(items),
           f"本页 {len(items)} 条，首条最满意摘要: {sample_txt or '(空)'}")

    # 7. 资讯接口 AjaxGetNewsList.ashx（含回退链）
    news = await api.search_news(SERIES_ID)
    record("资讯 search_news（含回退链）", bool(news.get("articles")),
           f"{news.get('count')} 条，source={news.get('source')}，note={news.get('note', '')}")

    # 8. 车系首页（资讯回退1的数据源）
    homepage = await api._get_text(f"https://www.autohome.com.cn/{SERIES_ID}/")
    record("车系首页 /{id}/", len(homepage) > 10000, f"HTML 长度 {len(homepage)}")

    # 9. 销量 rank 页 SSR（market.get_sales_data 数据源）
    from src.tools.market import get_sales_data
    sales = await get_sales_data(SERIES_ID, months=3)
    sales_rows = sales.get("sales", sales.get("data", []))
    record("销量 rank 页 SSR (market.get_sales_data)", bool(sales_rows) and "error" not in sales,
           f"返回keys={list(sales.keys())[:6]} 行数={len(sales_rows) if isinstance(sales_rows, list) else sales_rows}")

    await close_autohome_api()

    n_ok = sum(1 for _, ok, _ in results if ok)
    print(f"\n===== 汇总: {n_ok}/{len(results)} 通过 =====")
    for name, ok, detail in results:
        if not ok:
            print(f"  未通过: {name} -> {detail}")


if __name__ == "__main__":
    asyncio.run(main())
