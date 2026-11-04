"""Two-stage relevance filter: rule engine (fast, free) → LLM (semantic, cheap).

Filters irrelevant posts (wrong-topic, wrong-time, wrong-domain) from
collected data before analysis and dashboard display.

Stage 1 — Rule engine: time window, URL blacklist, keyword exclude, car context
Stage 2 — LLM checker: semantic relevance for gray-zone posts
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum

import httpx
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from models.schemas import RawPost, Vehicle

logger = logging.getLogger(__name__)

# ── 已知车别名表（单一真相源：采集层 AND 门与语义层共用，v3 C-1）────────────

_KNOWN_ALIASES: dict[str, list[str]] = {
    "比亚迪海豚": ["海豚EV", "Dolphin", "BYD Dolphin"],
    "元PLUS":    ["元PLUS EV", "Yuan Plus", "BYD Yuan Plus"],
    "银河E5":    ["吉利银河E5", "Galaxy E5"],
    "特斯拉model 3": ["Model 3", "model 3", "model3", "Model3", "Tesla Model 3"],
    "海狮06":    ["海狮06", "海狮06EV", "海狮06ev", "海狮06DMI", "BYD Sea Lion 06", "Seal 06"],
    "Model Y":   ["Model Y", "ModelY", "Model YL", "ModelYL", "Tesla Model Y"],
    "小鹏MONA M03": ["MONA M03", "MONAM03", "M03", "小鹏MONA"],
    # 奇瑞风云系列（2026-10-06 加：同品牌不同车型混入根治）
    "风云A9":    ["风云A9", "奇瑞风云A9"],
    "风云A9L":   ["风云A9L", "风云A9l", "奇瑞风云A9L"],
    "风云T9":    ["风云T9", "奇瑞风云T9"],
    "风云T9L":   ["风云T9L", "风云T9l", "奇瑞风云T9L"],
    "风云T11":   ["风云T11", "奇瑞风云T11"],
    "风云T7":    ["风云T7", "奇瑞风云T7"],
    # QQ3（奇瑞）
    "QQ3":       ["QQ3", "奇瑞QQ3", "Chery QQ3", "QQ3ev"],
}


def get_vehicle_aliases(name: str) -> list[str]:
    """已知车的别名（未收录车返回空表——采集 AND 门只有车名组，语义层不受影响）。"""
    return list(_KNOWN_ALIASES.get(name, []))


# ── Enums ──────────────────────────────────────────────────────────────────

class Relevance(str, Enum):
    PASS = "pass"          # Rule engine: clearly relevant
    LIMBO = "limbo"        # Rule engine: unclear → needs LLM
    REJECT = "reject"      # Rule engine: clearly irrelevant


# ── Vehicle Profile ────────────────────────────────────────────────────────

@dataclass
class VehicleProfile:
    """Essential info for relevance checking."""
    name: str
    brand: str
    launch_date: str          # ISO date, e.g. "2021-08-01"
    vehicle_type: str = ""    # e.g. "纯电两厢车"
    aliases: list[str] = field(default_factory=list)
    # v3（2026-10-08）：同品牌易混车型（动态生成注入 LLM prompt，替代静态三家示例）
    confusables: list[str] = field(default_factory=list)

    @property
    def launch_date_obj(self) -> date:
        return date.fromisoformat(self.launch_date)

    @classmethod
    def from_vehicle(cls, vehicle: Vehicle) -> "VehicleProfile":
        """Build profile from Vehicle ORM object with smart defaults."""
        name = vehicle.name
        brand = vehicle.brand
        # Known vehicle metadata（v3：别名走共享表 _KNOWN_ALIASES，采集层 AND 门共用）
        _KNOWN_META = {
            "比亚迪海豚": ("2021-08-01", "纯电两厢车"),
            "元PLUS":    ("2022-02-01", "纯电SUV"),
            "银河E5":    ("2024-08-01", "纯电SUV"),
            "特斯拉model 3": ("2019-06-01", "纯电轿车"),
            "海狮06":    ("2024-09-01", "纯电SUV"),
            "Model Y":   ("2020-01-01", "纯电SUV"),
            "小鹏MONA M03": ("2024-08-01", "纯电轿车"),
            # 奇瑞风云系列（2026-10-06 加：同品牌不同车型混入根治）
            "风云A9":    ("2024-11-01", "插混轿车"),
            "风云A9L":   ("2025-06-01", "插混轿车"),
            "风云T9":    ("2024-05-01", "插混SUV"),
            "风云T9L":   ("2025-03-01", "插混SUV"),
            "风云T11":   ("2024-12-01", "插混SUV"),
            "风云T7":    ("2024-08-01", "插混SUV"),
            # QQ3（奇瑞）
            "QQ3":       ("2024-06-01", "纯电两厢车"),
        }
        if name in _KNOWN_META:
            ld, vt = _KNOWN_META[name]
            return cls(name=name, brand=brand, launch_date=ld, vehicle_type=vt,
                       aliases=get_vehicle_aliases(name))
        # Fallback: guess launch_date from earliest post (will be refined)
        return cls(name=name, brand=brand, launch_date="2020-01-01",
                   vehicle_type="汽车", aliases=[name])


# ── Rule Engine ────────────────────────────────────────────────────────────

# URL patterns that indicate non-editorial pages
_URL_BLACKLIST = [
    r"/config\b", r"/picture\b", r"/image\b",
    r"/壁纸", r"/图片", r"/配置", r"/参数",
    r"/wallpaper", r"/gallery",
]

# Content patterns that indicate off-topic
_EXCLUDE_PATTERNS = [
    r"模拟器", r"[Dd]olphin\s*(模拟|[Ss]im)",     # Game emulator
    r"海豚.{0,6}(动物|海洋|水族|表演|馆)",          # Animal dolphin
    r"海豚.{0,6}(跳|救|杀|吃|捕)",                  # Animal dolphin actions
    r"海豚.{0,4}\.(ppt|pdf|doc|pptx)",               # Document files
    r"(下载|安装|破解).{0,10}海豚",                   # Downloads about dolphin
]

_EXCLUDE_RE = re.compile("|".join(_EXCLUDE_PATTERNS), re.IGNORECASE)
_URL_RE = re.compile("|".join(_URL_BLACKLIST), re.IGNORECASE)

# Keywords that indicate automotive context
_CAR_CONTEXT = {
    "车", "汽车", "续航", "充电", "电池", "驾驶", "提车", "新能源",
    "EV", "电动", "油耗", "保养", "4S", "OTA", "智能", "座舱", "智驾",
    "BYD", "比亚迪", "吉利", "吉利银河", "价位", "落地", "试驾",
    "订车", "交车", "提车", "油耗", "能耗", "续航", "续航里程",
    "刀片电池", "三元锂", "磷酸铁锂", "快充", "慢充",
    "辅助驾驶", "自动驾驶", "HUD", "车机", "中控", "底盘", "悬挂",
    "减震", "刹车", "轮胎", "轮毂", "天窗", "后备箱",
}

# Compile car context regex for faster matching
_CAR_CONTEXT_RE = re.compile(
    "|".join(re.escape(k) for k in _CAR_CONTEXT),
    re.IGNORECASE,
)


def _has_self_name(text: str, profile: VehicleProfile) -> bool:
    """Whether text mentions THIS vehicle's name/alias.

    Handles brand-prefix: profile.name like "比亚迪海豚" should match a post
    titled "海豚测评" (brand stripped to "海豚"). Without this, same-brand
    different-model posts (e.g. "海狮07EV" under "海狮06EV" profile) leak
    through Rule 4 solely on car-context keywords.

    v3 边界（2026-10-08 审计）：候选词含 ASCII 字母/数字时带前后非字母数字
    边界匹配——"风云T9" 不再子串命中 "风云T9L"（后缀变体是不同车型），
    "A9" 不再命中 "A9L"。纯中文候选维持子串。
    """
    candidates: list[str] = []
    if profile.name:
        candidates.append(profile.name)
        # Strip brand prefix so short model names still match
        if profile.brand and profile.name.startswith(profile.brand):
            short = profile.name[len(profile.brand):].strip()
            if short:
                candidates.append(short)
    candidates.extend(a for a in profile.aliases if a)
    text_lower = text.lower()
    for c in candidates:
        if any(ch.isascii() and ch.isalnum() for ch in c):
            m = re.search(rf'(?<![a-z0-9]){re.escape(c.lower())}(?![a-z0-9])', text_lower)
            if m:
                return True
        elif c.lower() in text_lower:
            return True
    return False


class RuleBasedFilter:
    """Stage 1: Fast, free rule-based relevance check."""

    def check(self, post: dict, profile: VehicleProfile) -> Relevance:
        """Check a single post against rules.

        Args:
            post: dict with 'title', 'content', 'url', 'published_at', 'platform'
            profile: vehicle metadata

        Returns:
            Relevance.PASS, .LIMBO, or .REJECT
        """
        title = post.get("title", "") or ""
        content = post.get("content", "") or ""
        url = post.get("url", "") or ""
        text = f"{title} {content}"

        # Rule 1: Published before vehicle launch → REJECT
        pub = post.get("published_at")
        if pub is not None:
            pub_date = pub.date() if isinstance(pub, datetime) else pub
            if isinstance(pub_date, date) and pub_date < profile.launch_date_obj:
                return Relevance.REJECT

        # Rule 2: URL matches blacklist → REJECT
        if url and _URL_RE.search(url):
            return Relevance.REJECT

        # Rule 3: Content matches exclude patterns → REJECT
        if _EXCLUDE_RE.search(text):
            return Relevance.REJECT

        # Rule 4: 含本车名/别名 + 汽车语境词 → PASS（对比帖含本车名+其他车名也保留）
        # 不含本车名不直接 PASS，进 LLM 判断（防同品牌不同车型混入）
        if _CAR_CONTEXT_RE.search(text) and _has_self_name(text, profile):
            return Relevance.PASS

        # Rule 5: Platform-specific rules
        platform = post.get("platform", "") or post.get("source", "")
        if platform == "news":
            # News articles are more likely relevant if they mention the brand or name
            combined = f"{title} {content}"
            if profile.brand in combined or profile.name in combined:
                return Relevance.PASS
            for alias in profile.aliases:
                if alias in combined:
                    return Relevance.PASS
            # News without brand/name mention → LIMBO
            return Relevance.LIMBO

        # Nothing matched → LIMBO (needs LLM check)
        return Relevance.LIMBO


# ── LLM Relevance Checker ─────────────────────────────────────────────────

_RELEVANCE_PROMPT = """判断以下帖子是否与"{vehicle_name}"({brand}品牌{vehicle_type})相关。

