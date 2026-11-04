import uuid
from datetime import datetime, date
from typing import Optional, Literal

from pydantic import BaseModel
from sqlalchemy import Column, String, Text, DateTime, Integer, Float, Boolean, Date, or_, and_
from sqlalchemy.sql import func

from models.database import Base


class Vehicle(Base):
    __tablename__ = "vehicles"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    brand = Column(String, nullable=False)
    search_keywords = Column(Text)
    expanded_keywords = Column(Text)
    keywords_expanded_at = Column(DateTime)
    # audit Phase 1 T1.2：扩展状态区分成功/失败/未跑，防失败固化 7 天
    expansion_status = Column(String, default="pending")  # success/failed/pending
    lifecycle_anchors = Column(Text)
    competitor_ids = Column(Text)
    status = Column(String, default="active")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class CollectionStatus(Base):
    __tablename__ = "collection_status"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vehicle_id = Column(String, nullable=False)
    source = Column(String, nullable=False)
    mode = Column(String, nullable=False)
    last_collected_at = Column(DateTime)
    posts_collected = Column(Integer, default=0)
    status = Column(String, default="pending")
    is_running = Column(Boolean, default=False)  # F-1：DB 级并发锁防重启后并发同车
    error_message = Column(Text)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    # §3.8 L5：加锁时刻（trigger_collection 设），脏锁判据用此字段而非 last_collected_at
    # （last_collected_at 只在采集完成时更新，无法区分"本次运行已 30min"与"上次完成已 30min 前"）
    lock_acquired_at = Column(DateTime)
    # 方案 C：上次"刷新互动数"完成时刻（展示用，不参与增量水位线）
    # last_collected_at 是增量水位线（_determine_mode 消费），不能用刷新时间覆盖（P0-1 漏采）
    last_refreshed_at = Column(DateTime)
    # 2026-10-15 舆情降本 T2（L6 v2）：预算护栏命中时登记当日未采车
    # JSON {"date": "YYYY-MM-DD", "vehicles": [车名...]}——写在触顶那台车的
    # collection_status 行上；agent/前端消费侧用它做 stale 降级声明（防"部分
    # 车已陈旧"被全局 as_of 掩盖，红线#1）
    skipped_vehicles = Column(Text)


class TikhubDailyUsage(Base):
    """TikHub 日调用计数（T2 预算护栏，方案 L6）：date 主键，进程崩溃/重启不丢当日计数。

    写入方 pipeline.collectors.budget（stdlib sqlite3 直连，挂 TikHubClient._send
    唯一通路）；表由 create_all 建，budget.py 另带 CREATE TABLE IF NOT EXISTS 兜底。
    """
    __tablename__ = "tikhub_daily_usage"
    date = Column(String, primary_key=True)  # YYYY-MM-DD（本地日）
    calls = Column(Integer, nullable=False, default=0)


class RawPost(Base):
    __tablename__ = "raw_posts"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vehicle_id = Column(String, nullable=False)
    source = Column(String, nullable=False)
    platform = Column(String)
    title = Column(String)
    content = Column(Text, nullable=False)
    author = Column(String)
    url = Column(String)
    published_at = Column(DateTime)
    collected_at = Column(DateTime, server_default=func.now())
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    analysis_status = Column(String, default="pending")
    full_content = Column(Text)
    duplicate_group_id = Column(String)
    relevance_score = Column(Float, nullable=True)
    # 作者分层（2026-09-15 Q5）：brand_official=品牌官号 / dealer=4S·车商·营销号 /
    # auto_media=汽车媒体博主（尽力识别）/ organic=普通用户。打标不删除——
    # 口碑类指标在查询层排除官方与经销商（见 AUTHENTIC_AUTHOR），热帖/声量保留。
    author_type = Column(String, default="organic")
    # 导流号标记（2026-09-29 D-3）：auto_media 帖含导流信号词（低首付/报价/
    # 现车/找我/加微信等）时 is_promo=True，口径排除；车评号（auto_media 但
    # 无导流信号）保留。只对 auto_media 判，普通用户帖即使含"优惠"也不标。
    is_promo = Column(Boolean, default=False)


class AnalyzedPost(Base):
    __tablename__ = "analyzed_posts"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    post_id = Column(String, nullable=False)
    vehicle_id = Column(String, nullable=False)
    sentiment = Column(String, nullable=False)
    event_tags = Column(Text)
    opinion_tags = Column(Text)
    confidence = Column(Float)
    analyzed_at = Column(DateTime, server_default=func.now())
    model_used = Column(String)
    dim_sentiment = Column(Text)
    comment_summary = Column(Text)
    # subject: self=主车型 / competitor=竞品具体车 / other=行业泛谈
    # NULL 视为 self（兼容回填前数据）。事件检测和聚合只取 self。
    subject = Column(String)
    # subject_name: 主要讨论的车名。self 时=主车型名，competitor 时=竞品车名，other 时为空
    subject_name = Column(String, default="")


