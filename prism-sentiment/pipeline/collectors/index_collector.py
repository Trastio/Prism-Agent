"""IndexCollector —— 多平台搜索指数采集（2026-09-12，替代已死的 gopup 百度指数）。

数据源（09-12 index_probe.py 付费实测，产物 logs/tikhub_test/probe/）：
- 抖音：douyin/index/fetch_multi_keyword_hot_trend（POST + **query** 参数，
  GET 会 405）——keyword_list 逗号分隔一次多词、起止日期 YYYYMMDD、
  app_name=aweme（toutiao 是同款端点的另一平台）。$0.003/次（词数不影响）。
  响应 data.hot_list[]：{keyword（小写回显）, hot_list[{datetime "20260813",
  index "2440"（字符串）}]}。
- 小红书：xiaohongshu/pgy/get_keyword_daily（POST JSON {search_word}）。
  $0.02/次，**查无结果也计费、官方明确不要重试**；时间范围固定近三个月
  （无时间参数，超出采集窗的历史点照存，白赚回溯）；三层信封
  resp.data.data.dailyData[]：{dateKey "2026-06-12", searchScore "190"
  （字符串），noteNum/userNum/impNum 等富字段}。
- 微博/快手：无关键词级指数端点（车型词多数不在热搜榜），按 2026-09-11
  评估结论暂不采。

返回统一点位 dict：{date: "YYYY-MM-DD", keyword, source, index: float}，
scheduler._store_search_index 落 SearchIndexMetric 表。
"""

from __future__ import annotations

import logging
from datetime import date

from pipeline.collectors.tikhub_collector import TikHubClient, TikHubError

logger = logging.getLogger(__name__)

# 抖音指数日期格式 YYYYMMDD ↔ 存储 ISO YYYY-MM-DD
_DY_DATE = "%Y%m%d"


class IndexCollector:
    """搜索指数采集器（抖音 + 小红书；接口形态差异封装在本层）。"""

    def __init__(self, client: TikHubClient | None = None) -> None:
        self._client = client or TikHubClient()

    async def is_available(self) -> bool:
        """与两社媒 collector 同款：本地 key 检查，无免费探活端点。"""
        return self._client.configured

    async def collect_douyin(
        self, keyword: str, start_date: str, end_date: str,
    ) -> list[dict]:
        """抖音指数逐日曲线（aweme 端）。start/end_date 是 ISO YYYY-MM-DD。

        一次调用只查一个词（与多词同价 $0.003，但多词曲线语义混杂——
        看板合成指数要求两源同词可比，故只传核心词）。
        """
        data = await self._client.post_query("douyin.index_trend", params={
            "keyword_list": keyword,
            "start_date": date.fromisoformat(start_date).strftime(_DY_DATE),
            "end_date": date.fromisoformat(end_date).strftime(_DY_DATE),
            "app_name": "aweme",
        })
        points: list[dict] = []
        for kw_obj in (data or {}).get("hot_list") or []:
            for item in kw_obj.get("hot_list") or []:
                raw = str(item.get("datetime") or "")
                if len(raw) != 8 or not raw.isdigit():
                    continue
                iso = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
                try:
                    date.fromisoformat(iso)
                except ValueError:
                    continue
                val = item.get("index")
                try:
                    points.append({
                        "date": iso, "keyword": keyword,
                        "source": "douyin", "index": float(val),
                    })
                except (TypeError, ValueError):
                    continue  # index 非数字（契约是字符串数字）
        logger.info("抖音指数: %d points for '%s'", len(points), keyword)
        return points

    async def collect_xiaohongshu(self, keyword: str) -> list[dict]:
        """小红书 PGY 逐日搜索指数（近三月，时间范围服务端定）。

        查无结果（data 为 null）也计费 → 不重试不告警，返回空列表
        （官方文档明确"不要因为拿不到数据就重试"）。
        """
        # pgy 是 POST JSON body 端点（区别于 douyin 指数的 POST+query）
        data = await self._client.post("xiaohongshu.pgy_keyword_daily",
                                       params={"search_word": keyword})
        # 三层信封：client 已剥 TikHub 层，这里再剥 PGY 层
        inner = (data or {}).get("data") or {}
        points: list[dict] = []
        for day in inner.get("dailyData") or []:
            iso = str(day.get("dateKey") or "")
            try:
                date.fromisoformat(iso)
            except ValueError:
                continue
            try:
                points.append({
                    "date": iso, "keyword": keyword,
                    "source": "xiaohongshu", "index": float(day.get("searchScore")),
                })
            except (TypeError, ValueError):
                continue
        logger.info("小红书指数: %d points for '%s'", len(points), keyword)
        return points
