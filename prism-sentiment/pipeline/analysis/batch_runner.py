import asyncio
import json
import logging
import os
import uuid
from datetime import date as date_type

from sqlalchemy import select, func, desc, or_
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import AnalyzedPost, PostComment, RawPost, Vehicle
from pipeline.analysis.analyzer import AnalysisPipeline
from pipeline.analysis.relevance_filter import RelevanceFilter, LLMRelevanceChecker
from pipeline.platforms import XIAOHONGSHU, WEIBO, DOUYIN, KUAISHOU
from utils.config import env_int
from utils.llm_helpers import extract_json_object
from utils.constants import ENGAGEMENT_WEIGHT_LIKES, ENGAGEMENT_WEIGHT_COMMENTS, ENGAGEMENT_WEIGHT_SHARES

MAX_POSTS_PER_RUN = 1000
_COMMENT_WINDOW_DAYS = env_int("COMMENT_WINDOW_DAYS", 30)  # 评论摘要选帖窗口（原半月=15天，拓宽到全月增覆盖）
_MIN_COMMENTS_FOR_SUMMARY = env_int("MIN_COMMENTS_FOR_SUMMARY", 3)  # 降低阈值（原5→3）提升评论摘要覆盖率

# 评论补抓旋钮（2026-10-15 舆情降本 R41）：top-N 默认 30→10（评论降级只判极性
# 后单条价值下降，量价匹配）；翻页 3→2（post_utils._COMMENT_MAX_PAGES_DEFAULT）。
# env 同名 COMMENT_TOP_N / COMMENT_MAX_PAGES 整数覆盖，非法回退默认。
# 2026-10-15 渠道收敛（R23）：评论平台随社媒缩到 小红书/抖音 两平台。
_COMMENT_TOP_N_DEFAULT = env_int("COMMENT_TOP_N_DEFAULT", 15)  # 2026-10-16 R46：top10→top15（用户拍板，评论覆盖加深）
_COMMENT_PLATFORMS = (XIAOHONGSHU, DOUYIN)

logger = logging.getLogger(__name__)

# 向后兼容别名：历史代码与下游可能 import batch_runner._env_int。
# 实现已抽到 utils.config.env_int（公共位置，defect_miner/scheduler 等共用）。
_env_int = env_int


def comment_top_n(platform: str) -> int:
    """评论补抓每平台选帖数 top-N（env COMMENT_TOP_N 整数覆盖全平台）。

    平台不在四社媒白名单返回 0（选帖即跳过该平台）。
    """
    if platform not in _COMMENT_PLATFORMS:
        return 0
    return _env_int("COMMENT_TOP_N", _COMMENT_TOP_N_DEFAULT)


def comment_negative_extra_n(platform: str) -> int:
    """负面帖评论追加每平台上限（T2/L1，env COMMENT_NEGATIVE_EXTRA_N，默认 10）。

    与 comment_top_n 同款平台白名单语义：非社媒平台返回 0。选帖侧用它对
    负面词表预筛命中的帖做独立 cap（R41 预算：top10×2 + 追加 10/平台）。
    """
    if platform not in _COMMENT_PLATFORMS:
        return 0
    return _env_int("COMMENT_NEGATIVE_EXTRA_N", 10)


# ── Half-month period helpers ─────────────────────────────────────────────

def get_current_period() -> tuple[date_type, date_type]:
    """Return (start_date, end_date) for the current half-month window."""
    today = date_type.today()
    if today.day <= 15:
        return today.replace(day=1), today.replace(day=15)
    start = today.replace(day=16)
    if today.month == 12:
        end = date_type(today.year + 1, 1, 1)
    else:
        end = date_type(today.year, today.month + 1, 1)
    return start, date_type.fromordinal(end.toordinal() - 1)


