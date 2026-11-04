from datetime import date, datetime, timedelta, timezone
from sqlalchemy import Column, String, Date, Float, JSON, DateTime, ForeignKey, Integer, Index, func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class OwnerReview(Base):
    __tablename__ = "owner_reviews"
    # P1-7：覆盖索引（model_id, post_date, fetched_at）— 口碑列表首屏 GROUP BY model_id
    # 聚合 COUNT(*)/MAX(post_date)/MAX(fetched_at) 全部从索引取，不读 123K 行 TEXT 列。
    __table_args__ = (
        Index("idx_owner_reviews_model_post", "model_id", "post_date", "fetched_at"),
    )

    review_id = Column(String, primary_key=True)
    owner_id = Column(String, nullable=True)
    model_full_name = Column(String, nullable=False)
    spec_name = Column(String, nullable=True)
    spec_id = Column(String, nullable=True)
    model_id = Column(String, nullable=False, index=True)
    purchase_date = Column(Date, nullable=True)
    post_date = Column(String, nullable=True)
    best_review_text = Column(String, nullable=True)
    worst_review_text = Column(String, nullable=True)
    # dashboards-tri-polish：完整原文（回填自之家详情页，~500 字 vs API 截断 ~56 字）
    best_full_text = Column(String, nullable=True)
    worst_full_text = Column(String, nullable=True)
    score = Column(Float, nullable=True)
    dimensions = Column(JSON, nullable=True)
    buy_price = Column(String, nullable=True)
    fuel_consumption = Column(String, nullable=True)
    mileage = Column(String, nullable=True)
    city = Column(String, nullable=True)
    use_purposes = Column(JSON, nullable=True)
    dimension_reviews = Column(JSON, nullable=True)
    exinfo = Column(JSON, nullable=True)
    raw_json = Column(JSON, nullable=True)
    fetched_at = Column(DateTime, default=func.now())


# review_tags 唯一索引名单源：db.py 存量迁移（_UQ_INDEX_NAME）与 tests 探针引用同一常量。
# 用命名 Index 而非 UniqueConstraint：create_all 对新库直接建出该命名索引，
# 与迁移路径收敛到同一索引（否则 UniqueConstraint 渲染为 sqlite_autoindex_*，新库会双索引）。
REVIEW_TAGS_UQ_NAME = "uq_review_tags_rid_name_senti"


