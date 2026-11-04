"""Vehicle sentiment analysis pipeline — API-only combined analysis."""
import asyncio
import json
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from pipeline.analysis.local_absa import ALL_DIMENSIONS
from utils.config import load_api_config
from utils.llm_helpers import extract_json_object

# dim_sentiment 维度白名单——single source 来自 local_absa.ALL_DIMENSIONS（15 维度）
VALID_DIMENSIONS = frozenset(ALL_DIMENSIONS)

logger = logging.getLogger(__name__)

# ── Event Tag Pool (17 flat tags) ─────────────────────────────────────────

EVENT_TAG_POOL = [
    "质量问题", "异响/故障", "安全事故", "召回",
    "新车发布/上市", "降价/促销", "交付延迟", "提车分享",
    "续航争议", "充电问题", "智能驾驶事故", "OTA升级",
    "维权投诉", "售后服务", "4S店纠纷",
    "政策法规", "行业动态",
]

# ── Combined Analysis Prompt (API-only fallback) ──────────────────────────

COMBINED_ANALYSIS_PROMPT = """分析这条汽车相关帖文，完成以下判断：

1. event_tags: 从以下标签池中选最多 3 个最匹配的（可为空列表）：
   {event_tags}
   只能从上面的标签池中选择，不要自创标签。

2. opinion_tags: 提取文本中的用户观点，格式为"维度+评价"（如"续航长""价格贵""空间大""内饰差""售后慢"），每条观点必须包含感情倾向，自由提取3-5个

3. sentiment: positive / negative / neutral

4. dim_sentiment: 提取各维度评价，格式为 {{"维度名": 分数}}
   可选维度及分数（-1负面, 0中性, 1正面）：
   动力/加速, 续航里程, 电耗, 充电体验, 智能化/车机, 辅助驾驶/智驾,
   价格/性价比, 舒适性, 操控, 安全性, 内饰, 外观, 空间, 售后服务, 油耗
   文本中未涉及的维度不要输出。

5. subject: 这条帖主要讨论哪款车？
   - 若主要讨论 {vehicle_name}（{vehicle_brand}），回复 "self"
   - 若主要讨论另一款具体车型，回复 "competitor"
   - 若是行业泛谈/无具体车型，回复 "other"
   并在 subject_name 填主要讨论的车名（self 时填 {vehicle_name}，other 填空）。
   ⚠ 同品牌其他车型（≠{vehicle_name}）单独出现时必须判 competitor，不是 self：
{confusables}
   判别规则：名称仅多字母数字后缀的是不同车型（如 T9L≠T9、A9L≠A9）；
   配置版本（如"{vehicle_name}"的"星舰版/尽情版"等 trim）仍算 self。

帖子文本：
{text}

请严格以 JSON 格式回复：
{{"event_tags": ["标签1"], "opinion_tags": ["观点1"], "sentiment": "positive/negative/neutral", "dim_sentiment": {{"维度名": 分数}}, "subject": "self/competitor/other", "subject_name": "车名", "confidence": 0.0-1.0}}"""


# ── Event-only Prompt (dual model mode) ───────────────────────────────────

EVENT_ONLY_PROMPT = """分析这条汽车相关帖文，完成以下判断：

1. event_tags: 从以下标签池中选最多 3 个最匹配的（可为空列表）：
   {event_tags}
   只能从上面的标签池中选择，不要自创标签。

2. opinion_tags: 提取文本中的用户观点，格式为"维度+评价"（如"续航长""价格贵""空间大""内饰差""售后慢"），每条观点必须包含感情倾向，自由提取3-5个

3. subject: 这条帖主要讨论哪款车？
   - 若主要讨论 {vehicle_name}（{vehicle_brand}），回复 "self"
   - 若主要讨论另一款具体车型，回复 "competitor"
   - 若是行业泛谈/无具体车型，回复 "other"
   并在 subject_name 填主要讨论的车名（self 时填 {vehicle_name}，other 填空）。
   ⚠ 同品牌其他车型（≠{vehicle_name}）单独出现时必须判 competitor，不是 self：
{confusables}
   判别规则：名称仅多字母数字后缀的是不同车型（如 T9L≠T9、A9L≠A9）；
   配置版本（如"{vehicle_name}"的"星舰版/尽情版"等 trim）仍算 self。

帖子文本：
{text}

请严格以 JSON 格式回复：
{{"event_tags": ["标签1"], "opinion_tags": ["观点1"], "subject": "self/competitor/other", "subject_name": "车名", "confidence": 0.0-1.0}}"""

