"""每日批量刷新近30天帖互动数——治快照冻结（dashboard-data-foundation A3）。

问题：当天采的帖平均赞 42.9，7 天后回溯采的平均赞 1135——榜单偏老帖，
因为互动数在采集时是一次性快照，之后不再更新。

策略（按平台能力分流，控成本；2026-09-27 OneAPI 退役后全走 TikHub）：
- 抖音：批量统计端点 fetch_multi_video_statistics（$0.025/批，全刷近30天帖）
- 快手：批量详情端点 fetch_videos_batch（≤40/批，$0.001/帖，全刷近30天帖）
- 微博：无批量端点，只刷 top30 帖（按 likes+comments 降序，逐帖调
  web_v2 详情端点——控成本，避免逐帖计费刷全量；与 TikHubCollector
  enrich_weibo_details 同一端点，此处只取互动数三键）
- 小红书：无批量端点，只刷 top30 帖（app_v2 get_image_note_detail 逐帖，
  免 xsec_token；$0.001/帖，首跑 1 帖确认计费）

刷新失败不阻断 daily_update：每批/每帖 try-except 记 warning 跳过。
"""
import asyncio
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select, update, func

from models.database import async_session
from models.schemas import RawPost, Vehicle
from pipeline.analysis.heat_calculator import HeatMetricCalculator
from utils.config import env_int
from pipeline.collectors.tikhub_collector import TikHubClient

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50          # 批量端点单次上限（抖音 aweme_ids 同量级；TikHub 内部再按 ≤20 分批）
_KS_BATCH_SIZE = 40       # 快手批量端点上限（openapi 显式 ≤40；2026-10-15 停采后不再触达）
# 无批量端点平台（小红书）的逐帖刷新上限（控成本）。2026-10-15 舆情降本：30→15
# （R39/R41 后口径：窗维持 30 天、逐帖帽减半；env REFRESH_TOP_N 整数覆盖）。
_TOP_N = env_int("REFRESH_TOP_N", 15)
_WINDOW_DAYS = 30         # 刷新近 30 天帖（R39 维持不缩；与采集窗口对齐）


def _url_id(url: str | None) -> str:
    """URL 末段 id（与 post_utils._path_tail 同款约定）。

    /video/{id}、/short-video/{id}、/explore/{id}?xsec_token=...、/status/{id}
    """
    if not url:
        return ""
    return url.rsplit("/", 1)[-1].split("?")[0].split("#")[0]


def _stats_to_vals(st: dict) -> dict:
    """统计 dict → RawPost 更新值（只装非 None 字段，None 保留原值）。

    int 强转：详情端点互动数实测有字符串/整数两种形态（mblog 契约），
    转不动（None/空串以外的畸形值罕见）直接跳过该键不写。
    """
    vals = {}
    for col, key in (("likes", "likes"), ("comments", "comments"), ("shares", "shares")):
        v = st.get(key)
        if v is None:
            continue
        try:
            vals[col] = int(v)
        except (TypeError, ValueError):
            continue
    return vals


async def _refresh_douyin(session, posts: list[RawPost], client: TikHubClient) -> int:
    """抖音批量统计：aweme_ids 一次拿回 digg_count/share_count（comment_count 不保证有）。"""
    refreshed = 0
    for i in range(0, len(posts), _BATCH_SIZE):
        batch = posts[i:i + _BATCH_SIZE]
        aweme_ids = [_url_id(p.url) for p in batch if _url_id(p.url)]
        if not aweme_ids:
            continue
        try:
            stats = await client.fetch_douyin_play_stats(aweme_ids)
        except Exception as e:
            logger.warning("抖音批量刷新失败（%d 帖跳过）: %s", len(batch), e)
            continue
        for p in batch:
            aid = _url_id(p.url)
            st = stats.get(aid)
            if not st:
                continue
            # douyin-app 统计键名：digg_count(赞)/share_count(转)；comment_count 不一定有
            vals = _stats_to_vals({
                "likes": st.get("digg_count"),
                "comments": st.get("comment_count"),
                "shares": st.get("share_count"),
            })
            if vals:
                await session.execute(
                    update(RawPost).where(RawPost.id == p.id).values(**vals))
                refreshed += 1
    return refreshed