相关：讨论该车型的性能、质量、购买、使用、售后、市场表现、竞品对比等
不相关：讨论其他同名事物、纯广告、配置参数页、图片集、无关短视频等

⚠ 撞名车特别校验（重要）：
车名若为通用词（如"星愿/银河/风云/元"等），帖文仅含车名字面是不够的——
必须检查是否有汽车语境词（提车/续航/充电/4S/经销商/试驾/油耗/保养/配置/
续航里程/购车/车主/落地价等）。无任何汽车语境词、却在讨论游戏/偶像/节目/
宝盒/超话/生日企划/大熊猫等的，判不相关。

撞名误判示例（这些含"星愿"但与车无关，应判 false）：
- "星宝！星愿节闪耀开启！趣味星图、免费礼物" → 游戏/活动，无汽车语境
- "idolish7超话 #偶像星愿# 【贺图】" → 偶像团体，无汽车语境
- "星愿宝盒 金纱礼宴动作套装预览" → 游戏道具，无汽车语境
- "为肖战守护星愿 十载风雨淬炼" → 粉丝生日企划，无汽车语境

⚠ 同品牌不同车型校验（重要）：
本车是"{vehicle_name}"({brand}品牌)。如果帖子单独讨论下列同品牌其他车型
而不涉及"{vehicle_name}"本身，判不相关。但竞品对比帖（同时提及本车与
其他车型）判相关。
{confusables}
判别规则：名称仅多字母数字后缀的是不同车型（如 T9L≠T9、A9L≠A9）；
配置版本（如"{vehicle_name}"的"星舰版/尽情版/冠军版"等 trim）仍算本车，
不要把配置版本误判为其他车型。