_API_CONCURRENCY = 16

# v3 I-3：本车自身写法变体（EV/DMI 等版本后缀）缓存——analyze_batch 级填充，
# analyze_single 复用（进程内按车名缓存，_KNOWN_ALIASES 静态不会变）
_self_alias_cache: dict[str, list[str]] = {}


def _format_confusables(confusables: list[str], vehicle_name: str,
                        self_aliases: list[str] | None = None) -> str:
    """动态易混车型清单 → prompt 注入段（v3：与 relevance_filter 同模式）。

    self_aliases：本车自身的写法变体（EV/DMI/Pro 等动力/配置后缀）——它们算
    本车不是后缀车型，注入防"海狮06EV 提车"被判 competitor（review I-3）。
    空清单给一行占位（prompt 结构稳定）。
    """
    lines = []
    if confusables:
        lines += [f"   - {c}（≠{vehicle_name}）" for c in confusables[:15]]
    else:
        lines.append("   （本品牌暂无其他在库车型，无需同品牌排除）")
    if self_aliases:
        shown = [a for a in self_aliases if a and a != vehicle_name][:8]
        if shown:
            lines.append(f"   ⚠ 以下是「{vehicle_name}」自身的写法变体（EV/DMI/Pro 等版本），"
                         f"仍算本车 self，不要判 competitor：{('、'.join(shown))}")
    return "\n".join(lines)


def _safe_confidence(raw_val) -> float:
    """Parse confidence from LLM response, handling None/null gracefully.

    data.get('confidence', 0.5) only uses the default when the key is MISSING,
    not when the value is None/null. float(None) would raise TypeError, which
    the outer try/except catches — but that discards the ENTIRE valid response
    (sentiment, event_tags, subject, etc.). This helper avoids that.

    Returns float in [0.0, 1.0].
    """
    if raw_val is None:
        return 0.5
    try:
        return max(0.0, min(1.0, float(raw_val)))
    except (ValueError, TypeError):
        return 0.5


# ── Analysis Pipeline ─────────────────────────────────────────────────────

