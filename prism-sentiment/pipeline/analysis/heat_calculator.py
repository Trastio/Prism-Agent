import logging
import math
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import HeatMetric, RawPost, AnalyzedPost, RELEVANT_ONLY, AUTHENTIC_AUTHOR
from utils.config import env_int
from utils.constants import ENGAGEMENT_WEIGHT_LIKES, ENGAGEMENT_WEIGHT_COMMENTS, ENGAGEMENT_WEIGHT_SHARES

logger = logging.getLogger(__name__)

# 社媒帖判定 = platform != "news"（看板评估 P0-1 根治，2026-09-11）：
# 原判定是 source 白名单 ("cdp",)，provider 迭代（cdp→oneapi→tikhub）后枚举
# 必然漏配，09-10 起新 source 帖全被排除，discussion_volume /
# interaction_intensity 连日全 0。DB 实证 news 帖（anspire/bocha 623 条）
# platform 恒为 "news"、社媒帖恒为四平台名 → 按 platform 语义判定，
# 后续新增 provider 无需改这里。SQL != 比较 NULL platform 行自动落空
# （无 platform 的脏数据不进热度）。旧 SOCIAL_SOURCES 枚举已删除。
NEWS_PLATFORM = "news"

# 单日 interaction_intensity 合理上限（防止单帖病毒传播污染整条热度线）
# 超过此值 clamp + warning log，避免 6M 异常值出现
# env MAX_INTERACTION_PER_DAY 可调（模块级读取，import 时定型）
_MAX_INTERACTION_PER_DAY = env_int("MAX_INTERACTION_PER_DAY", 500_000)


