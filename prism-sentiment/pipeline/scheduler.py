import asyncio
import json
import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select, func, desc, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.pipeline_state import PipelineProgress, PlatformProgress, pipeline_progress
from models.schemas import CollectionStatus, HeatMetric, PostComment, RawPost, SearchIndexMetric, Vehicle
from pipeline.analysis.deduplicator import deduplicate, resolve_note_id
from pipeline.collectors.full_text_crawler import crawl_full_text
from pipeline.collectors.index_collector import IndexCollector
from pipeline.collectors.news_collector import NewsCollector  # 2026-10-15 R31 停采：仅归档保留（方法不再被调度）
from pipeline.collectors.chezhiwang_collector import ChezhiwangCollector
from pipeline.collectors.post_utils import expand_defect_keywords
import httpx

from pipeline.collectors.platform_strategy import get_strategy
from pipeline.collectors.providers import collect_providers
from pipeline.collectors.tikhub_collector import (
    TikHubAuthError, TikHubError, TikHubCollector, TikHubBudgetExceeded,
)
from pipeline.platforms import SOCIAL_PLATFORMS, normalize_platform, platform_label
# v3 C-1：已知车别名（与语义层共享 _KNOWN_ALIASES，采集 AND 门 alias 组放行）
from pipeline.analysis.relevance_filter import get_vehicle_aliases
from utils.config import env_int

logger = logging.getLogger(__name__)

_CRAWL_CONCURRENCY = env_int("CRAWL_CONCURRENCY", 5)
# 2026-10-15 舆情降本（R40）：initial 首采窗 90→30 天（与 POST_RETENTION_DAYS=30
# 对齐，后 60 天采了即删白花钱）；env INITIAL_WINDOW_DAYS 可调回。
_INITIAL_WINDOW_DAYS = env_int("INITIAL_WINDOW_DAYS", 30)
_BRAND_TOKEN_RE = re.compile(r'[一-鿿]+|[A-Za-z0-9]+')

# ── 成本告警（E4）──────────────────────────────────────────────────────
# 402/余额耗尽首现推送：TikHubAuthError 涵盖 401/403/402 三类
# 账户级错误，但只有 402（余额耗尽）是"成本"事件——key 失效/账户封禁不会自愈
# 需充值，402 会且会反复触发计费空转。按 vehicle_id 去重避免同车多平台重复告警。
_alert_402_sent: set[str] = set()

# F-14：webhook 推送用的模块级线程池（避免每次 _alert_402 创建泄漏）
import concurrent.futures
_webhook_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def _is_balance_error(err: Exception) -> bool:
    """识别 402/余额耗尽类账户错误（区别于 401 key 失效 / 403 账户封禁）。

    TikHub: 错误信息含 "HTTP 402"；历史 OneAPI 文案 code=301 与 HTTP 302
    （OneAPI 已退役，保留匹配防未来 provider 复用同类文案）；外加 "余额" /
    "balance" / "insufficient" / "quota exceeded" 措辞。
    """
    msg = str(err).lower()
    return any(k in msg for k in (
        "402", "301", "302", "quota exceeded", "余额", "insufficient", "balance",
    ))


def _alert_402(vehicle_id: str, provider: str, err: Exception):
    """402 余额耗尽首现告警（日志 + 可选 webhook）。

    非余额类账户错误（401/403）不触发成本告警——它们走 env_warning 可见化
    但不属于"成本"事件。按 vehicle_id 去重：同车多平台共享同一 provider
    账户，首现后其余平台只会重复刷屏。
    """
    if not _is_balance_error(err):
        return
    if vehicle_id in _alert_402_sent:
        return
    _alert_402_sent.add(vehicle_id)
    logger.error("[COST ALERT] %s 余额耗尽（402）——vehicle=%s: %s",
                 provider, vehicle_id, err)
    webhook = os.getenv("COST_ALERT_WEBHOOK")
    if webhook:
        # F-14：模块级线程池 fire-and-forget（code-review #3：原每次创建泄漏）
        try:
            import httpx
            _webhook_executor.submit(httpx.post, webhook, json={
                "text": f"[成本告警] {provider} 余额耗尽（402），"
                        f"vehicle={vehicle_id}：{err}",
            }, timeout=10)
        except Exception as we:
            logger.warning("COST_ALERT_WEBHOOK 推送失败: %s", we)


# ── 预算护栏登记（T2/L6 v2，2026-10-15 舆情降本）────────────────────────
async def register_budget_skip(
    session: AsyncSession, current_vehicle_id: str, err: str,
) -> list[str]:
    """预算触顶时：当前车标 budget_capped + 登记当日其余未采 active 车。

    落法（directive 允许自选，选最简不破流程）：daily_update 是逐车串行触发
    API，触顶时 scheduler 只知道当前车——"剩余未采车"由本函数当场算：
    active 车中排除当前车与今日已完成采集的车（collection_status.
    last_collected_at 落在今日），登记进触顶车行的 skipped_vehicles JSON
    （{"date", "vehicles":[车名]}）。后续车再被触发会秒败（_send 首调用即
    抛），各自再登记一次同值——幂等无害。模块级函数便于单测直测。
    """
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (await session.execute(
        select(Vehicle, CollectionStatus)
        .outerjoin(CollectionStatus, CollectionStatus.vehicle_id == Vehicle.id)
        .where(Vehicle.status == "active")
    )).fetchall()
    collected_today: set[str] = set()
    name_by_id: dict[str, str] = {}
    for v, cs in rows:
        name_by_id[v.id] = v.name
        if cs is not None and cs.last_collected_at and cs.last_collected_at >= today_start:
            collected_today.add(v.id)
    skipped = sorted(
        name for vid, name in name_by_id.items()
        if vid != current_vehicle_id and vid not in collected_today
    )
    payload = json.dumps(
        {"date": today_start.date().isoformat(), "vehicles": skipped},
        ensure_ascii=False)
    status_row = (await session.execute(
        select(CollectionStatus).where(
            CollectionStatus.vehicle_id == current_vehicle_id,
            CollectionStatus.source == "all",
        )
    )).scalars().first()
    if status_row is None:
        status_row = CollectionStatus(
            id=str(uuid.uuid4()), vehicle_id=current_vehicle_id, source="all",
            mode="incremental")
        session.add(status_row)
    status_row.status = "budget_capped"
    status_row.error_message = err
    status_row.skipped_vehicles = payload
    await session.commit()
    logger.warning("[BUDGET CAP] vehicle=%s 触顶；当日未采登记 %d 台: %s",
                   current_vehicle_id, len(skipped), "、".join(skipped))
    return skipped

# 平台级限速 token bucket（A4）：车型级 _CRAWL_CONCURRENCY 只管车型并发，
# 多车并发采同一平台时会同时打到 provider API 触发 429/风控。每平台一个
# asyncio.Semaphore 限制同平台并发搜索数，跨车型共享。Semaphore(N) 近似
# N RPS（单次搜索通常 ≥1s）；与 strategy.inter_request_delay 互补——后者
# 管单车内同平台关键词间隔，本信号量管跨车型同平台并发。
_PLATFORM_RPS = {
    "douyin": 2,       # TikHub 抖音 2/s
    "xiaohongshu": 2,
    "kuaishou": 2,
    "weibo": 2,
}
_platform_sems: dict[str, asyncio.Semaphore] = {}


def _get_platform_sem(platform: str) -> asyncio.Semaphore:
    """惰性创建并缓存每平台信号量。未知平台默认 2。"""
    if platform not in _platform_sems:
        rps = _PLATFORM_RPS.get(platform, 2)
        _platform_sems[platform] = asyncio.Semaphore(rps)
    return _platform_sems[platform]