class AnalysisPipeline:
    def __init__(self):
        # #27：复用 utils/llm_client._select_provider（单一真相源，消除重复拼接）
        from utils.llm_client import _select_provider
        self._api_key, self._api_url, self._model = _select_provider()
        self._use_anthropic_format = False

    # ── Unified API call ──────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _call_api(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
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

    # ── Event-only API call ───────────────────────────────────────────

    async def _analyze_event_api(self, text: str, vehicle_name: str = "", vehicle_brand: str = "",
                                 confusables: list[str] | None = None) -> dict:
        prompt = EVENT_ONLY_PROMPT.format(
            event_tags="、".join(EVENT_TAG_POOL),
            vehicle_name=vehicle_name or "本车型",
            vehicle_brand=vehicle_brand or "",
            confusables=_format_confusables(confusables or [], vehicle_name or "本车型",
                                            self_aliases=_self_alias_cache.get(vehicle_name or "")),
            text=text,
        )
        try:
            raw = await self._call_api(prompt)
            return self._parse_event_response(raw)
        except Exception as e:
            logger.warning("Event API failed: %s", e)
            return self._fallback_event_result()

    # ── Main analysis ─────────────────────────────────────────────────

    async def analyze_single(self, text: str, vehicle_name: str = "", vehicle_brand: str = "",
                             confusables: list[str] | None = None) -> dict:
        if not text or not text.strip():
            return self._fallback_result()
        if not self._api_key:
            return self._fallback_result()
        vehicle_name = vehicle_name or "本车型"
        vehicle_brand = vehicle_brand or ""
        prompt = COMBINED_ANALYSIS_PROMPT.format(
            event_tags="、".join(EVENT_TAG_POOL),
            vehicle_name=vehicle_name,
            vehicle_brand=vehicle_brand,
            confusables=_format_confusables(confusables or [], vehicle_name,
                                            self_aliases=_self_alias_cache.get(vehicle_name)),
            text=text,
        )
        try:
            raw = await self._call_api(prompt)
            return self._parse_response(raw)
        except Exception:
            logger.warning("analyze_single API failed, returning fallback")
            return self._fallback_result()

    async def analyze_batch(self, posts: list[dict], vehicle_name: str = "", vehicle_brand: str = "",
                            confusables: list[str] | None = None) -> list[dict]:
        # 并发调用，用信号量限速避免触发 API 限流（顺序与输入一致）
        # v3 I-3：batch 级填充本车别名缓存（analyze_single 的 prompt 注入用）
        if vehicle_name:
            from pipeline.analysis.relevance_filter import get_vehicle_aliases  # noqa: inline-import
            _self_alias_cache[vehicle_name] = get_vehicle_aliases(vehicle_name)
        sem = asyncio.Semaphore(_API_CONCURRENCY)

        async def _one(post):
            async with sem:
                analysis = await self.analyze_single(post.get("content", ""), vehicle_name, vehicle_brand,
                                                      confusables)
                return {"id": post.get("id", ""), "content": post.get("content", ""), **analysis}

        return list(await asyncio.gather(*[_one(p) for p in posts]))

    # ── Response parsing (combined prompt) ────────────────────────────

    @staticmethod
    def _parse_response(raw: str) -> dict:
        data = extract_json_object(raw)
        if data is None:
            return AnalysisPipeline._fallback_result()

        valid_sentiments = {"positive", "negative", "neutral"}
        sentiment = data.get("sentiment", "neutral")
        if sentiment not in valid_sentiments:
            sentiment = "neutral"

        event_tags = data.get("event_tags", []) or []
        if not isinstance(event_tags, list):
            event_tags = []
        event_tags = [t for t in event_tags if t in EVENT_TAG_POOL]

        dim_sentiment = data.get("dim_sentiment", {}) or {}
        if not isinstance(dim_sentiment, dict):
            dim_sentiment = {}
        # 只保留 15 个标准维度，丢弃 LLM 自创维度（销量/砍价技巧/颠簸道路稳定性 等）
        dim_sentiment = {k: v for k, v in dim_sentiment.items() if k in VALID_DIMENSIONS}

        opinion_tags = data.get("opinion_tags", []) or []
        if not isinstance(opinion_tags, list):
            opinion_tags = []

        subject = data.get("subject", "self")
        if subject not in {"self", "competitor", "other"}:
            subject = "self"
        subject_name = data.get("subject_name", "") or ""
        if not isinstance(subject_name, str):
            subject_name = ""

        return {
            "sentiment": sentiment,
            "event_tags": event_tags,
            "opinion_tags": opinion_tags,
            "dim_sentiment": dim_sentiment,
            "subject": subject,
            "subject_name": subject_name,
            "confidence": _safe_confidence(data.get("confidence")),
        }

    # ── Response parsing (event-only prompt) ──────────────────────────

    @staticmethod
    def _parse_event_response(raw: str) -> dict:
        data = extract_json_object(raw)
        if data is None:
            return AnalysisPipeline._fallback_event_result()

        event_tags = data.get("event_tags", []) or []
        if not isinstance(event_tags, list):
            event_tags = []
        event_tags = [t for t in event_tags if t in EVENT_TAG_POOL]

        opinion_tags = data.get("opinion_tags", []) or []
        if not isinstance(opinion_tags, list):
            opinion_tags = []

        subject = data.get("subject", "self")
        if subject not in {"self", "competitor", "other"}:
            subject = "self"
        subject_name = data.get("subject_name", "") or ""
        if not isinstance(subject_name, str):
            subject_name = ""

        return {
            "event_tags": event_tags,
            "opinion_tags": opinion_tags,
            "subject": subject,
            "subject_name": subject_name,
            "confidence": _safe_confidence(data.get("confidence")),
        }

    @staticmethod
    def _fallback_result() -> dict:
        return {
            "sentiment": "neutral",
            "event_tags": [],
            "opinion_tags": [],
            "dim_sentiment": {},
            "subject": "self",
            "subject_name": "",
            "confidence": 0.0,
        }

    @staticmethod
    def _fallback_event_result() -> dict:
        return {
            "event_tags": [],
            "opinion_tags": [],
            "subject": "self",
            "subject_name": "",
            "confidence": 0.0,
        }
