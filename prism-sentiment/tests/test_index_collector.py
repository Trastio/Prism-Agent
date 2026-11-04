"""Tests: IndexCollector —— 多平台搜索指数（抖音+小红书，2026-09-12）。

fixture 按 logs/tikhub_test/probe/ 实测响应复刻（dy_index_trend.json /
xhs_pgy_daily.json），日期动态；client 层 mock（信封已在 client 剥掉，
adapter 直接吃 data；POST+query vs POST+body 的分流在 TikHubClient 有
独立测试，这里只断言 adapter 选用正确的入口）。
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from pipeline.collectors.index_collector import IndexCollector
from pipeline.collectors.tikhub_collector import TikHubClient


def _client() -> TikHubClient:
    return TikHubClient(base_url="https://tikhub.test", api_key="k")


def _iso(days_ago: float) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def _dy_trend_data(index_by_date: dict[str, str]) -> dict:
    """douyin.index_trend 的 data：hot_list[] 每词一条，index 是字符串。"""
    return {"hot_list": [{
        "keyword": "小鹏mona m03",  # 契约：keyword 小写回显
        "hot_list": [{"datetime": d.replace("-", ""), "index": v}
                     for d, v in index_by_date.items()],
    }], "BaseResp": {"StatusCode": 0}}


def _pgy_daily_data(scores: dict[str, str]) -> dict:
    """pgy daily 剥掉 TikHub 层后的 data（PGY 信封内还有一层 data）。"""
    daily = [{"dateKey": d, "searchScore": v, "noteNum": 100, "userNum": 50}
             for d, v in scores.items()]
    return {"code": 0, "success": True, "data": {"dailyData": daily}}


class TestDouyinIndex:
    @pytest.mark.asyncio
    async def test_post_query_entrypoint_and_params(self):
        """抖音指数走 post_query（POST+query，GET 会 405——probe 实证）。"""
        collector = IndexCollector(client=_client())
        mock = AsyncMock(return_value=_dy_trend_data({_iso(1): "2440"}))
        with patch.object(collector._client, "post_query", mock):
            points = await collector.collect_douyin(
                "小鹏MONA M03", start_date=_iso(30), end_date=_iso(0))
        assert mock.call_args.args == ("douyin.index_trend",)
        params = mock.call_args.kwargs["params"]
        assert params["keyword_list"] == "小鹏MONA M03"
        assert params["app_name"] == "aweme"
        # ISO → YYYYMMDD
        assert params["start_date"] == _iso(30).replace("-", "")
        assert params["end_date"] == _iso(0).replace("-", "")
        assert points == [{"date": _iso(1), "keyword": "小鹏MONA M03",
                           "source": "douyin", "index": 2440.0}]

    @pytest.mark.asyncio
    async def test_string_index_and_bad_rows_skipped(self):
        """index 契约是字符串数字；坏日期/非数字 index 跳过不炸。"""
        data = _dy_trend_data({_iso(2): "3038", _iso(1): "2521"})
        # 混入坏行：日期长度错 / 非数字
        data["hot_list"][0]["hot_list"] += [
            {"datetime": "2026-9-8", "index": "100"},   # 非 YYYYMMDD
            {"datetime": _iso(3).replace("-", ""), "index": "N/A"},  # 非数字
        ]
        collector = IndexCollector(client=_client())
        with patch.object(collector._client, "post_query",
                          AsyncMock(return_value=data)):
            points = await collector.collect_douyin("kw", _iso(30), _iso(0))
        assert len(points) == 2
        assert all(p["index"] > 0 for p in points)

    @pytest.mark.asyncio
    async def test_empty_hot_list_returns_empty(self):
        collector = IndexCollector(client=_client())
        with patch.object(collector._client, "post_query",
                          AsyncMock(return_value={"hot_list": []})):
            assert await collector.collect_douyin("kw", _iso(30), _iso(0)) == []


class TestXhsIndex:
    @pytest.mark.asyncio
    async def test_post_body_entrypoint_and_triple_envelope(self):
        """PGY 走 post（JSON body）；三层信封——client 剥 TikHub 层，
        adapter 剥 PGY 层（data.data.dailyData）。"""
        collector = IndexCollector(client=_client())
        mock = AsyncMock(return_value=_pgy_daily_data({_iso(1): "600", _iso(2): "190"}))
        with patch.object(collector._client, "post", mock):
            points = await collector.collect_xiaohongshu("小鹏MONA M03")
        assert mock.call_args.args == ("xiaohongshu.pgy_keyword_daily",)
        assert mock.call_args.kwargs["params"] == {"search_word": "小鹏MONA M03"}
        assert [(p["date"], p["index"]) for p in points] == \
            [(_iso(1), 600.0), (_iso(2), 190.0)]  # dailyData 保 dict 插入序
        assert all(p["source"] == "xiaohongshu" for p in points)

    @pytest.mark.asyncio
    async def test_null_data_returns_empty_no_retry_semantics(self):
        """查无结果（data null）也计费 → 空列表返回，不抛不重试（官方契约）。"""
        collector = IndexCollector(client=_client())
        with patch.object(collector._client, "post",
                          AsyncMock(return_value={"data": None})):
            assert await collector.collect_xiaohongshu("无人搜的词") == []


class TestAvailability:
    @pytest.mark.asyncio
    async def test_unconfigured_returns_false(self):
        # conftest 隔离 env → 无 key；显式传空串同样未配置
        collector = IndexCollector(client=TikHubClient(api_key=""))
        assert await collector.is_available() is False