# 主车型帖过滤：subject='self' 或 NULL（兼容老数据/未回填）。
# 竞品帖(subject=competitor)不进聚合，避免污染健康分/情感/词云等。
# 供 dashboard、event_tracker 等模块统一引用，避免复制粘贴。
SELF_ONLY = or_(AnalyzedPost.subject == "self", AnalyzedPost.subject.is_(None))

# 口碑口径（2026-09-15 Q5 分层 + 2026-09-29 D-3 导流号排除）：
# 情感分布/健康分/维度口碑等"用户口碑"类指标排除官方/经销商/营销号 +
# 导流号（is_promo）。auto_media 车评号保留（是传播信号）。
# NULL 视为 organic/non-promo（回填前/异常数据不误伤）。
INAUTHENTIC_AUTHOR_TYPES = ("brand_official", "dealer", "marketing_account")
AUTHENTIC_AUTHOR = and_(
    or_(
        RawPost.author_type.is_(None),
        ~RawPost.author_type.in_(INAUTHENTIC_AUTHOR_TYPES),
    ),
    or_(RawPost.is_promo.is_(None), ~RawPost.is_promo),
)

# 相关性口径（2026-09-15 举一反三收口）：LLM/规则判无关的帖（analysis_status=
# 'irrelevant'）不得进入任何声量/内容/词云/对话上下文/热度——此前仅 overview
# 计数挂了过滤，热帖/词云/平台分布/周报/锚点对话/热度引擎共 8 处泄漏（星愿
# 实采暴露：K-pop"星愿降临"1.4万赞无关帖登榜）。pending/analyzed 均通过；
# irrelevant 帖留库可回捞，post-comments 单帖详情端点刻意不过滤（审计要用）。
RELEVANT_ONLY = RawPost.analysis_status != "irrelevant"

# 展示类端点统一口径（2026-09-26 C1）：主车型帖 + 排除官方/经销商 + 排除无关帖。
# 供 top-opinions/word-cloud/top-posts/event 聚类等统一引用，避免逐处手写三条件。
# 注：AUTHENTIC_AUTHOR 在 author-behavior-profiling（B1）落地后扩展排除
# marketing_account，此处引用自动受益，无需改动。
LISTING_CALIBER = (SELF_ONLY, AUTHENTIC_AUTHOR, RELEVANT_ONLY)


class HeatMetric(Base):
    __tablename__ = "heat_metrics"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vehicle_id = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    attention_index = Column(Float)
    discussion_volume = Column(Integer)
    media_volume = Column(Integer)
    interaction_intensity = Column(Float)
    rank = Column(String)
    percentile = Column(Float)
    created_at = Column(DateTime, server_default=func.now())


class SearchIndexMetric(Base):
    """多平台搜索指数（2026-09-12）：抖音指数 + 小红书 PGY，按 (vehicle,
    date, source) 一行。独立于 HeatMetric——后者每车每天一行的语义被
    heat_calculator 的去重逻辑依赖，塞多 source 行会被吞。微博/快手无
    关键词级指数源，暂不采。"""
    __tablename__ = "search_index_metrics"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vehicle_id = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    source = Column(String, nullable=False)   # douyin / xiaohongshu
    keyword = Column(String, nullable=False, default="")
    index_value = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, server_default=func.now())


# DEPRECATED: AnomalyEvent removed in 2026-06 analysis redesign.
# Table and model kept as comments for migration reference.
# class AnomalyEvent(Base):
#     __tablename__ = "anomaly_events"
#     id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
#     vehicle_id = Column(String, nullable=False)
#     date = Column(Date, nullable=False)
#     volume_change_rate = Column(Float)
#     today_volume = Column(Float)
#     yesterday_volume = Column(Float)
#     event_type = Column(String)
#     sentiment_shift = Column(Text)
#     top_posts = Column(Text)
#     brief_generated = Column(Boolean, default=False)
#     root_cause = Column(Text)
#     report_generated = Column(Boolean, default=False)
#     created_at = Column(DateTime, server_default=func.now())



class Report(Base):
    __tablename__ = "reports"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vehicle_id = Column(String, nullable=False)
    type = Column(String, nullable=False)
    anomaly_event_id = Column(String)
    title = Column(String)
    content = Column(Text, nullable=False)
    time_range_start = Column(Date)
    time_range_end = Column(Date)
    created_at = Column(DateTime, server_default=func.now())


