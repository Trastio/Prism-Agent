"""采集 provider 路由表 —— 2026-09-27 OneAPI 退役，社媒全量 TikHub。

OneAPI 余额反复耗尽（302 quota exceeded 30次/轮），且 TikHub 已具备四平台
全部能力（搜索+评论+批量统计），双 provider 路由的复杂度不再有收益。
本表保留 key 结构（weibo / xiaohongshu / kuaishou / douyin_search /
douyin_comments / douyin_stats）供调用方按任务查询，值恒为 "tikhub"。
"""

from __future__ import annotations

DEFAULT_PROVIDERS: dict[str, str] = {
    "weibo": "tikhub",
    "xiaohongshu": "tikhub",
    "kuaishou": "tikhub",
    "douyin_search": "tikhub",
    "douyin_comments": "tikhub",
    "douyin_stats": "tikhub",
}


def collect_providers() -> dict[str, str]:
    """返回当前生效的采集 provider 路由表（key → 'tikhub'）。

    单 provider 后无路由选择：返回默认表副本（调用方可安全改写，
    不会污染模块级默认表）。
    """
    return dict(DEFAULT_PROVIDERS)