标题：{title}
内容摘要：{content}

只回复 JSON：{{"relevant": true/false, "confidence": 0.0-1.0}}"""


def _format_confusables(confusables: list[str], name: str, brand: str,
                        self_aliases: list[str] | None = None) -> str:
    """动态易混车型清单 → prompt 注入段（v3：替代静态三家硬编码示例）。

    self_aliases：本车自身写法变体（EV/DMI 等版本后缀）仍算本车（review I-3）。
    空清单给一行占位（prompt 结构稳定），有清单给逐行 "- 车型名"。
    """
    lines = []
    if confusables:
        lines += [f"- {c}（≠{name}）" for c in confusables[:15]]
    else:
        lines.append(f"- （{brand}品牌暂无其他在库车型，无需同品牌排除）")
    if self_aliases:
        shown = [a for a in self_aliases if a and a != name][:8]
        if shown:
            lines.append(f"⚠ 以下是「{name}」自身的写法变体（EV/DMI/Pro 等版本），"
                         f"仍算本车相关，不要判不相关：{('、'.join(shown))}")
    return "\n".join(lines)


class LLMRelevanceChecker:
    """Stage 2: LLM-based semantic relevance check for limbo posts."""

    def __init__(self, api_key: str, api_url: str, model: str = "glm-4-flash"):
        self._api_key = api_key
        self._api_url = api_url
        self._model = model

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def _call_api(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                self._api_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def check(self, post: dict, profile: VehicleProfile) -> tuple[bool, float]:
        """Check a single post for relevance. Returns (is_relevant, confidence)."""
        title = post.get("title", "") or ""
        content = (post.get("content", "") or "")[:200]
        prompt = _RELEVANCE_PROMPT.format(
            vehicle_name=profile.name,
            brand=profile.brand,
            vehicle_type=profile.vehicle_type or "汽车",
            confusables=_format_confusables(profile.confusables, profile.name, profile.brand,
                                            self_aliases=profile.aliases),
            title=title[:100],
            content=content,
        )
        try:
            raw = await self._call_api(prompt)
            # Parse JSON from response
            data = self._parse_json(raw)
            if data is not None:
                return bool(data.get("relevant", False)), float(data.get("confidence", 0.5))
            return False, 0.3
        except Exception as e:
            logger.warning("LLM relevance check failed: %s", e)
            return False, 0.0

    async def check_batch(
        self, posts: list[dict], profile: VehicleProfile,
    ) -> list[tuple[bool, float]]:
        """Check multiple posts concurrently. Returns list of (is_relevant, confidence).

        Order is preserved (matches input order) since gather respects argument order.
        """
        import asyncio
        sem = asyncio.Semaphore(8)  # 并发上限，避免 API 限速

        async def _one(post):
            async with sem:
                return await self.check(post, profile)

        return list(await asyncio.gather(*[_one(p) for p in posts]))

    @staticmethod
    def _parse_json(raw: str) -> dict | None:
        """Extract JSON object from LLM response."""
        # Try direct parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Try extracting from code block
        import re
        m = re.search(r'\{[^{}]*"relevant"[^{}]*\}', raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        return None

    @classmethod
    def from_config(cls) -> "LLMRelevanceChecker | None":
        """Create checker from config. Returns None if no API key available."""
        from utils.config import load_api_config
        config = load_api_config()
        glm_cfg = config.get("glm", {})
        if glm_cfg.get("api_key"):
            return cls(
                api_key=glm_cfg["api_key"],
                api_url=glm_cfg.get("base_url", "https://open.bigmodel.cn/api/paas/v4") + "/chat/completions",
                model=glm_cfg.get("model", "glm-4-flash"),
            )
        return None


# ── Orchestrator ───────────────────────────────────────────────────────────

class RelevanceFilter:
    """Two-stage relevance filter: rule engine → LLM."""

    def __init__(self, llm_checker: LLMRelevanceChecker | None = None):
        self._rule_filter = RuleBasedFilter()
        self._llm = llm_checker

    def filter_posts(self, posts: list[dict], profile: VehicleProfile) -> list[dict]:
        """Run rule engine on posts. Returns posts with relevance_score set.

        - PASS posts: relevance_score = 1.0
        - REJECT posts: relevance_score = 0.0, analysis_status = "irrelevant"
        - LIMBO posts: relevance_score = None (needs LLM check later)

        All posts are returned; callers can filter by relevance_score.
        """
        for post in posts:
            result = self._rule_filter.check(post, profile)
            if result == Relevance.PASS:
                post["relevance_score"] = 1.0
            elif result == Relevance.REJECT:
                post["relevance_score"] = 0.0
                post["analysis_status"] = "irrelevant"
            else:
                post["relevance_score"] = None  # LIMBO
        return posts

    async def filter_limbo_posts(
        self, posts: list[dict], profile: VehicleProfile,
    ) -> list[dict]:
        """Run LLM check on LIMBO posts (those with relevance_score is None).

        Updates relevance_score and sets analysis_status for rejected posts.
        """
        if not self._llm:
            logger.warning("No LLM checker available; keeping %d limbo posts", len(posts))
            for p in posts:
                if p.get("relevance_score") is None:
                    p["relevance_score"] = 0.5  # default: keep
            return posts

        limbo = [p for p in posts if p.get("relevance_score") is None]
        if not limbo:
            return posts

        logger.info("LLM relevance check: %d limbo posts", len(limbo))
        results = await self._llm.check_batch(limbo, profile)

        for post, (is_relevant, confidence) in zip(limbo, results):
            post["relevance_score"] = confidence if is_relevant else 0.0
            if not is_relevant:
                post["analysis_status"] = "irrelevant"

        return posts

    async def filter_vehicle(self, vehicle_id: str, session: AsyncSession) -> dict:
        """Full two-stage filter for a vehicle's pending posts.

        Returns stats: {"total": N, "passed": N, "limbo": N, "rejected_by_rules": N, "rejected_by_llm": N}
        """
        # Load vehicle
        vehicle = await session.get(Vehicle, vehicle_id)
        if not vehicle:
            return {"error": "Vehicle not found"}

        profile = VehicleProfile.from_vehicle(vehicle)
        # v3：同品牌易混车型动态清单（从 vehicles 表按品牌分组自动生成），
        # 替代静态三家示例——车队扩容后清单自动跟随，不再依赖人工维护
        if vehicle.brand:
            # M-1：active 优先 + ORDER BY name（确定性）
            rows = await session.execute(
                select(Vehicle.name).where(
                    Vehicle.brand == vehicle.brand,
                    Vehicle.id != vehicle_id,
                    Vehicle.status == "active",
                ).order_by(Vehicle.name)
            )
            profile.confusables = [r[0] for r in rows.all() if r[0]]

        # Load pending posts
        result = await session.execute(
            select(RawPost).where(
                RawPost.vehicle_id == vehicle_id,
                RawPost.analysis_status == "pending",
            )
        )
        posts = result.scalars().all()
        if not posts:
            return {"total": 0, "passed": 0, "rejected_by_rules": 0, "limbo": 0, "rejected_by_llm": 0}

        # Convert to dicts for processing
        post_dicts = []
        for p in posts:
            post_dicts.append({
                "id": p.id,
                "title": p.title or "",
                "content": (p.full_content or p.content or "")[:500],
                "url": p.url or "",
                "published_at": p.published_at,
                "platform": p.platform or "",
                "source": p.source or "",
            })

        # Stage 1: Rule engine
        post_dicts = self.filter_posts(post_dicts, profile)

        passed = sum(1 for p in post_dicts if p.get("relevance_score") == 1.0)
        rejected_by_rules = sum(1 for p in post_dicts if p.get("relevance_score") == 0.0)
        limbo_count = sum(1 for p in post_dicts if p.get("relevance_score") is None)

        # Stage 2: LLM check for limbo posts
        if limbo_count > 0:
            post_dicts = await self.filter_limbo_posts(post_dicts, profile)

        # Count LLM rejects: irrelevant posts that were NOT rule-rejected (score > 0)
        rejected_by_llm = sum(
            1 for p in post_dicts
            if p.get("analysis_status") == "irrelevant"
            and p.get("relevance_score") is not None
            and p["relevance_score"] > 0.0  # rule rejects are exactly 0.0
        )

        # Update DB — wrap in try/except to avoid partial commits
        try:
            id_to_result = {p["id"]: p for p in post_dicts}
            for post_orm in posts:
                pd = id_to_result.get(post_orm.id)
                if pd:
                    if pd.get("relevance_score") is not None:
                        post_orm.relevance_score = pd["relevance_score"]
                    if pd.get("analysis_status") == "irrelevant":
                        post_orm.analysis_status = "irrelevant"

            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error("Failed to update relevance scores: %s", e)
            return {"vehicle_id": vehicle_id, "total": len(posts), "error": str(e)}

        total_rejected = rejected_by_rules + rejected_by_llm
        logger.info(
            "Relevance filter for %s: %d total → %d passed, %d limbo→%d passed, "
            "%d rejected (rules=%d, llm=%d)",
            vehicle.name, len(posts),
            passed, limbo_count, limbo_count - rejected_by_llm,
            total_rejected, rejected_by_rules, rejected_by_llm,
        )

        return {
            "vehicle_id": vehicle_id,
            "total": len(posts),
            "passed": passed,
            "limbo_kept": limbo_count - rejected_by_llm,
            "rejected_by_rules": rejected_by_rules,
            "rejected_by_llm": rejected_by_llm,
        }