async def _fetch_weibo_stats(client: TikHubClient, mid: str) -> dict:
    """微博单帖详情（web_v2 fetch_post_detail，$0.001/帖）→ 统一 stats dict。

    mblog 键名：attitudes_count(赞)/comments_count(评)/reposts_count(转)，
    字符串/整数两种形态实测都见过（_stats_to_vals int 归一）。
    """
    mb = await client.get("weibo.fetch_post_detail",
                           params={"id": mid, "is_get_long_text": "false"}) or {}
    return {
        "likes": mb.get("attitudes_count"),
        "comments": mb.get("comments_count"),
        "shares": mb.get("reposts_count"),
    }


async def _refresh_kuaishou(session, posts: list[RawPost], client: TikHubClient) -> int:
    """快手批量详情（fetch_videos_batch，≤40/批，$0.001/帖）→ 全刷近30天帖。

    响应结构（2026-09-28 实采确认）：{result, photos, host-name}，photos[]
    每个顶层含 photo_id + like_count/comment_count/share_count/view_count。
    按 photo_id 建索引对应请求 id。
    """
    refreshed = 0
    for i in range(0, len(posts), _KS_BATCH_SIZE):
        batch = posts[i:i + _KS_BATCH_SIZE]
        photo_ids = [_url_id(p.url) for p in batch if _url_id(p.url)]
        if not photo_ids:
            continue
        try:
            data = await client.get("kuaishou.fetch_videos_batch",
                                    params={"photo_ids": ",".join(photo_ids)}) or {}
        except Exception as e:
            logger.warning("快手批量刷新失败（%d 帖跳过）: %s", len(batch), e)
            continue
        by_id = {str(p.get("photo_id") or ""): p
                 for p in (data.get("photos") or []) if p.get("photo_id")}
        for p in batch:
            pid = _url_id(p.url)
            if not pid:
                continue
            st = by_id.get(pid)
            if not st:
                continue
            vals = _stats_to_vals({
                "likes": st.get("like_count"),
                "comments": st.get("comment_count"),
                "shares": st.get("share_count"),
            })
            if vals:
                await session.execute(
                    update(RawPost).where(RawPost.id == p.id).values(**vals))
                refreshed += 1
    return refreshed


async def _fetch_xhs_stats(client: TikHubClient, note_id: str) -> dict:
    """小红书单帖详情（app_v2 get_image_note_detail，$0.001/帖）→ 统一 stats dict。

    响应结构（2026-09-28 实采确认）：双层信封，client.get 拆外层后 payload =
    {code, success, data:[{note_list:[...]}], msg}。笔记在 data[0].note_list[0]，
    键名 liked_count/comments_count/shared_count/collected_count。
    免 xsec_token（web_v3 才需要）。视频笔记若 note_list 为空（image 端点不
    覆盖视频），记 warning——后续可切 get_video_note_detail 端点补全。
    """
    payload = await client.get("xiaohongshu.get_note_detail",
                               params={"note_id": note_id}) or {}
    data = payload.get("data") or []
    note = {}
    if isinstance(data, list) and data:
        notes = data[0].get("note_list") or []
        if notes:
            note = notes[0]
        else:
            logger.warning("小红书 note_list 空（可能视频笔记走 image 端点）: %s", note_id)
    return {
        "likes": note.get("liked_count"),
        "comments": note.get("comments_count"),
        "shares": note.get("shared_count"),
    }