class DialogConversation(Base):
    __tablename__ = "dialog_conversations"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vehicle_id = Column(String, nullable=False)
    anchor_type = Column(String)
    anchor_data = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class DialogMessage(Base):
    __tablename__ = "dialog_messages"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    generative_ui = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class PostComment(Base):
    __tablename__ = "post_comments"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    post_id = Column(String, nullable=False)
    vehicle_id = Column(String, nullable=False)
    # 平台评论 id（dy=cid / weibo·xhs=id / ks=comment_id）：每日增量重抓同一批
    # 热帖评论的去重键（2026-09-12 修：此前无键导致 M03 4476 条里 1216 组重复，
    # 最狠一条 ×13）。不加 DB 唯一约束——SQLite 对存量重复建唯一索引会炸，
    # 去重在 _store_comments 入库前查询判定。
    cid = Column(String)
    content = Column(Text, nullable=False)
    author = Column(String)
    likes = Column(Integer, default=0)
    platform = Column(String)
    published_at = Column(DateTime)
    collected_at = Column(DateTime, server_default=func.now())
    # dim_sentiment: 15-dimension ABSA result from local model (JSON: {"维度名": score})
    dim_sentiment = Column(Text)
    # comment_polarity（2026-10-16 T4 双轨，方案 §4/R1）：新评论极性直出
    # "1"/"0"/"−1"（ASCII 连字符 "-1"）；老评论保持 dim_sentiment 不迁移，
    # 读侧 derive_comment_sentiment 新列优先/老列回退。"none"=已处理但不可解析
    # 的哨兵值（对齐维度模式 "{}" 的"已处理"语义，防队列死循环）。
    comment_polarity = Column(Text)


class EventGroup(Base):
    __tablename__ = "event_groups"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vehicle_id = Column(String, nullable=False)
    event_tag = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    post_count = Column(Integer, default=0)
    # source: "social" = 社媒帖子事件 / "news" = 新闻媒体事件
    source = Column(String, default="social")
    # JSON 数组，存 RawPost.id（= AnalyzedPost.post_id）；全项目 post_ids 语义统一为 RawPost.id
    post_ids = Column(Text)
    summary = Column(Text)
    sentiment_distribution = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class DefectTheme(Base):
    """缺陷话题簇落库（Phase 9 结果持久化 + 端点 TTL 读库）。

    每次 collection Phase 9 跑完 mine_defect_themes 后全量覆盖（delete 旧 +
    insert 新）；端点 /defect-themes 读最新行，TTL 24h 内直接返回 payload，
    超时或无数据才重算——避免每次开看板都烧 LLM。payload=JSON 簇列表。
    """
    __tablename__ = "defect_themes"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vehicle_id = Column(String, nullable=False)
    payload = Column(Text, nullable=False)  # JSON: 簇列表
    computed_at = Column(DateTime, server_default=func.now())
    # 窗口范围（code-review #1：缓存需区分时间窗，否则切窗返回旧窗口数据）
    window_start = Column(String, nullable=True)
    window_end = Column(String, nullable=True)


class WatchItem(Base):
    """手动关注清单条目（2026-09-25 三分法重设计，替代传播点报自动挖掘）。

    纯人工标记——用户在看板上对某条信号（热帖/吐槽/缺陷簇/事件）点"关注"后落库。
    无状态机（舆情不会"平息"，状态流转无意义），只存线索元数据 + 来源信号锚点。
    """
    __tablename__ = "watch_items"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vehicle_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    source_type = Column(String, nullable=False)    # hot_post | complaint | defect_cluster | event
    source_ref = Column(String)                     # post_id / cluster_id / event_id
    post_count = Column(Integer, default=0)         # 涉及帖数快照
    first_seen = Column(Date, nullable=False)       # 首次发现日期
    note = Column(Text)                             # 用户备注（可选）
    created_at = Column(DateTime, server_default=func.now())


# Pydantic schemas

class VehicleCreate(BaseModel):
    name: str  # F-6：min_length 由 FastAPI 自动校验空串
    brand: Optional[str] = None  # F-6：改 Optional（后端 _detect_brand 兜底）
    search_keywords: Optional[list[str]] = None
    lifecycle_anchors: Optional[dict] = None
    competitor_ids: Optional[list[str]] = None


class VehicleUpdate(BaseModel):
    name: Optional[str] = None
    brand: Optional[str] = None
    search_keywords: Optional[list[str]] = None
    lifecycle_anchors: Optional[dict] = None
    competitor_ids: Optional[list[str]] = None
    # F-7：status 枚举校验（防拼错致车辆静默消失）
    status: Optional[Literal["active", "paused", "inactive"]] = None


class VehicleResponse(BaseModel):
    id: str
    name: str
    brand: str
    search_keywords: Optional[str] = None
    lifecycle_anchors: Optional[str] = None
    competitor_ids: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