class HeatMetricCalculator:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def calculate_daily(self, vehicle_id: str, target_date: date, _commit: bool = True) -> HeatMetric | None:
        start = datetime.combine(target_date, datetime.min.time())
        end = datetime.combine(target_date + timedelta(days=1), datetime.min.time())

        # Layer 1: attention index — preserve value set by scheduler (百度指数)
        # Deduplicate: keep the row with the most data, delete the rest
        existing_metric = await self._session.execute(
            select(HeatMetric).where(
                HeatMetric.vehicle_id == vehicle_id,
                HeatMetric.date == target_date,
            )
        )
        existing_rows = list(existing_metric.scalars().all())

        # Pick the best row: prefer one with non-null discussion_volume, then any row
        best = None
        for row in existing_rows:
            if row.discussion_volume is not None:
                best = row
                break
        if best is None and existing_rows:
            best = existing_rows[0]

        # Delete duplicates (all except best)
        for row in existing_rows:
            if row is not best:
                await self._session.delete(row)

        existing = best
        attention_index = existing.attention_index if existing and existing.attention_index else 0.0

        # Layer 2-4: discussion/media/interaction 合并为单条聚合查询
        # （主题D 性能：原 3 条独立 roundtrip → 1 条；CASE WHEN 区分 social/news）
        # Phase 2 §9.1+9.2：口径加 SELF_ONLY（排除 competitor 帖）+ AUTHENTIC_AUTHOR；
        # 时间窗用 coalesce(published_at, collected_at) 兜底 NULL published_at。
        # SELF_ONLY 基于 AnalyzedPost.subject；无 AnalyzedPost 行的 RawPost 视为 self（兜底）。
        competitor_post_ids = select(AnalyzedPost.post_id).where(
            AnalyzedPost.vehicle_id == vehicle_id,
            AnalyzedPost.subject == "competitor",
        )
        agg_result = await self._session.execute(
            select(
                func.count(case((RawPost.platform != NEWS_PLATFORM, 1))),        # discussion (social)
                func.count(case((RawPost.platform == NEWS_PLATFORM, 1))),        # media (news)
                func.coalesce(func.sum(case((RawPost.platform != NEWS_PLATFORM, RawPost.likes), else_=0)), 0),
                func.coalesce(func.sum(case((RawPost.platform != NEWS_PLATFORM, RawPost.comments), else_=0)), 0),
                func.coalesce(func.sum(case((RawPost.platform != NEWS_PLATFORM, RawPost.shares), else_=0)), 0),
            ).where(
                RawPost.vehicle_id == vehicle_id,
                func.coalesce(RawPost.published_at, RawPost.collected_at) >= start,
                func.coalesce(RawPost.published_at, RawPost.collected_at) < end,
                RELEVANT_ONLY,  # 口径：无关帖不进声量/热度（2026-09-15 收口）
                AUTHENTIC_AUTHOR,  # §9.1：排除官方/经销商/营销号/导流帖
                ~RawPost.id.in_(competitor_post_ids),  # §9.1：排除 competitor 帖（无 AnalyzedPost 行视为 self 兜底）
            )
        )
        a = agg_result.one()
        discussion_volume = a[3] or 0  # 讨论声量 = 社媒评论数（"讨论"即留言，比帖数更反映讨论热度）
        media_volume = a[1] or 0
        interaction_intensity = float(a[2] * ENGAGEMENT_WEIGHT_LIKES + a[3] * ENGAGEMENT_WEIGHT_COMMENTS + a[4] * ENGAGEMENT_WEIGHT_SHARES)

        # Clamp outlier spikes: single-day engagement above ceiling → cap + warn
        if interaction_intensity > _MAX_INTERACTION_PER_DAY:
            logger.warning(
                "interaction_intensity %.0f exceeds cap %d for vehicle %s on %s, clamping",
                interaction_intensity, _MAX_INTERACTION_PER_DAY, vehicle_id, target_date,
            )
            interaction_intensity = float(_MAX_INTERACTION_PER_DAY)

        # Fallback: 无百度指数（cookie 失效/groupon 未返回）时，用对数压缩后的 interaction_intensity
        # 原逻辑 attention_index = round(interaction_intensity, 1) 会将 6M 直接赋给 attention_index
        # 改为对数压缩：log1p(interaction_intensity) * 1000 —— 6M → ~15,600，20K → ~9,900
        if attention_index == 0.0 and interaction_intensity > 0:
            attention_index = round(math.log1p(interaction_intensity) * 1000, 1)

        if discussion_volume == 0 and media_volume == 0 and interaction_intensity == 0.0 and attention_index == 0.0:
            return None

        # Upsert
        if existing:
            existing.attention_index = attention_index  # fallback 可能更新了它（无百度指数时）
            existing.discussion_volume = discussion_volume
            existing.media_volume = media_volume
            existing.interaction_intensity = interaction_intensity
            metric = existing
        else:
            metric = HeatMetric(
                id=str(uuid.uuid4()),
                vehicle_id=vehicle_id,
                date=target_date,
                attention_index=attention_index,
                discussion_volume=discussion_volume,
                media_volume=media_volume,
                interaction_intensity=interaction_intensity,
            )
            self._session.add(metric)

        # Calculate rank and percentile over last 30 days
        thirty_days_ago = target_date - timedelta(days=30)
        range_result = await self._session.execute(
            select(HeatMetric.interaction_intensity).where(
                HeatMetric.vehicle_id == vehicle_id,
                HeatMetric.date >= thirty_days_ago,
                HeatMetric.date <= target_date,
            )
        )
        values = [v for (v,) in range_result.all() if v is not None and v > 0]
        if values:
            sorted_values = sorted(values, reverse=True)
            rank_pos = 0
            for i, v in enumerate(sorted_values):
                if v <= metric.interaction_intensity:
                    rank_pos = i
                    break
            percentile = round((1 - rank_pos / len(sorted_values)) * 100, 1)
            if percentile >= 99:
                metric.rank = "近30天最高"
            elif percentile >= 90:
                metric.rank = "前10%"
            elif percentile >= 75:
                metric.rank = "前25%"
            else:
                metric.rank = f"前{int(100 - percentile)}%"
            metric.percentile = percentile
        else:
            metric.rank = "无历史数据"
            metric.percentile = 0.0

        if _commit:
            await self._session.commit()
        return metric

    async def calculate_range(self, vehicle_id: str, start: date, end: date) -> list[HeatMetric]:
        # 完全批量化：一次 GROUP BY date 聚合 + 批量 upsert + percentile 内存算 + 一次 commit。
        # 原逐天 calculate_daily（90 × 3-4 async query = 270+ query）慢到分钟级。
        start_dt = datetime.combine(start, datetime.min.time())
        end_dt = datetime.combine(end + timedelta(days=1), datetime.min.time())

        # 1. 一次聚合每天的 discussion(社媒评论)/media(news帖数)/interaction 分量
        # 列顺序：d / discussion(comments sum) / media(news count) / likes / comments / shares
        # Phase 2 §9.1+9.2：口径加 SELF_ONLY（排除 competitor）+ AUTHENTIC_AUTHOR；时间用 coalesce 兜底 NULL。
        competitor_post_ids = select(AnalyzedPost.post_id).where(
            AnalyzedPost.vehicle_id == vehicle_id,
            AnalyzedPost.subject == "competitor",
        )
        time_col = func.coalesce(RawPost.published_at, RawPost.collected_at)
        agg = await self._session.execute(
            select(
                func.date(time_col).label("d"),
                func.coalesce(func.sum(case((RawPost.platform != NEWS_PLATFORM, RawPost.comments), else_=0)), 0).label("discussion"),
                func.count(case((RawPost.platform == NEWS_PLATFORM, 1))).label("media"),
                func.coalesce(func.sum(case((RawPost.platform != NEWS_PLATFORM, RawPost.likes), else_=0)), 0).label("likes"),
                func.coalesce(func.sum(case((RawPost.platform != NEWS_PLATFORM, RawPost.comments), else_=0)), 0).label("comments"),
                func.coalesce(func.sum(case((RawPost.platform != NEWS_PLATFORM, RawPost.shares), else_=0)), 0).label("shares"),
            ).where(
                RawPost.vehicle_id == vehicle_id,
                time_col >= start_dt,
                time_col < end_dt,
                RELEVANT_ONLY,  # 口径：无关帖不进声量/热度（2026-09-15 收口）
                AUTHENTIC_AUTHOR,  # §9.1：排除官方/经销商/营销号/导流帖
                ~RawPost.id.in_(competitor_post_ids),  # §9.1：排除 competitor 帖（无 AnalyzedPost 行视为 self 兜底）
            ).group_by(func.date(time_col))
        )
        agg_rows = list(agg.all())

        # 2. existing HeatMetric（保留 attention_index；删重复）
        ex = await self._session.execute(
            select(HeatMetric).where(
                HeatMetric.vehicle_id == vehicle_id,
                HeatMetric.date >= start, HeatMetric.date <= end,
            )
        )
        existing_by_date: dict = {}
        for m in ex.scalars().all():
            if m.date in existing_by_date:
                await self._session.delete(m)  # 删重复
            else:
                existing_by_date[m.date] = m

        # 3. upsert 每个有数据的日子
        metrics: list[HeatMetric] = []
        for r in agg_rows:
            target = r.d if isinstance(r.d, date) else date.fromisoformat(r.d)
            # r[0]=date, r[1]=discussion, r[2]=media, r[3]=likes, r[4]=comments, r[5]=shares
            discussion = int(r[1] or 0)
            media = int(r[2] or 0)
            interaction = float(
                int(r[3] or 0) * ENGAGEMENT_WEIGHT_LIKES
                + int(r[4] or 0) * ENGAGEMENT_WEIGHT_COMMENTS
                + int(r[5] or 0) * ENGAGEMENT_WEIGHT_SHARES
            )
            if interaction > _MAX_INTERACTION_PER_DAY:
                interaction = float(_MAX_INTERACTION_PER_DAY)
            existing = existing_by_date.get(target)
            attention = existing.attention_index if existing and existing.attention_index else 0.0
            if attention == 0.0 and interaction > 0:
                attention = round(math.log1p(interaction) * 1000, 1)
            if existing:
                existing.attention_index = attention
                existing.discussion_volume = discussion
                existing.media_volume = media
                existing.interaction_intensity = interaction
                metrics.append(existing)
            else:
                metric = HeatMetric(
                    id=str(uuid.uuid4()), vehicle_id=vehicle_id, date=target,
                    attention_index=attention, discussion_volume=discussion,
                    media_volume=media, interaction_intensity=interaction,
                )
                self._session.add(metric)
                metrics.append(metric)

        # 3.5 口径收口（2026-09-16）：范围内的日子若已无 relevant 帖（帖子被
        # 判 irrelevant / 被清库），旧行的 discussion/media/interaction 清零，
        # 仅保留 attention_index（搜索指数独立于帖子存在）。否则僵尸行永久残留
        # （实测 7 行旧污染，irrelevant-only 的日子 heat>0）。
        agg_dates = {r.d if isinstance(r.d, date) else date.fromisoformat(r.d) for r in agg_rows}
        for d, m in existing_by_date.items():
            if d not in agg_dates:
                m.discussion_volume = 0
                m.media_volume = 0
                m.interaction_intensity = 0

        # 4. percentile：取该 vehicle 全部 metric interaction（DB 历史），合并本次新算，内存算每天 30 天窗口
        all_ex = await self._session.execute(
            select(HeatMetric.date, HeatMetric.interaction_intensity).where(
                HeatMetric.vehicle_id == vehicle_id,
            )
        )
        val_by_date = {d: v for d, v in all_ex.all() if v is not None}
        for metric in metrics:
            val_by_date[metric.date] = metric.interaction_intensity  # 本次新算覆盖
        for metric in metrics:
            ws = metric.date - timedelta(days=30)
            window = sorted((v for d, v in val_by_date.items() if ws <= d <= metric.date and v > 0), reverse=True)
            if window:
                rank_pos = 0
                for i, v in enumerate(window):
                    if v <= metric.interaction_intensity:
                        rank_pos = i
                        break
                percentile = round((1 - rank_pos / len(window)) * 100, 1)
                metric.percentile = percentile
                if percentile >= 99:
                    metric.rank = "近30天最高"
                elif percentile >= 90:
                    metric.rank = "前10%"
                elif percentile >= 75:
                    metric.rank = "前25%"
                else:
                    metric.rank = f"前{int(100 - percentile)}%"
            else:
                metric.rank = "无历史数据"
                metric.percentile = 0.0

        await self._session.commit()
        return metrics

    async def get_metrics(self, vehicle_id: str, start: date, end: date) -> list[HeatMetric]:
        result = await self._session.execute(
            select(HeatMetric).where(
                HeatMetric.vehicle_id == vehicle_id,
                HeatMetric.date >= start,
                HeatMetric.date <= end,
            ).order_by(HeatMetric.date)
        )
        return list(result.scalars().all())