def _extract_brand_keywords(name: str, brand: str) -> list[str]:
    """Extract brand-specific keywords from vehicle name and brand.

    Splits on Chinese/alphanumeric boundaries so "启源Q05" yields ["启源","Q05"].
    Tokens shorter than 2 chars are discarded (avoids single-char false positives
    like "元" from "元PLUS"). Brand tokens are included to catch industry news
    that mentions the brand without the model name.

    Returns deduplicated list (case-insensitive).
    """
    return _dedup_tokens(_raw_tokens(name) + _raw_tokens(brand))


def _raw_tokens(text: str) -> list[str]:
    if not text:
        return []
    return [p for p in _BRAND_TOKEN_RE.findall(text) if len(p) >= 2]


def _dedup_tokens(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


# v3 审计（2026-10-08）：字母数字词元子串命中是跨车型混入根因之一——
# "A7"⊂奥迪A7L/索尼A7V、"03"⊂mona03、"Model"（Model Y 丢单字符 Y 后）⊂Model 3。
# 匹配时对含字母数字的词元加前后非字母数字边界；纯中文词元维持子串
# （中文车名无前后缀拼接形态，边界无收益且有害："银河"须命中"吉利银河A7"）。
_TOKEN_BOUNDARY_RE = {}  # token → 编译好的 regex（惰性缓存）


def _token_in_text(token: str, text: str) -> bool:
    """词元是否命中文本（字母数字词元带边界；文本内部统一 lower，不依赖调用方）。"""
    text = text.lower()
    if any(c.isascii() and c.isalnum() for c in token):
        # 含 ASCII 字母/数字的词元（A7/Model/03/银河A7 的 A7 部分）：边界匹配
        key = token.lower()  # M-7：缓存 key 统一小写（A7/a7 不重复编译）
        pat = _TOKEN_BOUNDARY_RE.get(key)
        if pat is None:
            pat = re.compile(rf'(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])')
            _TOKEN_BOUNDARY_RE[key] = pat
        return bool(pat.search(text))
    return token.lower() in text


def _name_tokens(name: str, brand: str = "") -> list[str]:
    """车名级词元（不含品牌词）——社媒放行要求全命中（AND）。

    "银河A7" → ["银河","A7"]：帖须同时含两者，"吉利银河星舰7"（无 A7）
    不再放行，"25款银河A7 EM星舰版"（两者都有）仍放行。
    品牌前缀剥离（与 _has_self_name 同款）："比亚迪海豚"→["海豚"]（原整词
    命中会拦掉只写短名的帖），strip 后空/单字符则回退整名。
    """
    stripped = name
    if brand and name.startswith(brand):
        rest = name[len(brand):].strip()
        if len(rest) >= 2:
            stripped = rest
    return _dedup_tokens(_raw_tokens(stripped))


def rotate_defect_words(
    defects: list[str],
    today: date | None = None,
    rotate_days: int | None = None,
    pick: int = 3,
) -> list[str]:
    """缺陷词 P1 轮换（2026-10-15 舆情降本 R43）：按日期错位取 pick 个。

    12 缺陷词分 4 组（每组 pick=3），隔 DEFECT_ROTATE_DAYS 天换一组、4 组轮
    一圈——缺陷词覆盖周期从 1 天放宽到 2-3 天（检出延迟代价）。确定性：同
    一日期必出同一组（同日多次调用一致）。
    ⚠️ 轮换换的是**构成**不换**数量**：仍 6 词/天（core1+双2+轮换缺陷3）≈18
    次搜索/车——P1 提案文中"18→12 次/省 650 元月"的算式与本实现不符（若要
    该节省需另行拍板 pick=1 或社媒 max_keywords=4；且 10-16 判别实验实证词近
    可互换，缩量影响存疑）。rotate_days<=1 退化为"永远前 pick 个"（回退档）。
    轮换只作用于社媒搜索选词；缺陷评论池（DEFECT_SEED_KEYWORDS 全量定向）
    与车质网不受影响。
    """
    if len(defects) <= pick:
        return list(defects)
    if rotate_days is None:
        rotate_days = env_int("DEFECT_ROTATE_DAYS", 2)
    if rotate_days <= 1:
        return list(defects[:pick])
    groups = [defects[i:i + pick] for i in range(0, len(defects), pick)]
    g = groups[((today or date.today()).toordinal() // rotate_days) % len(groups)]
    return list(g)


class CollectionScheduler:
    def __init__(self, session: AsyncSession):
        self._session = session
        self._index = IndexCollector()
        # 社媒采集 provider（2026-09-27 OneAPI 退役）：四平台全量 TikHub
        # （搜索/评论/批量统计），路由表见 pipeline/collectors/providers.py
        self._tikhub = TikHubCollector()
        self._news = NewsCollector()
        self._chezhiwang = ChezhiwangCollector()

    # ── Keyword helpers ─────────────────────────────────────────────────

    def _get_core_keyword(self, vehicle: Vehicle) -> str:
        """Return the first (primary) search keyword."""
        kws = json.loads(vehicle.search_keywords) if vehicle.search_keywords else [vehicle.name]
        return kws[0] if kws else vehicle.name

    async def _expand_keywords_if_needed(self, vehicle: Vehicle) -> list[str]:
        """返回车辆基础搜索词（LLM 扩词链已下线）。

        2026-10-15 舆情降本（R31）：LLM 扩词的唯一消费者是 news（社媒 6 词截断
        用不上扩词），news 停采后整条 keyword_expander 链下线——直接返回
        search_keywords。expanded_keywords 老缓存字段保留在库、不再读写。
        """
        return json.loads(vehicle.search_keywords) if vehicle.search_keywords else [vehicle.name]

    def _select_keywords(self, all_keywords: list[str], max_kw: int) -> list[str]:
        """Select up to max_kw keywords (core keyword always first)."""
        if not all_keywords:
            return []
        return all_keywords[:max_kw]

    def _build_collection_keywords(
        self, base_keywords: list[str], vehicle_name: str, brand: str,
    ) -> list[str]:
        """合并主关键词与（轮换后的）缺陷扩词为最终采集关键词列表。

        2026-10-15 舆情降本（R43）拼序调整：core + 双关键词2 + 轮换缺陷词3 +
        其余基础词。社媒 _select_keywords 按 max_keywords=6 截断时，选出的
        6 词构成 = 核心1 + 双关键词2 + 缺陷词3（P1 轮换，隔天换组）。
        ⚠️ max_keywords 若回调到 <6，缺陷词会被挤出选区（核心/双词排在前）。
        历史注：旧拼序 core+缺陷+rest 是 max=5 时代防缺陷词被 LLM 扩词挤出的
        设计；扩词链已下线（R31）、max=6（R32），缺陷词排 4-6 位仍在选区内。
        """
        defect_combos = expand_defect_keywords(vehicle_name, brand)
        if not defect_combos:
            return list(base_keywords)
        core = base_keywords[:1]
        rest = base_keywords[1:]
        rotated = rotate_defect_words(defect_combos)
        seen = set(core) | set(rest)
        defect_unique = [k for k in rotated if k not in seen]
        return core + rest[:2] + defect_unique + rest[2:]

    # ── Phase 1: News collection (zero risk) ────────────────────────────

    async def _collect_news(
        self, vehicle_id: str, keywords: list[str],
        start_date: str, end_date: str,
        progress: PlatformProgress,
    ) -> list[dict]:
        """Collect from all news APIs. Zero risk, all keywords.

        ⚠️ 2026-10-15 R31 停采：本方法不再被 collect_vehicle 调度（news 阶段块
        已摘除），保留方法体仅为兼容既有测试的 patch 目标——勿在新代码中调用。
        """
        strategy = get_strategy("news")
        all_posts: list[dict] = []
        for kw in keywords:
            try:
                posts = await self._news.search_all(kw, start_date, end_date)
                all_posts.extend(posts)
            except Exception as e:
                logger.warning("News search failed for '%s': %s", kw, e)
        progress.posts_found = len(all_posts)
        logger.info("News: %d posts for %d keywords", len(all_posts), len(keywords))
        return all_posts

    async def _collect_chezhiwang(
        self, vehicle_id: str, vehicle_name: str,
        start_date: str, end_date: str,
        progress: PlatformProgress,
    ) -> list[dict]:
        """车质网投诉帖采集（A5）。按车系 seriesId 直采 BBS 列表 + 详情正文。

        质量投诉是缺陷监控的种子数据，独立于新闻源采集（news 走搜索 API，
        车质网按车系版块直采，两者互补不重叠）。无 seriesId 映射的车型静默跳过。

        窗口（2026-09-28 修订）：统一 30 天 + max_pages=3，与社媒增量窗对齐。
        原首次 180 天宽窗设计被推翻（用户拍板：车质网只要近 30 天，丢帖子也
        丢评论，与社媒一致）。车质网帖在 _store_posts 里跳过社媒 min_date floor
        （见 _store_posts 的 platform=='chezhiwang' 豁免）——incremental 模式
        下社媒 start_date≈3 天前，若不豁免，4~30 天前的投诉帖会被社媒 floor
        误杀。
        """
        window_days = 30
        max_pages = 3
        cz_start = (date.today() - timedelta(days=window_days)).isoformat()
        cz_end = date.today().isoformat()
        logger.info("车质网窗口 vehicle=%s window=%dd pages=%d range=%s~%s",
                    vehicle_name, window_days, max_pages, cz_start, cz_end)
        try:
            posts = await self._chezhiwang.search(
                vehicle_name, cz_start, cz_end, max_pages=max_pages)
        except Exception as e:
            logger.warning("车质网采集失败 vehicle=%s: %s", vehicle_name, e)
            posts = []
        progress.posts_found = len(posts)
        logger.info("车质网: %d 投诉帖 for %s", len(posts), vehicle_name)
        return posts

    # ── Phase 2: social platform collection (provider-routed, sequential) ─

    async def _resolve_collector(
        self, key: str,
    ) -> tuple[TikHubCollector | None, str]:
        """按路由 key 解析 collector——单 provider（TikHub），无备胎语义。

        返回 (collector, provider)。key 未知返回 (None, "")；TikHub 未配置
        key（本地配置检查，无免费探活端点）返回 (None, "tikhub")，调用方按
        平台 skip + env_warning 可见化处理。
        """
        if key not in collect_providers():
            logger.warning("未知采集路由 key=%s，无可用 collector", key)
            return None, ""
        if await self._tikhub.is_available():
            return self._tikhub, "tikhub"
        return None, "tikhub"

    async def _collect_social_platform(
        self, vehicle_id: str, platform: str, keywords: list[str],
        progress: PlatformProgress,
        mode: str = "incremental",
        window_days: int = 7,
        collector: TikHubCollector | None = None,
        provider: str = "",
    ) -> tuple[list[dict], list[dict]]:
        """Collect from a social platform via the routed provider collector.

        collector 由调用方解析后传入（None 时本方法自解析，解析不到则返回
        空）。单 provider（TikHub，2026-09-27 OneAPI 退役）后 provider 参数
        仅用于日志/告警标签。
        mode：微博 initial 3 页扩量，增量窄窗；
        window_days：抖音/小红书/快手时间窗档位（initial 90 天 → 180/half_year）。
        """
        if collector is None:
            collector, provider = await self._resolve_collector(
                "douyin_search" if platform == "douyin" else platform)
            if collector is None:
                logger.warning("%s 采集 provider 未配置，返回空", platform)
                progress.posts_found = 0
                return [], []
        strategy = get_strategy(platform)
        selected_kw = self._select_keywords(keywords, strategy.max_keywords)

        async def _search_with_retry(c, kw) -> tuple[list[dict], list[dict]]:
            """单关键词搜索，网络/超时类错误指数退避重试 2 次（1s, 2s）。

            分层容错（A7）：
            - httpx 网络异常（超时/连接失败/ConnectionError）→ 本层重试 2 次，
              仍失败则记 fetch_failures 跳过该词（collector 内层通常已先重试，
              这里兜底漏网的网络异常）。
            - TikHubError（非 auth）= collector 内部重试已耗尽（上游 429 持续
              / 业务失败）→ 不再重试，交上层记 fetch_failures。
            - TikHubAuthError（401/403/402）→ raise 不断管线。
            - 其余异常（KeyError/AttributeError 等代码 bug）→ 不捕获直接抛，
              让 bug 暴露而非伪装成"完成"。
            """
            for attempt in range(3):  # 首次 + 2 次重试
                try:
                    # 平台级限速（A4）：跨车型共享，多车并发打同平台时
                    # 排队等令牌，避免叠加触发 provider 429/风控
                    async with _get_platform_sem(platform):
                        return await c.search(kw, platform, window_days=window_days, mode=mode)
                except TikHubAuthError:
                    raise  # 账户级错误（401/403/余额），重试只会白烧
                except (httpx.TimeoutException, httpx.ConnectError, ConnectionError) as e:
                    if attempt < 2:
                        logger.warning(
                            "collect '%s' kw='%s' 网络异常 (attempt %d/3): %s，退避重试",
                            platform, kw, attempt + 1, e)
                        await asyncio.sleep(2 ** attempt)  # 1s, 2s
                        continue
                    progress.fetch_failures.append(kw)
                    logger.warning(
                        "collect '%s' kw='%s' 网络重试耗尽，跳过该词", platform, kw)
                    return [], []
                # 其余异常（TikHubError collector 已重试耗尽、
                # KeyError/AttributeError 代码 bug）落到外层 _search_all 处理
            return [], []

        async def _search_all(c) -> tuple[list[dict], list[dict]]:
            posts, comments = [], []
            for kw in selected_kw:
                try:
                    p, cm = await _search_with_retry(c, kw)
                    posts.extend(p)
                    comments.extend(cm)
                except TikHubAuthError:
                    raise  # 账户级错误，整平台终止（上层 collect_vehicle 进 env_warning）
                except TikHubError as e:
                    # collector 内部已重试耗尽（上游 429 持续 / 业务失败）→
                    # 记失败跳过该词，不拖垮整平台
                    progress.fetch_failures.append(kw)
                    logger.warning(
                        "collect '%s' kw='%s' 失败（collector 重试耗尽）: %s",
                        platform, kw, e)
                # 其余异常（KeyError/AttributeError 等代码 bug）不捕获，直接抛出
                if strategy.inter_request_delay > 0:
                    await asyncio.sleep(strategy.inter_request_delay)
            return posts, comments

        all_posts, all_comments = await _search_all(collector)
        progress.posts_found = len(all_posts)
        logger.info("collect %s: %d posts, %d comments for %d keywords",
                    platform, len(all_posts), len(all_comments), len(selected_kw))
        return all_posts, all_comments

    # ── Full-text enrichment ────────────────────────────────────────────

    async def _crawl_full_texts(self, posts: list[dict]) -> list[dict]:
        sem = asyncio.Semaphore(_CRAWL_CONCURRENCY)

        async def _limited_crawl(url: str, snippet: str):
            async with sem:
                return await crawl_full_text(url, snippet)

        crawl_jobs = []
        for post in posts:
            if post.get("source") in ("bocha", "anspire", "news") and post.get("url"):
                crawl_jobs.append(_limited_crawl(post["url"], post.get("content", "")))
            else:
                crawl_jobs.append(None)
        results = await asyncio.gather(
            *(j for j in crawl_jobs if j is not None), return_exceptions=True
        )
        ri = 0
        for i, post in enumerate(posts):
            if crawl_jobs[i] is None:
                continue
            if isinstance(results[ri], Exception):
                ri += 1
                continue
            crawl_result = results[ri]
            ri += 1
            if crawl_result and crawl_result.get("full_text"):
                post["full_content"] = crawl_result["full_text"]
        return posts

    # ── URL resolution & dedup ──────────────────────────────────────────

    async def _resolve_urls(self, posts: list[dict]) -> list[dict]:
        for post in posts:
            url = post.get("url", "")
            if url:
                note_id = await resolve_note_id(url)
                if note_id != url.rsplit("/", 1)[-1].split("?")[0]:
                    post["resolved_note_id"] = note_id
        return posts

    def _run_dedup(self, posts: list[dict]) -> list[dict]:
        return deduplicate(posts)

    @staticmethod
    def _remap_comments_to_kept_posts(
        pre_dedup_posts: list[dict], kept_posts: list[dict], comments: list[dict],
    ) -> list[dict]:
        """被当批次去重丢弃的帖，其评论搬迁到保留孪生帖（T2.4 评论 unmatched 修复）。

        根因（实采 55/365 unmatched 排查结论）：collector 在搜索内先抓评论，
        scheduler 随后才对帖做当批次 simhash 去重——近重复转发稿/多账号通稿
        内容近同但 URL 不同，被丢弃帖的评论 post_url 查无此帖，全进 unmatched。
        deduplicate 现在在丢弃帖上标记 ``duplicate_of_url``（保留孪生帖 URL），
        这里据此改写评论 post_url 指向保留帖，评论随帖存活而非白白丢弃。
        """
        kept_ids = {id(p) for p in kept_posts}
        url_remap: dict[str, str] = {}
        for p in pre_dedup_posts:
            if id(p) not in kept_ids:
                url = p.get("url", "")
                twin = p.get("duplicate_of_url") or ""
                # 无 URL 的帖不建映射（空键会把无主评论错挂到孪生帖）
                if url and twin and twin != url:
                    url_remap[url] = twin
        if not url_remap:
            return comments
        remapped = 0
        for c in comments:
            target = url_remap.get(c.get("post_url", ""))
            if target:
                c["post_url"] = target
                remapped += 1
        if remapped:
            logger.info("评论随帖去重搬迁: %d 条评论改挂保留孪生帖（%d 个被去重帖）",
                        remapped, len(url_remap))
        return comments

    async def _cross_batch_dedup(self, posts: list[dict], vehicle_id: str) -> list[dict]:
        """跨批次近似去重——新帖与近30天库内同前缀帖 simhash 比对。

        当批次去重（deduplicate）只挡同一次采集内的近似帖，跨天的微改稿/多
        账号转发稿穿透（实测"吉利星愿上市21个月累计…"12 条同前缀不同 URL 全
        入库）。本方法对近 30 天库内帖按标题前 12 字分桶，新帖落桶后与桶内帖
        simhash 比对（距离≤3 视为重复），把住跨批次咽喉。

        性能：近 30 天帖约 500-1000 条/车，前缀分桶后每桶 <10 条，simhash
        比对 O(桶内) 而非 O(n²)。标题为空的新帖无桶可落，直接放行（空标题
        帖由后续品牌过滤/入库守卫处理）。
        """
        from simhash import Simhash

        since = datetime.now() - timedelta(days=30)
        existing = (await self._session.execute(
            select(RawPost.id, RawPost.title).where(
                RawPost.vehicle_id == vehicle_id,
                RawPost.collected_at >= since,
            )
        )).all()

        # simhash band 分桶（LSH，2026-09-29 D-4）：替代前缀 12 字分桶。
        # 前缀分桶无法覆盖"吉利星愿最新报价" vs "星愿最新报价"类前缀不同的
        # 近似帖。band 分桶：64 位 simhash 切 4 个 16 位 band，每帖落 4 桶，
        # 新帖任一 band 命中桶则与桶内帖 simhash 全量比对（距离≤3 判重）。
        # 性能：O(band 数) 而非 O(n²)，近 30 天 500-1000 帖/车可控。
        buckets: dict[int, list[tuple[str, str]]] = {}
        for pid, title in existing:
            if not title:
                continue
            fp = Simhash(title)
            # 切 4 个 16 位 band 入桶
            fp_val = fp.value
            for b in range(4):
                band = (fp_val >> (b * 16)) & 0xFFFF
                buckets.setdefault(band, []).append((pid, title))

        # 新帖按 band 找桶，与桶内帖 simhash 比对
        result: list[dict] = []
        dropped = 0
        for post in posts:
            title = post.get("title", "") or ""
            if not title:
                result.append(post)
                continue
            new_fp = Simhash(title)
            fp_val = new_fp.value
            candidate_titles: list[str] = []
            seen_pids: set[str] = set()
            for b in range(4):
                band = (fp_val >> (b * 16)) & 0xFFFF
                for pid, existing_title in buckets.get(band, []):
                    if pid not in seen_pids:
                        seen_pids.add(pid)
                        candidate_titles.append(existing_title)
            is_dup = False
            for existing_title in candidate_titles:
                if new_fp.distance(Simhash(existing_title)) <= 3:
                    is_dup = True
                    break
            if is_dup:
                dropped += 1
            else:
                result.append(post)
        # 无条件输出拦截计数（T2.6）：0 拦截也打一行，日志存在即证明生效。
        logger.info("跨批次去重: %d/%d 帖被拦截（simhash band 分桶, vehicle=%s）",
                    dropped, len(posts), vehicle_id)
        return result

    # ── Storage ─────────────────────────────────────────────────────────

    async def _store_search_index(self, vehicle_id: str, points: list[dict]) -> int:
        """搜索指数点位 → SearchIndexMetric，按 (vehicle, date, source) 幂等。

        与 HeatMetric 分表：heat_calculator 对同日多行有删重逻辑，多 source
        行塞进去会被吞。重跑语义 = 同 source 覆盖该日期段（delete+insert）；
        PGY 返回固定近三月，历史回溯白赚。
        """
        from sqlalchemy import delete as sa_delete
        by_source: dict[str, list[dict]] = {}
        for p in points:
            by_source.setdefault(p.get("source", ""), []).append(p)
        stored = 0
        for source, items in by_source.items():
            dates = [date.fromisoformat(p["date"]) for p in items if p.get("date")]
            if not dates:
                continue
            await self._session.execute(
                sa_delete(SearchIndexMetric).where(
                    SearchIndexMetric.vehicle_id == vehicle_id,
                    SearchIndexMetric.source == source,
                    SearchIndexMetric.date.in_(dates),
                ))
            for p in items:
                if not p.get("date"):
                    continue
                self._session.add(SearchIndexMetric(
                    id=str(uuid.uuid4()),
                    vehicle_id=vehicle_id,
                    date=date.fromisoformat(p["date"]),
                    source=source,
                    keyword=p.get("keyword", ""),
                    index_value=float(p.get("index", 0)),
                ))
                stored += 1
        if stored:
            await self._session.commit()
        return stored

    async def _store_posts(self, vehicle_id: str, posts: list[dict], min_date: str | None = None,
                           vehicle_name: str = "", vehicle_brand: str = "",
                           aliases: list[str] | None = None) -> dict[str, int]:
        # URL 去重键 = 路径（去 query）。xhs 的 xsec_token / weibo 的 refer_flag
        # 是抓取凭证不是身份：同一笔记每次搜索 token 不同，按全 URL 比对会
        # 重复入库（2026-09-12 实证：同一 nid 最多 4 份，情感被重复帖带偏）。
        # 存储仍保留完整 URL（token 是详情/评论回链凭证），只做比对归一。
        seen_paths: dict[str, str] = {}   # path → 库内真实 URL（互动刷新定位用）
        existing = await self._session.execute(
            select(RawPost.url).where(RawPost.vehicle_id == vehicle_id)
        )
        for (url,) in existing:
            if url:
                seen_paths.setdefault(url.split("?", 1)[0], url)

        # 采集范围下限（min_date 不变，循环外算一次，避免每个 post 重复 parse）
        floor = None
        if min_date:
            try:
                floor = datetime.fromisoformat(min_date + "T00:00:00")
            except ValueError:
                floor = None

        # 品牌关键词过滤（采集层竞品根治 + v3 车名级收紧）
        # 社媒：车名级词元全命中（AND，带字母数字边界）——"银河A7"须同时含
        # "银河"和"A7"，星舰7/E5 等同品牌兄弟车型与奥迪A7L/索尼A7V 不再放行。
        # C-1（review）：aliases 各自生成一组词元，任一组全命中即放行——
        # "model3提车作业"（alias=model3）、"MONAM03车主群"（alias=MONAM03）、
        # "海狮06EV 510km旗舰"（alias=海狮06EV）等连写/简写拼法是本车帖不能丢。
        # （2026-10-15 R31：news 全词元 OR 分支随 news 停采摘除）
        aliases = aliases or []
        name_token_sets = [set(_name_tokens(vehicle_name, vehicle_brand))] if vehicle_name else []
        name_token_sets += [set(_name_tokens(a)) for a in aliases if a]
        name_token_sets = [s for s in name_token_sets if s]  # 空组（纯单字符名）剔除
        all_tokens = _extract_brand_keywords(vehicle_name, vehicle_brand) if (vehicle_name or vehicle_brand) else []

        # 作者分层（2026-09-15 Q5）：dealer 不再丢弃——打标入库，口碑类口径
        # 在查询层排除（AUTHENTIC_AUTHOR）；官号/4S 帖仍进热帖榜与声量
        # 行为背调（B1）：本批作者批量查近 90 天历史帖，内存分组——循环内
        # 不逐帖查 DB（防 N+1）。跨车型合计判定 marketing_account。
        from pipeline.collectors.post_utils import (
            classify_author_type, profile_author_behavior, strip_html,
            _PROMO_SIGNAL_RE,
        )

        authors_in_batch = {p.get("author", "") for p in posts if p.get("author")}
        hist_by_author: dict[str, list[dict]] = {}
        if authors_in_batch:
            since = datetime.now() - timedelta(days=90)
            hist_result = await self._session.execute(
                select(RawPost.author, RawPost.title, RawPost.content).where(
                    RawPost.author.in_(authors_in_batch),
                    RawPost.collected_at >= since,
                )
            )
            for author, title, content in hist_result.all():
                hist_by_author.setdefault(author or "", []).append(
                    {"title": title or "", "content": content or ""})

        count = 0
        filtered = 0
        count_by_platform: dict[str, int] = {}
        # （2026-10-15 R31：新闻跨源标题去重 preload 随 news 停采摘除——
        # anspire/bocha 下线后不再有 news 帖进本方法）
        for post in posts:
            url = post.get("url", "")
            path = url.split("?", 1)[0] if url else ""
            # 微博 title 常含 <a href> 超话链接，入库前剥标签（B3 统一安全网——
            # 对所有微博帖生效，不只某个搜索方法；news 等平台 title 可能含 < >
            # 比较符故只对 weibo 挂载）
            if post.get("platform") == "weibo":
                post["title"] = strip_html(post.get("title", "")) or ""
            if path and path in seen_paths:
                # Refresh engagement on already-stored posts — likes/comments/shares
                # change over time, and the old skip-left-them-stale behaviour meant
                # a re-collect never wrote back corrected counts (e.g. after fixing
                # DouyinExtractor.DETAIL_JS, the new numbers still didn't land).
                # P2-8 守卫：搜索快照缺统计时用 0 占位（抖音上游"选择性回填"），
                # 0 不覆盖库内真值——真值来自详情回填/互动刷新，只会更准。
                vals = {k: v for k, v in (
                    ("likes", int(post.get("likes") or 0)),
                    ("comments", int(post.get("comments") or 0)),
                    ("shares", int(post.get("shares") or 0)),
                ) if v}
                if vals:
                    await self._session.execute(
                        update(RawPost).where(
                            RawPost.url == seen_paths[path],
                            RawPost.vehicle_id == vehicle_id,
                        ).values(**vals)
                    )
                continue
            if path:
                seen_paths[path] = url

            # 品牌关键词白名单：v3 社媒车名级 AND（带边界）
            # 检查 title + content + full_content（全文抓取在入库前已完成）
            # （2026-10-15 R31：news 同稿标题去重与全词元 OR 分支随停采摘除）
            if name_token_sets or all_tokens:
                post_text_lower = f"{post.get('title', '')} {post.get('content', '')} {post.get('full_content', '') or ''}"
                # 社媒：任一 token-set 组全命中即放行（车名组 + 各 alias 组）；
                # 无任何组（如仅品牌名建车）用全词元 AND
                if not any(
                    all(_token_in_text(kw, post_text_lower) for kw in ts)
                    for ts in (name_token_sets or [set(all_tokens)])
                ):
                    filtered += 1
                    continue

            author_type = (
                profile_author_behavior(post.get("author", ""),
                                        hist_by_author.get(post.get("author", ""), []))
                or classify_author_type(
                    post.get("author", ""), post.get("title", ""),
                    vehicle_brand, vehicle_name)
            )

            published_at = None
            raw_date = post.get("published_at", "")
            if raw_date:
                try:
                    published_at = datetime.fromisoformat(raw_date)
                except (ValueError, TypeError):
                    pass

            # 过滤采集范围外的老帖（floor 已在循环外算好）
            # 新闻源可能返回带时区的时间戳，统一转 naive 再比较
            # 车质网用独立 30 天窗，不跟随社媒 min_date floor——incremental 模式
            # 下社媒 start_date≈3 天前，若不豁免车质网，4~30 天前的投诉帖会被
            # 社媒 floor 误杀（2026-09-29 code-review 实证：30 天窗仍丢帖）
            if floor and published_at and post.get("platform") != "chezhiwang":
                pub_cmp = published_at.replace(tzinfo=None) if published_at.tzinfo else published_at
                if pub_cmp < floor:
                    continue

            # 导流号标记（D-3）：只对 auto_media 帖判信号词，车评号保留
            post_text = f"{post.get('title', '')} {post.get('content', '')} {post.get('full_content') or ''}"
            is_promo = author_type == "auto_media" and bool(_PROMO_SIGNAL_RE.search(post_text))

            self._session.add(RawPost(
                id=str(uuid.uuid4()),
                vehicle_id=vehicle_id,
                source=post.get("source", "unknown"),
                platform=post.get("platform", ""),
                title=post.get("title", ""),
                content=post.get("content", ""),
                author=post.get("author", ""),
                url=url,
                published_at=published_at,
                likes=post.get("likes", 0),
                comments=post.get("comments", 0),
                shares=post.get("shares", 0),
                full_content=post.get("full_content"),
                author_type=author_type,
                is_promo=is_promo,
            ))
            count += 1
            plat = post.get("platform", "") or "unknown"
            count_by_platform[plat] = count_by_platform.get(plat, 0) + 1

        if filtered:
            logger.info("Brand filter: %d posts filtered out (name_token_sets=%s, all_tokens=%s), %d stored for %s",
                        filtered, name_token_sets, all_tokens, count, vehicle_id)
        await self._session.commit()
        return count_by_platform

    async def _store_comments(self, vehicle_id: str, comments: list[dict]) -> int:
        if not comments:
            return 0
        url_result = await self._session.execute(
            select(RawPost.id, RawPost.url).where(RawPost.vehicle_id == vehicle_id)
        )
        url_to_post_id: dict[str, str] = {}
        for post_id, url in url_result.all():
            if url:
                url_to_post_id[url] = post_id
                note_id = url.rsplit("/", 1)[-1].split("?")[0].split("#")[0]
                if note_id:
                    url_to_post_id[note_id] = post_id

        # 评论去重（2026-09-12 修）：每日增量会重抓同一批热帖的评论，此前
        # 无去重键导致同一条评论堆 N 份（M03 实测 4476 条里 1216 组重复、
        # 最狠 ×13），情感被重复样本带偏。两级键：平台评论 id（cid，权威）
        # 优先；无 cid 用 (post_id, author, content[:200]) 内容指纹兜底。
        existing_result = await self._session.execute(
            select(PostComment.cid, PostComment.post_id, PostComment.author,
                   PostComment.content).where(PostComment.vehicle_id == vehicle_id)
        )
        existing_cids: set[str] = set()
        existing_fp: set[tuple] = set()
        for cid, pid, author, content in existing_result.all():
            if cid:
                existing_cids.add(cid)
            existing_fp.add((pid, author, (content or "")[:200]))

        count = 0
        unmatched = 0
        unmatched_samples: list[str] = []
        for c in comments:
            # 空内容守卫（所有 provider 的入库咽喉）：去空白后为空的评论丢弃
            # ——xhs 置顶 null 槽位已在 collector 跳过，此处兜底空串/纯空白
            # （ABSA 拿空文本只会产出垃圾行）。不计 unmatched（非匹配失败）。
            if not str(c.get("content") or "").strip():
                continue
            post_url = c.get("post_url", "")
            note_id = c.get("post_note_id", "")
            post_id = url_to_post_id.get(post_url) or url_to_post_id.get(note_id)
            if not post_id:
                unmatched += 1
                if len(unmatched_samples) < 3:
                    unmatched_samples.append(post_url or note_id or "(empty)")
                continue

            # comment_cid：collector 统一透传键；快手历史遗留 comment_id 兜底
            cid = str(c.get("comment_cid") or c.get("comment_id") or "")
            if cid and cid in existing_cids:
                continue
            fp = (post_id, c.get("author", ""), (c.get("content") or "")[:200])
            if fp in existing_fp:
                continue

            published_at = None
            raw_date = c.get("published_at", "")
            if raw_date:
                try:
                    published_at = datetime.fromisoformat(raw_date)
                except (ValueError, TypeError):
                    pass

            self._session.add(PostComment(
                id=str(uuid.uuid4()),
                post_id=post_id,
                vehicle_id=vehicle_id,
                cid=cid or None,
                content=c.get("content", ""),
                author=c.get("author", ""),
                likes=c.get("likes", 0),
                platform=c.get("platform", ""),
                published_at=published_at,
            ))
            existing_cids.add(cid)
            existing_fp.add(fp)
            count += 1

        if count:
            await self._session.commit()
        if unmatched:
            # 归因说明（T2.4 排查结论）：post_url/post_note_id 键契约本身正确
            # （库内 0 孤儿行实证），unmatched 全部来自"评论先抓、帖后被品牌
            # 过滤/时间窗 floor/跨批次去重丢弃"——不是 id 错配。样本 URL 供
            # 实采对账定位具体丢弃路径。
            logger.warning(
                "Comment matching: %d/%d unmatched for %s"
                "（帖被品牌过滤/时间窗/去重丢弃，评论随之丢弃；样本 post_url=%s）",
                unmatched, len(comments), vehicle_id, unmatched_samples)
        return count

    async def _update_status(self, vehicle_id: str, mode: str, posts_count: int, error: str | None = None):
        result = await self._session.execute(
            select(CollectionStatus).where(
                CollectionStatus.vehicle_id == vehicle_id, CollectionStatus.source == "all"
            )
        )
        existing = result.scalars().first()
        now = datetime.now()
        if existing:
            existing.mode = mode
            if not error:
                existing.last_collected_at = now
            existing.posts_collected = posts_count
            existing.status = "completed" if not error else "error"
            existing.error_message = error
        else:
            self._session.add(CollectionStatus(
                id=str(uuid.uuid4()),
                vehicle_id=vehicle_id,
                source="all",
                mode=mode,
                last_collected_at=now,
                posts_collected=posts_count,
                status="completed" if not error else "error",
                error_message=error,
            ))
        await self._session.commit()

    # ── Date range helpers ──────────────────────────────────────────────

    def _get_date_ranges(self, mode: str, last_collected: datetime | None) -> list[tuple[str, str]]:
        today = date.today()
        if mode == "initial":
            # R40（2026-10-15）：initial 窗 90→30（env INITIAL_WINDOW_DAYS），
            # 与 POST_RETENTION_DAYS=30 保留线对齐。
            start = (today - timedelta(days=_INITIAL_WINDOW_DAYS)).strftime("%Y-%m-%d")
            return [(start, today.strftime("%Y-%m-%d"))]
        buffered = last_collected - timedelta(days=2) if last_collected else today
        start = buffered.strftime("%Y-%m-%d")
        return [(start, today.strftime("%Y-%m-%d"))]

    async def _determine_mode(self, vehicle_id: str) -> tuple[str, datetime | None]:
        result = await self._session.execute(
            select(CollectionStatus).where(CollectionStatus.vehicle_id == vehicle_id)
        )
        existing = result.scalars().first()
        if existing and existing.last_collected_at:
            return "incremental", existing.last_collected_at
        return "initial", None

    # ── Main entry point ────────────────────────────────────────────────

    async def collect_vehicle(self, vehicle_id: str) -> dict:
        vehicle = await self._session.get(Vehicle, vehicle_id)
        if not vehicle:
            return {"vehicle_id": vehicle_id, "status": "error", "posts_collected": 0, "error": "Vehicle not found"}

        # Init progress tracking
        progress = PipelineProgress()
        progress.init_platforms()
        pipeline_progress[vehicle_id] = progress
        # Legacy compat
        from api.pipeline_state import pipeline_phases
        # _updated_at 必带（审计 P1-1）：采集是最长阶段，无时间戳则 30min stale
        # 逃逸失效（_is_phase_stale 对无时间戳恒 False），zombie 残留会锁死触发
        pipeline_phases[vehicle_id] = {"phase": "collecting", "posts_collected": 0, "analyzed": 0, "error": None, "_updated_at": datetime.now()}

        vehicle_name = vehicle.name
        progress.overall_phase = "collecting"

        try:
            mode, last_collected = await self._determine_mode(vehicle_id)
            date_ranges = self._get_date_ranges(mode, last_collected)
            # Use the first (broadest) date range
            start_date, end_date = date_ranges[0]
            logger.info("开始采集 vehicle=%s mode=%s range=%s~%s", vehicle_name, mode, start_date, end_date)

            # Get all keywords
            base_keywords = await self._expand_keywords_if_needed(vehicle)
            # 缺陷扩词（T1.1）：车名+故障词组合。只搜车名只采到评测/提车帖，
            # "风云T7 仪表盘"类故障帖搜不到——拼成"车名 故障词"后搜索可命中。
            # 缺陷词紧贴核心词之后（_build_collection_keywords），社媒 max_keywords
            # 截断时仍在选区；news 全扫。
            all_keywords = self._build_collection_keywords(
                base_keywords, vehicle.name, vehicle.brand)
            defect_count = len(all_keywords) - len(base_keywords)
            logger.info("Keywords for %s: %s (含 %d 缺陷扩词)",
                        vehicle_name, all_keywords, defect_count)

            all_posts: list[dict] = []
            all_comments: list[dict] = []

            # F-13：删 _import_historical 死代码（initial 90 天窗口已覆盖历史）

            # ── Step 1: News ── 2026-10-15 R31 停采：阶段块整条摘除
            # （anspire/bocha 下线；_collect_news 方法体保留归档，见其 docstring）

            # ── Step 1b: 车质网投诉帖（A5） ──────────────────────────
            # 质量投诉主阵地，按车系 seriesId 直采 BBS。无 seriesId 映射的车型
            # 静默跳过（collector 内已处理）。投诉帖进缺陷监控评论池。
            progress.current_step = "车质网投诉采集"
            cz_pp = progress.platforms["chezhiwang"]
            cz_pp.phase = "collecting"
            cz_posts = await self._collect_chezhiwang(
                vehicle_id, vehicle_name, start_date, end_date, cz_pp)
            all_posts.extend(cz_posts)
            cz_pp.phase = "done"
            logger.info("车质网 phase done: %d posts", len(cz_posts))

            # ── Step 2: Social platforms (provider-routed, sequential) ─
            # provider 路由（2026-09-27 OneAPI 退役）：四平台全量 TikHub；
            # TikHub 未配置 key 该平台 skip + env_warning 可见化（防伪
            # completed）。可用性预检 = 本地 key 配置检查（无免费探活端点，
            # 每次调用都计费，不做 HTTP 探活）。
            social_platforms = list(SOCIAL_PLATFORMS)
            # 时间窗语义（2026-09-12 澄清）：有效窗口由 start_date 决定——
            # initial=90 天（_get_date_ranges），增量=上次采集-2天缓冲→今天。
            # dy=180/xhs=半年 只是服务端过滤档位（两平台无 90 天档，180 是
            # 能覆盖 90 的最小档），出窗老帖由 _store_posts 的 min_date floor 丢弃。
            window_days = max(1, (date.today() - date.fromisoformat(start_date)).days + 1)
            skipped_social: list[str] = []
            for platform in social_platforms:
                pp = progress.platforms[platform]
                # 抖音搜索路由 douyin_search key，其余用平台本名
                collector, provider = await self._resolve_collector(
                    "douyin_search" if platform == "douyin" else platform)
                if collector is None:
                    pp.phase = "skipped"
                    skipped_social.append(platform)
                    continue
                pp.phase = "collecting"
                progress.current_step = f"{platform_label(platform)}采集"
                strategy = get_strategy(platform)

                try:
                    posts, comments = await self._collect_social_platform(
                        vehicle_id, platform, all_keywords, pp,
                        mode=mode,
                        window_days=window_days,
                        collector=collector,
                        provider=provider,
                    )
                    all_posts.extend(posts)
                    all_comments.extend(comments)
                    # audit Phase 1 T1.3：全词失败标 error 而非 done（伪完成）
                    selected_kw_count = len(self._select_keywords(
                        all_keywords, get_strategy(platform).max_keywords))
                    if pp.fetch_failures and len(pp.fetch_failures) >= selected_kw_count:
                        pp.phase = "error"
                        pp.error = f"全部 {selected_kw_count} 个关键词采集失败"
                    else:
                        pp.phase = "done"
                except TikHubBudgetExceeded:
                    # 预算触顶不是平台错误（重试/记录 fetch_failures 都无意义）：
                    # 冒泡到 collect_vehicle 顶层统一标 budget_capped + 登记未采车
                    raise
                except Exception as e:
                    pp.phase = "error"
                    pp.error = str(e)
                    if isinstance(e, TikHubAuthError):
                        # 账户级错误（401/403/余额）：所有走该 provider 的平台
                        # 都会同样挂，接进 env_warning 可见化
                        progress.env_warning = f"采集 provider 账户/配置错误（{provider}）：{e}"
                        # 402 余额耗尽首现告警（E4）：区别于 401/403 的成本事件
                        _alert_402(vehicle_id, provider, e)
                    logger.warning("collect %s (%s) failed: %s", platform, provider, e)

                if strategy.inter_request_delay > 0:
                    await asyncio.sleep(strategy.inter_request_delay)

            if skipped_social and not progress.env_warning:
                progress.env_warning = (
                    f"{len(skipped_social)} 个社媒平台采集 provider 未配置"
                    f"（{'/'.join(skipped_social)}，需 TIKHUB_KEY，项目根 .env），"
                    "已跳过（车质网仍正常采集）。配置后重采即可。"
                )
                logger.warning("%d social platforms skipped (no provider configured)",
                               len(skipped_social))

            # 失败计数汇总到 pipeline_phases（A7）：per-platform fetch_failures 已
            # 经通过 /progress 端点暴露给前端 collectionProgress 面板，这里再聚
            # 合一份到 pipeline_phases 供 /pipeline-status 查询（顶层视图）。
            all_failures = []
            for pp in progress.platforms.values():
                all_failures.extend(pp.fetch_failures)
            if all_failures:
                pipeline_phases[vehicle_id]["fetch_failures"] = all_failures

            # ── Step 3: Full-text + dedup ───────────────────────────────
            progress.overall_phase = "enriching"
            progress.current_step = "全文抓取与去重"

            # 微博长文替换（缺口#5）：搜索响应只是 HTML 预览，全文需另抓。TikHub
            # 在 _search_weibo 搜索内已做 enrich_weibo_details（web_v2 详情端点
            # 三合一：长文全文 + 真互动数 + 带年份时间，top-N 帖），此处无需再富化
            all_posts = await self._crawl_full_texts(all_posts)
            all_posts = await self._resolve_urls(all_posts)
            pre_dedup_posts = list(all_posts)
            all_posts = self._run_dedup(all_posts)
            # 评论随帖搬迁（T2.4）：评论在 collector 搜索内先抓、帖随后才被
            # 当批次去重丢弃——被丢弃帖的评论改挂到其保留孪生帖
            all_comments = self._remap_comments_to_kept_posts(
                pre_dedup_posts, all_posts, all_comments)
            # 跨批次近似去重（B2）：当批次去重只挡同次采集内近似帖，跨天微改稿/
            # 多账号转发稿穿透——对近30天库内同前缀帖 simhash 比对拦截
            all_posts = await self._cross_batch_dedup(all_posts, vehicle_id)

            stored_by_platform = await self._store_posts(vehicle_id, all_posts, min_date=start_date,
                                             vehicle_name=vehicle.name, vehicle_brand=vehicle.brand,
                                             aliases=get_vehicle_aliases(vehicle.name))
            stored = sum(stored_by_platform.values())
            progress.posts_collected = stored
            comment_count = await self._store_comments(vehicle_id, all_comments)

            # Update per-platform stored counts（真实 per-platform 计数，不再是 total 占位）
            for name, pp in progress.platforms.items():
                pp.posts_stored = stored_by_platform.get(name, 0)

            # 采集多平台搜索指数（抖音+小红书，替代已死的 gopup 百度指数）。
            # 核心词两源同词 → /trend 合成指数可比；失败只 warning 不炸采集
            # （指数是看板增强项，帖子/评论才是主链路）。微博/快手无关键词级
            # 指数源，暂不采（2026-09-11 评估结论）。
            core_kw = self._get_core_keyword(vehicle)
            search_points: list[dict] = []
            if core_kw and await self._index.is_available():
                # dy 指数固定拉 30 天滚动窗，与采集窗解耦：增量窗仅 ~1 天
                # 会把曲线截成几个点（M03 实采实证 4 点）；指数按次计费
                # $0.003 不因范围变贵，且 _store_search_index 幂等覆盖无残留
                idx_end = date.today().isoformat()
                idx_start = (date.today() - timedelta(days=29)).isoformat()
                # audit Phase 1 T1.3：拆 try，douyin 失败不连带 xhs
                try:
                    search_points = await self._index.collect_douyin(
                        core_kw, idx_start, idx_end)
                except Exception as e:
                    logger.warning("抖音指数采集失败（不影响 xhs 指数）: %s", e)
                try:
                    search_points += await self._index.collect_xiaohongshu(core_kw)
                except Exception as e:
                    logger.warning("小红书指数采集失败（不影响帖子链路）: %s", e)
                if search_points:
                    logger.info("搜索指数: %d points for '%s' (douyin+xhs)",
                                len(search_points), core_kw)
            else:
                logger.info("搜索指数跳过：TIKHUB_KEY 未配置或无核心词")
            await self._store_search_index(vehicle_id, search_points)
            await self._update_status(vehicle_id, mode, stored)

            progress.overall_phase = "completed"
            # P2-7：瞬态 completed dict 也带 fetch_failures（采集阶段结束即查得到）
            done = {"phase": "completed", "posts_collected": stored, "analyzed": 0, "error": None, "_updated_at": datetime.now()}
            if all_failures:
                done["fetch_failures"] = all_failures
            pipeline_phases[vehicle_id] = done

            logger.info("采集完成: %d posts + %d comments stored for %s",
                        stored, comment_count, vehicle_name)
            return {
                "vehicle_id": vehicle_id, "mode": mode,
                "posts_collected": stored,
                "comments_collected": comment_count,
                "status": "completed",
            }

        except TikHubBudgetExceeded as e:
            # T2/L6：日预算护栏命中——区别于采集错误（不进 error 状态），
            # 标 budget_capped + 登记当日未采车（as_of 不掩盖部分陈旧，红线#1）
            progress.overall_phase = "error"
            progress.error = f"日预算护栏命中：{e}"
            pipeline_phases[vehicle_id] = {"phase": "budget_capped", "posts_collected": 0, "analyzed": 0, "error": str(e), "_updated_at": datetime.now()}
            await self._session.rollback()
            logger.warning("预算触顶 vehicle=%s: %s", vehicle_id, e)
            try:
                await register_budget_skip(self._session, vehicle_id, str(e))
            except Exception as reg_err:
                logger.warning("预算未采车登记失败（不影响触顶状态标记）: %s", reg_err)
            return {"vehicle_id": vehicle_id, "status": "budget_capped",
                    "posts_collected": 0, "error": str(e)}
        except Exception as e:
            progress.overall_phase = "error"
            progress.error = str(e)
            pipeline_phases[vehicle_id] = {"phase": "error", "posts_collected": 0, "analyzed": 0, "error": str(e), "_updated_at": datetime.now()}
            await self._session.rollback()
            logger.warning("采集失败 vehicle=%s: %s", vehicle_id, e)
            try:
                await self._update_status(vehicle_id, "unknown", 0, str(e))
            except Exception:
                pass
            return {"vehicle_id": vehicle_id, "status": "error", "posts_collected": 0, "error": str(e)}

    # ── On-demand comment fetching ──────────────────────────────────────

    async def fetch_top_comments(self, vehicle_id: str) -> int:
        """Fetch comments for top-N posts per platform via the routed provider.

        评论路由：douyin→douyin_comments（默认 TikHub），其余→平台本名；
        每平台独立 resolve，provider 未配置跳过该帖（不再全局一刀切）。
        每平台上限 N = batch_runner.comment_top_n（env COMMENT_TOP_N，默认 10
        ——2026-10-15 舆情降本 R41：top10×2 页；停采平台 comment_top_n=0 全跳过）。
        缺陷词帖（select_top_posts_for_comments 标记 _defect_directed）不受
        每平台上限约束——定向全量补评论（故障帖评论是缺陷监控数据源）。
        """
        from pipeline.analysis.batch_runner import (
            comment_top_n,
            select_top_posts_for_comments,
        )

        top_posts = await select_top_posts_for_comments(self._session, vehicle_id)
        if not top_posts:
            return 0

        platform_counts: dict[str, int] = {}
        total = 0

        for post in top_posts:
            plat = post.platform or ""
            plat_full = normalize_platform(plat) or ""
            # 旧 CDP 快手帖 URL 是 search 页（无真实 photo_id），评论接口无从调用；
            # 只对 /short-video/{photo_id} 永久链抓评论。
            if plat_full == "kuaishou" and "/short-video/" not in (post.url or ""):
                continue

            if platform_counts.get(plat_full, 0) >= comment_top_n(plat_full):
                # 缺陷词帖定向全量（T1.2）+ 负面帖追加（T2/L1）：均不受每平台
                # top-N 上限约束——负面追加在选帖侧已有独立 N 上限（R41 预算）。
                # getattr 哨兵兼容 SimpleNamespace 测试桩（无此属性→False→照常 cap）。
                if not (getattr(post, "_defect_directed", False)
                        or getattr(post, "_negative_directed", False)):
                    continue

            # 抖音评论路由 douyin_comments（默认 TikHub），其余用平台本名
            collector, provider = await self._resolve_collector(
                "douyin_comments" if plat_full == "douyin" else plat_full)
            if collector is None:
                logger.warning("%s 评论补抓 provider 未配置，跳过 %s", plat_full, post.url)
                continue

            try:
                comments = await collector.fetch_comments_for_post(post.url, plat_full)
            except TikHubAuthError as e:
                logger.warning("采集账户错误（%s），评论补抓中止: %s", provider, e)
                _alert_402(vehicle_id, provider, e)
                break
            except Exception as e:
                logger.debug("评论补抓失败 %s: %s", post.url, e)
                continue

            if comments:
                await self._store_comments(vehicle_id, comments)
                platform_counts[plat_full] = platform_counts.get(plat_full, 0) + 1
                total += len(comments)

        return total

    # ── Douyin batch play stats (provider-routed) ───────────────────────

    async def _fetch_douyin_play_stats(self, aweme_ids: list[str]) -> dict[str, dict]:
        """抖音批量播放统计——TikHub fetch_multi_video_statistics（$0.025/批）。

        返回 shape {aweme_id: 原始统计 dict}；provider 未配置 log warning
        返回 {}（调用方按空结果容错，不炸流程）。
        """
        if not aweme_ids:
            return {}
        collector, _provider = await self._resolve_collector("douyin_stats")
        if collector is None:
            logger.warning("douyin 批量统计 provider 未配置，跳过（%d 个 aweme_id）",
                           len(aweme_ids))
            return {}
        return await collector._client.fetch_douyin_play_stats(aweme_ids)