async def _refresh_topn(session, posts: list[RawPost], fetcher) -> int:
    """无批量端点平台：按 likes+comments 降序取 top30，逐帖详情刷新。

    fetcher 是已捕获 client 的闭包（如 _xhs_fetcher / _wb_fetcher）。
    """
    ranked = sorted(
        posts,
        key=lambda p: (p.likes or 0) + (p.comments or 0),
        reverse=True,
    )[:_TOP_N]
    refreshed = 0
    for p in ranked:
        oid = _url_id(p.url)
        if not oid:
            continue
        try:
            st = await fetcher(oid)
        except Exception as e:
            logger.warning("单帖刷新失败 %s: %s", p.url, e)
            continue
        vals = _stats_to_vals(st)
        if vals:
            await session.execute(
                update(RawPost).where(RawPost.id == p.id).values(**vals))
            refreshed += 1
    return refreshed


async def refresh_vehicle_engagement(
    session, vehicle_id: str, client: TikHubClient | None = None,
) -> int:
    """刷新单车近30天帖互动数，返回刷新帖数。

    失败不阻断：每平台/批次/单帖 try-except 跳过，最后统一 commit。
    """
    since = datetime.now() - timedelta(days=_WINDOW_DAYS)
    posts = (await session.execute(
        select(RawPost).where(
            RawPost.vehicle_id == vehicle_id,
            func.coalesce(RawPost.published_at, RawPost.collected_at) >= since,
        )
    )).scalars().all()
    if not posts:
        return 0

    client = client or TikHubClient()
    refreshed = 0

    dy = [p for p in posts if p.platform == "douyin" and p.url]
    if dy:
        refreshed += await _refresh_douyin(session, dy, client)

    # 2026-10-16 T7 实测发现（Step8 补刀）：快手/微博已停采（R23），存量帖
    # 不再刷互动——停采渠道数字定格在最后一次刷新值，随 30 天保留线自然
    # 出库；刷新只覆盖活跃平台（xhs/douyin）。_refresh_kuaishou/_fetch_weibo_stats
    # 连同分支保留归档，勿删（历史口径可查）。T7 首跑实证：停采平台逐帖刷新
    # 曾占预算 225 次/天的无效消耗面。
    # ks = [p for p in posts if p.platform == "kuaishou" and p.url]
    # if ks:
    #     refreshed += await _refresh_kuaishou(session, ks, client)

    xhs = [p for p in posts if p.platform == "xiaohongshu" and p.url]
    if xhs:
        async def _xhs_fetcher(nid: str) -> dict:
            return await _fetch_xhs_stats(client, nid)
        refreshed += await _refresh_topn(session, xhs, _xhs_fetcher)

    # wb = [p for p in posts if p.platform == "weibo" and p.url]
    # if wb:
    #     async def _wb_fetcher(mid: str) -> dict:
    #         return await _fetch_weibo_stats(client, mid)
    #     refreshed += await _refresh_topn(session, wb, _wb_fetcher)

    await session.commit()
    return refreshed


async def run_all() -> None:
    """刷新所有 active 车辆近30天帖互动数。单车失败不阻断下一车。

    审计 P1-3（2026-10-07）：每车刷新后重算热度——原只刷新不重算，榜单热度
    永远用上一轮互动数；API 侧 _run_refresh_pipeline 本就刷新后重算，此处对齐。
    """
    # engine 是模块级全局，asyncio.run 关循环后连接池的 aiosqlite 后台线程
    # 没清理会导致进程挂死不退出（2026-09-29 实证）。末尾显式 dispose 解锁。
    from models.database import engine
    try:
        async with async_session() as session:
            vehicles = (await session.execute(
                select(Vehicle).where(Vehicle.status == "active")
            )).scalars().all()
            for v in vehicles:
                try:
                    n = await refresh_vehicle_engagement(session, v.id)
                    end = date.today()
                    await HeatMetricCalculator(session).calculate_range(
                        v.id, end - timedelta(days=90), end)
                    logger.info("[%s] 刷新 %d 帖互动 + 热度重算", v.name, n)
                except Exception as e:
                    logger.error("[%s] 刷新失败: %s", v.name, e)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run_all())