class ReviewTag(Base):
    __tablename__ = "review_tags"
    __table_args__ = (
        Index(REVIEW_TAGS_UQ_NAME, "review_id", "tag_name", "sentiment", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    review_id = Column(String, ForeignKey("owner_reviews.review_id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(String, nullable=True)
    model_full_name = Column(String, nullable=False)
    model_id = Column(String, nullable=False, index=True)
    tag_category = Column(String, nullable=True)
    tag_name = Column(String, nullable=False)
    sentiment = Column(String, nullable=False)  # "pro" or "con"
    source_text = Column(String, nullable=True)
    confidence = Column(Float, nullable=False, default=0.0)


class SeriesSummary(Base):
    __tablename__ = "series_summaries"

    series_id = Column(String, primary_key=True)
    series_name = Column(String, nullable=True)
    brand_name = Column(String, nullable=True)
    brand_id = Column(String, nullable=True)
    level_name = Column(String, nullable=True)
    level_id = Column(String, nullable=True)
    price_range = Column(String, nullable=True)
    min_price = Column(Float, nullable=True)
    max_price = Column(Float, nullable=True)
    average_score = Column(Float, nullable=True)
    dimension_scores = Column(JSON, nullable=True)
    review_count = Column(Integer, nullable=True)
    onsell_review_count = Column(Integer, nullable=True)
    pph = Column(Integer, nullable=True)
    level_rank = Column(Integer, nullable=True)
    level_series_count = Column(Integer, nullable=True)
    powertype = Column(Integer, nullable=True)
    cmp_scores = Column(JSON, nullable=True)
    cmp_pph = Column(JSON, nullable=True)
    consumption = Column(String, nullable=True)
    consumption_battery = Column(String, nullable=True)
    spec_groups = Column(JSON, nullable=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class Conversation(Base):
    __tablename__ = "conversations"

    session_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, default="default")
    messages = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=func.now())
    last_active_at = Column(DateTime, default=func.now())

    @property
    def is_expired(self) -> bool:
        if self.last_active_at is None:
            return False
        now = datetime.now(timezone.utc)
        last = self.last_active_at
        # SQLite stores naive UTC datetimes via func.now()
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return now - last > timedelta(hours=24)

    @property
    def messages_list(self) -> list:
        return self.messages if isinstance(self.messages, list) else []

    def set_messages(self, msgs: list):
        self.messages = msgs
        self.last_active_at = datetime.now(timezone.utc)


class TaskRecord(Base):
    __tablename__ = "task_records"

    task_id = Column(String, primary_key=True)
    status = Column(String, nullable=False, default="pending")
    progress = Column(String, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id = Column(String, primary_key=True)
    budget_max = Column(Integer, nullable=True)
    budget_min = Column(Integer, nullable=True)
    segments = Column(JSON, nullable=True, default=list)     # ["SUV", "轿车"]
    energy_types = Column(JSON, nullable=True, default=list) # ["纯电", "混动"]
    brands = Column(JSON, nullable=True, default=list)
    dimension_weights = Column(JSON, nullable=True,
                               default=lambda: {"续航": 0.2, "安全": 0.2, "舒适": 0.2, "颜值": 0.2, "性价比": 0.2})
    updated_at = Column(DateTime, default=func.now())

    @property
    def dimension_weights_dict(self) -> dict:
        weights = self.dimension_weights or {
            "续航": 0.2, "安全": 0.2, "舒适": 0.2, "颜值": 0.2, "性价比": 0.2}
        return dict(weights)


class InsightCache(Base):
    """AI 总结筛选指纹缓存（specs/koubei-insights v5）。
    看板唯一写例外（用户价格文件之外）：仅写洞察产物，不写业务表。
    失效策略：存 baseline_reviews/baseline_tags，命中时比对当前行数，不一致失效。"""
    __tablename__ = "insight_cache"

    filter_hash = Column(String, primary_key=True)
    model_id = Column(String, nullable=False, index=True)
    filter_json = Column(JSON, nullable=False)
    summary_markdown = Column(String, nullable=True)
    review_refs = Column(JSON, nullable=True)
    n = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=func.now())
    llm_model = Column(String, nullable=True)
    baseline_reviews = Column(Integer, nullable=False)
    baseline_tags = Column(Integer, nullable=False)


class ConfigSnapshot(Base):
    """车系配置快照（specs/dashboards v5）。collector 式写库（手动刷新），
    看板只读。从 data/config_snapshots/*.json 迁入。"""
    __tablename__ = "config_snapshots"

    series_id = Column(String, primary_key=True)
    series_name = Column(String, nullable=True)
    maker = Column(String, nullable=True)
    energy = Column(String, nullable=True)
    level = Column(String, nullable=True)
    price_range = Column(String, nullable=True)
    categories = Column(JSON, nullable=False)
    fetched_at = Column(String, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    # dashboard-v10 Task 1.1：字体解码命中率（0-1，NULL=迁移前旧快照）。
    # collect 脚本/refresh 端点写入；selfcheck 查 MIN(decode_hit_rate) < 0.9 → 黄牌。
    decode_hit_rate = Column("decode_hit_rate", Float, nullable=True)


class CollectionRun(Base):
    """口碑采集运行台账（口碑周更增量采集 change，2026-11-01）。

    weekly/full 两种模式共用；深采历史不回填。started_at/finished_at 存 naive UTC
    （func.now()/datetime.now(timezone.utc)，与 Conversation 同口径）。
    budget_capped 是 stats 字段不是 status——预算触顶属正常终态（status=success）。
    看板"口碑更新至"读最近一条 mode=weekly 且 status=success。"""
    __tablename__ = "collection_runs"

    run_id = Column(Integer, primary_key=True, autoincrement=True)
    mode = Column(String, nullable=False)            # weekly | full
    started_at = Column(DateTime, default=func.now())
    finished_at = Column(DateTime, nullable=True)
    series_total = Column(Integer, nullable=False, default=0)
    series_done = Column(Integer, nullable=False, default=0)
    series_budget_capped = Column(Integer, nullable=False, default=0)
    new_reviews = Column(Integer, nullable=False, default=0)
    tagged = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False)          # success | partial | error
    error = Column(String, nullable=True)


class SalesTrim(Base):
    """CAM 终端价格监测-版型级（specs/market-dashboard v6）。主键=车型编号+年+月。
    Excel 双月度快照逐行落库（scripts/import_sales_excel.py），看板只读。
    month 为源表原文（"1月中"/"10月末"）。"""
    __tablename__ = "sales_trim"

    model_code = Column(String, primary_key=True)  # 车型编号
    year = Column(Integer, primary_key=True)
    month = Column(String, primary_key=True)  # "1月中"
    manufacturer = Column(String)
    brand = Column(String)
    series = Column(String, index=True)
    level = Column(String)
    body = Column(String)
    displacement = Column(String)
    gearbox = Column(String)
    energy_type = Column(String)
    seats = Column(Integer)
    drive = Column(String)
    fuel = Column(String)
    origin = Column(String)
    ev_range = Column(Integer)
    version = Column(String)
    pre_msrp = Column(Float)
    length_mm = Column(Integer)
    wheelbase_mm = Column(Integer)
    launch_date = Column(String)
    prod_status = Column(String)
    model_name = Column(String)
    msrp = Column(Float)
    tp = Column(Float)
    discount = Column(Float)
    mix = Column(Float)
    retail = Column(Integer)
    is_main = Column(String)
    hi_lo = Column(String)


# v7 单表化：SeriesWeighted（sales_series_weighted 加权表）与 SeriesAlias
# （series_alias 跨表归一表）已整体退役——市场车系视角一律由 SalesTrim 按
# series 聚合（车系销量=SUM(retail)，价格=零售加权），两表已从库中 DROP。


def upsert_config_snapshot(session, sid: str, data: dict) -> ConfigSnapshot:
    """upsert config_snapshots（specs/dashboards v5，/simplify 归一）。
    data 字段：series_name/maker/energy/level/price_range/categories/fetched_at/
    decode_hit_rate（v10 Task 1.1）。
    存在 → 更新非 None 字段 + version+1；新 → 插入 version=1。
    None 字段不覆盖既有值（refresh 端点 get_series_info 失败时不擦除旧名）。
    供 refresh 端点与 migrate 脚本共用，避免两处 upsert 逻辑漂移。"""
    existing = session.get(ConfigSnapshot, sid)
    fields = ("series_name", "maker", "energy", "level", "price_range",
              "categories", "fetched_at", "decode_hit_rate")
    if existing:
        for k in fields:
            v = data.get(k)
            if v is not None:
                setattr(existing, k, v)
        existing.version = (existing.version or 0) + 1
        return existing
    row = ConfigSnapshot(series_id=sid, version=1)
    for k in fields:
        v = data.get(k)
        if v is not None:
            setattr(row, k, v)
    session.add(row)
    return row