async def select_top_posts_for_comments(
    session: AsyncSession, vehicle_id: str,
) -> list[RawPost]:
    """Per-platform top-N posts by interaction, with backfill + engagement floor.

    Shared selection for fetch_top_comments（抓评论）和 run_comment_summaries（写摘要）。
    两者必须选同一批帖，否则评论抓了却没摘要可写（Bug 6：原 fetch 用 48h 窗口、
    summaries 用跨平台总 top-5，选帖不一致导致 comment_summary 恒空）。
    每平台 N = comment_top_n()（env COMMENT_TOP_N 可调，默认 30）；窗口 =
    最近 _COMMENT_WINDOW_DAYS 天（原半月=15天，拓宽到全月增覆盖）。

    口径（C1，T1.3）：挂 LISTING_CALIBER——主车型帖 + 排除官方/经销商/营销号
    （背调打标后候选池缩小）+ 排除无关帖。outerjoin AnalyzedPost 保留未分析帖
    （subject NULL 视为 self）。

    顺延补位（T1.3）：背调排除营销号后 top-N 可能填不满。取 2*N 缓冲候选（按
    互动降序），过滤最低互动门槛（likes+comments >= 5，不补评论为 0 的帖白烧
    API）后取前 N。可能仍不足 N，到此为止——不降阈值凑数。

    缺陷词帖定向全量（T1.2）：top-N 可能不含低互动的缺陷帖（故障帖天然互动
    偏低，但评论里藏着最有价值的吐槽）。在 top-N 选完后，额外查标题/正文含
    故障词（DEFECT_SEED_KEYWORDS 全量 12 词）但不在已选列表的帖，全量补评论
    （不受 top-N 限制、不受最低互动门槛约束——缺陷帖即使 0 互动也要采评论）。

    负面帖定向追加（T2/L1，2026-10-15）：缺陷词全量之外，每平台再按负面词表
    （NEGATIVE_PRESET_WORDS=缺陷词全集+维权/自燃/起火/断裂）预筛标题/正文
    命中且不在已选列表的帖，取互动降序前 comment_negative_extra_n() 追加
    （独立 N 上限，非全量——与缺陷词段的差异）。零互动负面帖也入选（与缺陷
    词段同语义：门槛会漏掉负面集中帖）。标记 _negative_directed 供
    fetch_top_comments 的 top-N cap 豁免。
    """
    from pipeline.collectors.platform_strategy import PLATFORM_MAP
    from pipeline.collectors.post_utils import DEFECT_SEED_KEYWORDS, NEGATIVE_PRESET_WORDS
    from models.schemas import LISTING_CALIBER, AnalyzedPost

    # 社媒平台名（full_name + code 两种可能都存于 DB.platform 列）。
    social_platforms: list[str] = []
    for full_name, code in PLATFORM_MAP.items():
        if full_name in _COMMENT_PLATFORMS:
            social_platforms.extend([full_name, code])

    posts: list[RawPost] = []
    for full_name, code in PLATFORM_MAP.items():
        n = comment_top_n(full_name)
        if n <= 0:
            continue
        # 2*N 缓冲候选：背调排除后候选池缩小，2x 缓冲给顺延补位留空间。
        # No published_at window here: the collector already time-boxes
        # ingestion (90-day collect range), and weibo/douyin posts often have
        # NULL published_at because the detail extractors don't yet return a
        # timestamp. Windowing in this selection silently dropped them and left
        # comment_summary permanently empty for those platforms.
        result = await session.execute(
            select(RawPost)
            .outerjoin(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
            .where(
                RawPost.vehicle_id == vehicle_id,
                RawPost.platform.in_([full_name, code]),
                *LISTING_CALIBER,
            ).order_by(
                desc(RawPost.likes * ENGAGEMENT_WEIGHT_LIKES
                     + RawPost.comments * ENGAGEMENT_WEIGHT_COMMENTS
                     + RawPost.shares * ENGAGEMENT_WEIGHT_SHARES)
            ).limit(n * 2)
        )
        candidates = result.scalars().all()
        # 最低互动门槛：likes+comments >= 5（评论为 0 的帖白烧 API，不补）。
        # 在 Python 层过滤以实现"顺延补位"——缓冲池内不达标的跳过，后续候选顶上。
        filtered = [p for p in candidates
                    if (p.likes or 0) + (p.comments or 0) >= 5]
        posts.extend(filtered[:n])

    # 缺陷词帖定向全量（T1.2）：top-N 外但含故障词的帖，全量补评论。
    # 不受 top-N / 互动门槛约束——缺陷帖即使 0 互动也要采评论（评论里藏着
    # 最有价值的吐槽，是缺陷话题监控的数据源）。仅社媒四平台（news 无评论）。
    already_ids = {p.id for p in posts}
    if already_ids:
        not_in_clause = RawPost.id.not_in(already_ids)
    else:
        not_in_clause = None  # top-N 为空时无需排除
    # 故障词命中任一即可（OR）：帖含"投诉"或"故障"或"异响"... 即定向补评论。
    # 每词 (title LIKE OR content LIKE)，词间再 OR——不能 AND（否则要求一帖含
    # 全部 12 个故障词才命中，逻辑错误）。2026-09-28 T1 全量启用 12 词（去 [:8]
    # 截断），与 expand_defect_keywords 口径一致。
    defect_word_clauses = [
        or_(RawPost.title.like(f"%{w}%"), RawPost.content.like(f"%{w}%"))
        for w in DEFECT_SEED_KEYWORDS
    ]
    defect_where = [
        RawPost.vehicle_id == vehicle_id,
        RawPost.platform.in_(social_platforms),
        *LISTING_CALIBER,
        or_(*defect_word_clauses),
    ]
    if not_in_clause is not None:
        defect_where.append(not_in_clause)
    defect_result = await session.execute(
        select(RawPost)
        .outerjoin(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
        .where(*defect_where)
    )
    defect_posts = defect_result.scalars().all()
    # 标记缺陷词帖：scheduler.fetch_top_comments 的每平台 top-N 上限对缺陷帖
    # 不生效（getattr 哨兵——SimpleNamespace 测试桩无此属性返回 False，保持
    # 既有 cap 测试行为不变）。
    for p in defect_posts:
        p._defect_directed = True  # type: ignore[attr-defined]
    posts.extend(defect_posts)

    # 负面帖定向追加（T2/L1）：每平台独立 cap（非缺陷词段的全量语义）。
    # 词表 OR 命中（与缺陷词段同构）；排序用与 top-N 段同一互动权重式，
    # 让"追加池内部"也按热度取头部；不受最低互动门槛约束。
    already_ids = {p.id for p in posts}
    for full_name, code in PLATFORM_MAP.items():
        n_extra = comment_negative_extra_n(full_name)
        if n_extra <= 0:
            continue
        neg_clauses = [
            or_(RawPost.title.like(f"%{w}%"), RawPost.content.like(f"%{w}%"))
            for w in NEGATIVE_PRESET_WORDS
        ]
        neg_where = [
            RawPost.vehicle_id == vehicle_id,
            RawPost.platform.in_([full_name, code]),
            *LISTING_CALIBER,
            or_(*neg_clauses),
        ]
        if already_ids:
            neg_where.append(RawPost.id.not_in(already_ids))
        neg_result = await session.execute(
            select(RawPost)
            .outerjoin(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
            .where(*neg_where)
            .order_by(
                desc(RawPost.likes * ENGAGEMENT_WEIGHT_LIKES
                     + RawPost.comments * ENGAGEMENT_WEIGHT_COMMENTS
                     + RawPost.shares * ENGAGEMENT_WEIGHT_SHARES)
            ).limit(n_extra)
        )
        neg_posts = list(neg_result.scalars().all())
        for p in neg_posts:
            p._negative_directed = True  # type: ignore[attr-defined]
            already_ids.add(p.id)
        posts.extend(neg_posts)
    return posts


# ── Comment summary prompt ────────────────────────────────────────────────

COMMENT_SUMMARY_PROMPT = """分析以下帖子评论区的整体情况：

帖子标题：{title}
帖子内容摘要：{content_snippet}
评论内容（按点赞数排序，前30条）：
{comments_text}

请输出 JSON：
{{"is_argumentative": true/false, "argument_detail": "", "genuine_themes": [], "genuine_sentiment": "positive/negative/mixed", "genuine_sentiment_score": 0.0, "summary": ""}}

如果评论区正常讨论，即使有不同意见，也不应标记为 argumentative。"""


# ── Comment summarizer ────────────────────────────────────────────────────

async def summarize_comments(
    comments: list[dict],
    title: str = "",
    content_snippet: str = "",
    max_comments: int = 30,
) -> dict | None:
    """Summarize a batch of comments via LLM. Returns None if below the minimum comment threshold."""
    if len(comments) < _MIN_COMMENTS_FOR_SUMMARY:
        return None
    top_comments = sorted(comments, key=lambda c: c.get("likes", 0), reverse=True)[:max_comments]
    comments_text = "\n".join(f"- {c['content']}" for c in top_comments)
    prompt = COMMENT_SUMMARY_PROMPT.format(
        title=title,
        content_snippet=content_snippet[:200],
        comments_text=comments_text,
    )
    pipeline = AnalysisPipeline()
    try:
        raw = await pipeline._call_api(prompt)
        result = extract_json_object(raw)
        if result is not None:
            return result
    except Exception:
        pass
    return None


class BatchAnalysisRunner:
    def __init__(self, session: AsyncSession, batch_size: int = 50, max_posts: int = MAX_POSTS_PER_RUN):
        self._session = session
        self._pipeline = AnalysisPipeline()
        self._batch_size = batch_size
        self._max_posts = max_posts

    async def _analyze_single_post(self, post: RawPost) -> dict:
        text = post.full_content if post.full_content else post.content
        return await self._pipeline.analyze_single(text)

    async def run_for_vehicle(self, vehicle_id: str) -> dict:
        vehicle = await self._session.get(Vehicle, vehicle_id)
        if not vehicle:
            return {"vehicle_id": vehicle_id, "analyzed": 0, "error": "Vehicle not found"}

        # Stage 0: Relevance filtering (rule engine + LLM)
        llm = LLMRelevanceChecker.from_config()
        refilter = RelevanceFilter(llm_checker=llm)
        filter_stats = await refilter.filter_vehicle(vehicle_id, self._session)
        if filter_stats.get("total", 0) > 0:
            logger.info("Relevance filter: %s", filter_stats)

        # v3：同品牌易混车型动态清单（subject 标注注入，防"星舰7→self"类错标）
        # M-1：active 优先 + ORDER BY name（确定性，项目"sorted 教训"）
        confusables: list[str] = []
        if vehicle.brand:
            rows = await self._session.execute(
                select(Vehicle.name).where(
                    Vehicle.brand == vehicle.brand,
                    Vehicle.id != vehicle_id,
                    Vehicle.status == "active",
                ).order_by(Vehicle.name)
            )
            confusables = [r[0] for r in rows.all() if r[0]]

        analyzed = 0
        while analyzed < self._max_posts:
            result = await self._session.execute(
                select(RawPost).where(
                    RawPost.vehicle_id == vehicle_id,
                    RawPost.analysis_status == "pending",
                ).limit(self._batch_size)
            )
            batch = result.scalars().all()
            if not batch:
                break

            post_dicts = [
                {"id": p.id, "content": p.full_content if p.full_content else p.content}
                for p in batch
            ]
            analyses = await self._pipeline.analyze_batch(
                post_dicts, vehicle_name=vehicle.name, vehicle_brand=vehicle.brand,
                confusables=confusables,
            )
            for post, analysis in zip(batch, analyses):
                confidence = analysis.get("confidence", 0.0)
                model_name = self._pipeline._model or "unknown"
                self._session.add(AnalyzedPost(
                    id=str(uuid.uuid4()),
                    post_id=post.id,
                    vehicle_id=vehicle_id,
                    sentiment=analysis["sentiment"],
                    event_tags=json.dumps(analysis.get("event_tags", []), ensure_ascii=False),
                    opinion_tags=json.dumps(analysis.get("opinion_tags", []), ensure_ascii=False),
                    confidence=max(0.0, min(1.0, confidence)),
                    model_used=model_name,
                    dim_sentiment=json.dumps(analysis.get("dim_sentiment", {}), ensure_ascii=False),
                    subject=analysis.get("subject", "self"),
                    subject_name=analysis.get("subject_name", ""),
                ))
                post.analysis_status = "analyzed"
                analyzed += 1

            await self._session.commit()

        return {"vehicle_id": vehicle_id, "analyzed": analyzed}

    async def run_comment_summaries(self, vehicle_id: str) -> int:
        """Generate LLM comment summaries for per-platform top posts (>= 5 comments).

        Post selection is shared with fetch_top_comments via
        select_top_posts_for_comments — summaries target exactly the posts whose
        comments were fetched (Bug 6 alignment). Returns count generated."""
        top_posts = await select_top_posts_for_comments(self._session, vehicle_id)

        # 1. 串行收集每个 post 的 comment_dicts（session 串行约束）
        tasks = []  # [(post, comment_dicts), ...]
        for post in top_posts:
            comments_result = await self._session.execute(
                select(PostComment).where(
                    PostComment.post_id == post.id
                ).order_by(desc(PostComment.likes))
            )
            comments = comments_result.scalars().all()
            if len(comments) < _MIN_COMMENTS_FOR_SUMMARY:
                continue
            comment_dicts = [{"content": c.content, "likes": c.likes or 0} for c in comments[:30]]
            tasks.append((post, comment_dicts))

        # 2. 并行 LLM 摘要（无 DB 操作，安全并发；Semaphore(5) 限流防 LLM 限流）
        sem = asyncio.Semaphore(5)

        async def _summarize(cd, title, snippet):
            async with sem:
                return await summarize_comments(cd, title=title, content_snippet=snippet)

        summaries = await asyncio.gather(*[
            _summarize(cd, post.title or "", post.content or "") for post, cd in tasks
        ]) if tasks else []

        # 3. 串行写回 AnalyzedPost.comment_summary（session）
        count = 0
        for (post, _), summary in zip(tasks, summaries):
            if not summary:
                continue
            ap_result = await self._session.execute(
                select(AnalyzedPost).where(AnalyzedPost.post_id == post.id)
            )
            ap = ap_result.scalars().first()
            if ap:
                ap.comment_summary = json.dumps(summary, ensure_ascii=False)
                count += 1

        await self._session.commit()
        return count

    async def run_comment_analysis(self, vehicle_id: str) -> int:
        """评论打标入口：POLARITY_ENGINE 路由（2026-10-20 引擎切换 change）。

        - deepseek（默认）：API 引擎（pipeline/analysis/deepseek_polarity.py），
          无 GPU 依赖，TAG_IN_SERVICE 门不适用——服务内/03:00 计划任务/
          采集管线 Phase 6 直接打标（治覆盖率掉档根因：门关后无人夜跑）。
          批级引擎失败 fail-soft：已 commit 批次保留，当批不写留队列。
        - local（回退）：本地 Qwen3-4B 老路径，TAG_IN_SERVICE 门语义不变。
        env 调用时读取（T3 事故教训：模块级捕获会击穿 monkeypatch 隔离）。
        """
        _engine = os.environ.get("POLARITY_ENGINE", "deepseek").strip().lower()
        if _engine == "local":
            return await self._run_comment_analysis_local(vehicle_id)
        if _engine != "deepseek":
            # 隔审 P2-3：拼写错（如 "locale"）不再静默 fail-open 到 deepseek
            logger.warning("POLARITY_ENGINE=%r 非法（应为 deepseek/local），按 deepseek 处理", _engine)
        return await self._run_comment_analysis_deepseek(vehicle_id)

    async def _run_comment_analysis_deepseek(self, vehicle_id: str) -> int:
        """DeepSeek v4-flash 极性直出（引擎与口径断点见 deepseek_polarity.py 头注）。

        队列/哨兵语义与 local 路径一致：两列皆空才入选；空内容与不可解析写
        哨兵 "none"。批级引擎失败（DeepSeekPolarityError）log + break——
        当批不写库留 NULL 队列下次再标（传输失败值得重试，区别于真不可解析）。
        单次运行上限 env DS_POLARITY_MAX_PER_RUN（默认 5000）防失控烧钱；
        批粒度检查（整批跑完才判），与 500 条/批 commit 模式对齐。
        """
        from pipeline.analysis.deepseek_polarity import tag_polarity_batch, DeepSeekPolarityError

        _cap = env_int("DS_POLARITY_MAX_PER_RUN", 5000)
        total_analyzed = 0
        while total_analyzed < _cap:
            result = await self._session.execute(
                select(PostComment).where(
                    PostComment.vehicle_id == vehicle_id,
                    or_(PostComment.comment_polarity.is_(None), PostComment.comment_polarity == ""),
                    or_(PostComment.dim_sentiment.is_(None), PostComment.dim_sentiment == ""),
                ).limit(500)
            )
            comments = result.scalars().all()
            if not comments:
                break
            valid = [c for c in comments if c.content and c.content.strip()]
            # 先调 API 后写库：失败时本批零写入（哨兵也不写），全部留队列
            try:
                batch_results = await tag_polarity_batch([c.content for c in valid])
                if len(batch_results) != len(valid):
                    # 隔审 P2-4：短列表若放行会 zip 截断、尾部静默落 "none"
                    # 哨兵（不可逆标记）——契约破坏即跳过本批
                    raise DeepSeekPolarityError(
                        f"引擎返回长度不等（{len(batch_results)}≠{len(valid)}），本批跳过")
            except DeepSeekPolarityError as e:
                logger.warning("DeepSeek polarity 批失败（已打 %d 条保留，当批留队列）: %s",
                               total_analyzed, e)
                break
            pols = {c.id: p for c, p in zip(valid, batch_results)}
            for comment in comments:
                p = pols.get(comment.id)
                # None=不可解析（重试无益）→ 哨兵；不在 pols=空内容 → 哨兵
                comment.comment_polarity = p if p in ("1", "0", "-1") else "none"
            await self._session.commit()
            total_analyzed += len(valid)
            logger.info("Comment polarity(deepseek): vehicle=%s batch=%d total=%d",
                        vehicle_id, len(valid), total_analyzed)
        return total_analyzed

    async def _run_comment_analysis_local(self, vehicle_id: str) -> int:
        """Analyze comments with local ABSA model for dimension sentiment.

        门（2026-10-17 用户拍板 B）：TAG_IN_SERVICE 默认 0=服务内不载模型
        （凌晨自动轮曾自行拉起模型占 4.4GB 显存——三台"超时"的慢相位即此）。
        手动夜跑 scripts/run_comment_tagging.py 顶部自带 TAG_IN_SERVICE=1。
        2026-10-20 起为 POLARITY_ENGINE=local 回退路径（默认已切 deepseek）。

        全量循环清零：每批 500 条待打标评论，commit + 累加，直到清空为止。
        predict_batch 抛错自然向上传播（出错即停，已 commit 批次保留）；
        下次调用会接住剩下的评论。镜像 run_for_vehicle 的循环模式。

        T5.2（ABSA A 方案）：模型未加载时返回 0 但不静默——调用方应通过
        LocalABSAModel.get()._loaded 判断 comment_model_available 显式回传前端。

        双轨（2026-10-16 舆情降本 T4，方案 §4）：
        - 队列：comment_polarity 与 dim_sentiment **两列皆空**才入选——老评论
          （已有 dim）永不重标；
        - 极性直出模式（env COMMENT_POLARITY_DIRECT，默认开）：predict_batch
          (polarity=True)，结果写 comment_polarity 列（"1"/"0"/"-1"；解析失败
          或空内容写哨兵 "none" 防队列死循环，对齐维度模式 "{}" 语义），
          **不写 dim_sentiment**——新评论不再出维度（口径断点，切换日后生效）；
        - 维度模式（env 关闭=回退）：走既有逻辑，写 dim_sentiment。
        env 调用时读取（T3 事故教训：模块级捕获会击穿 monkeypatch 隔离）。
        """
        if os.getenv("TAG_IN_SERVICE", "0").strip() != "1":
            return 0  # 门：服务内打标关（B 决策）——队列留手动夜跑清

        from pipeline.analysis.local_absa import LocalABSAModel
        from utils.config import load_api_config

        _polarity_direct = os.environ.get("COMMENT_POLARITY_DIRECT", "1").strip().lower() \
            not in ("0", "false", "no", "off")

        local_model = LocalABSAModel.get()
        if not local_model._loaded:
            config = load_api_config()
            local_cfg = config.get("local_model", {})
            local_path = local_cfg.get("path", "") or os.environ.get("LOCAL_MODEL_PATH", "")
            if local_path and os.path.exists(os.path.join(local_path, "adapter_config.json")):
                local_model.load(local_path)
            else:
                logger.warning("Local ABSA model path not configured, skipping comment analysis")
                return 0  # 调用方通过 LocalABSAModel.get()._loaded 判断 comment_model_available

        total_analyzed = 0
        while True:
            result = await self._session.execute(
                select(PostComment).where(
                    PostComment.vehicle_id == vehicle_id,
                    or_(PostComment.comment_polarity.is_(None), PostComment.comment_polarity == ""),
                    or_(PostComment.dim_sentiment.is_(None), PostComment.dim_sentiment == ""),
                ).limit(500)
            )
            comments = result.scalars().all()
            if not comments:
                break

            texts = [c.content for c in comments if c.content and c.content.strip()]
            valid = [c for c in comments if c.content and c.content.strip()]
            # 空内容评论也标记为已处理（哨兵），否则会永久留在 NULL 队列导致死循环
            for comment in comments:
                if comment not in valid:
                    if _polarity_direct:
                        comment.comment_polarity = "none"
                    else:
                        comment.dim_sentiment = "{}"
            # to_thread：torch 同步推理放线程池，避免阻塞 uvicorn 事件循环
            if _polarity_direct:
                batch_results = await asyncio.to_thread(
                    local_model.predict_batch, texts, 16, True)
                for comment, pol in zip(valid, batch_results):
                    comment.comment_polarity = pol if pol in ("1", "0", "-1") else "none"
            else:
                batch_results = await asyncio.to_thread(local_model.predict_batch, texts)
                for comment, res in zip(valid, batch_results):
                    dims = res.get("dim_sentiment", {})
                    comment.dim_sentiment = json.dumps(dims, ensure_ascii=False) if dims else "{}"

            await self._session.commit()
            total_analyzed += len(valid)
            logger.info("Comment ABSA: vehicle=%s mode=%s batch=%d total=%d",
                        vehicle_id, "polarity" if _polarity_direct else "dim", len(valid), total_analyzed)
        return total_analyzed

    async def run_all_pending(self) -> list[dict]:
        result = await self._session.execute(
            select(RawPost.vehicle_id).where(
                RawPost.analysis_status == "pending"
            ).distinct().limit(10)
        )
        vehicle_ids = [row[0] for row in result.all()]

        results = []
        for vid in vehicle_ids:
            r = await self.run_for_vehicle(vid)
            results.append(r)
        return results
