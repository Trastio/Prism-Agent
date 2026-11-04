"""LLM 标签提取器：使用 qwen3.5-27b 从口碑文本中语义提取买点/槽点标签

策略：关键词匹配优先（快速零成本），LLM 兜底补充（语义理解）。
- 关键词已命中的口碑不再调用 LLM
- 关键词未命中的口碑由 LLM 从预定义标签集选择 + 发现新标签
- 支持批量处理、速率控制、断点续传
"""
import json
import re
import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

TAGGER_BASE_URL = os.environ.get(
    "TAGGER_LLM_BASE_URL",
    os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
)
TAGGER_API_KEY = os.environ.get(
    "TAGGER_LLM_API_KEY",
    os.environ.get("LLM_API_KEY", "")
)
TAGGER_MODEL = os.environ.get(
    "TAGGER_LLM_MODEL",
    os.environ.get("LLM_MODEL", "deepseek-chat")
)

_REASONING_MODEL_PATTERNS = ["reasoning", "thinking", "deepseek-r1", "deepseek-reasoner", "o1", "o3"]


def _is_reasoning_model(model: str) -> bool:
    model_lower = model.lower()
    return any(p in model_lower for p in _REASONING_MODEL_PATTERNS)

L1_CATEGORIES = ["空间", "外观", "内饰", "驾驶感受", "续航", "性价比", "智能化", "舒适"]

L2_TAG_MAP = {
    "空间": {"pro": ["空间大", "后排宽敞", "后备箱大"], "con": ["空间小", "后排拥挤", "后备箱小"]},
    "外观": {"pro": ["外观好看", "造型时尚", "颜值高"], "con": ["外观普通", "车漆薄", "颜色少"]},
    "内饰": {"pro": ["内饰好看", "用料好", "做工精细"], "con": ["内饰差", "塑料感强", "做工粗糙", "异味大"]},
    "驾驶感受": {"pro": ["动力强", "操控好", "加速快", "好开"], "con": ["动力弱", "操控差", "起步慢"]},
    "续航": {"pro": ["续航长", "续航扎实", "能耗低", "充电快"], "con": ["续航短", "续航虚", "掉电快", "能耗高", "充电慢", "充电不便"]},
    "性价比": {"pro": ["性价比高", "配置丰富", "价格实惠"], "con": ["性价比低", "价格贵", "减配"]},
    "智能化": {
        "pro": ["辅助驾驶好用", "车机流畅", "语音好用", "OTA便捷", "泊车辅助好"],
        "con": ["辅助驾驶差", "车机问题", "OTA问题", "语音问题", "智能化不足"],
    },
    "舒适": {"pro": ["座椅舒适", "隔音好", "悬挂舒适"], "con": ["隔音差", "悬挂硬", "噪音大", "异响", "座椅不舒适"]},
}

TAGGER_SYSTEM_PROMPT = """你是一个汽车口碑两级标签提取器。从口碑文本中提取结构化标签。

## 两级标签体系

一级标签(tag_category)是维度分类，二级标签(tag_name)是具体观点。

一级标签和对应二级标签参考：
- 空间: 空间大/后排宽敞/后备箱大 | 空间小/后排拥挤/后备箱小
- 外观: 外观好看/造型时尚/颜值高 | 外观普通/车漆薄/颜色少
- 内饰: 内饰好看/用料好/做工精细 | 内饰差/塑料感强/做工粗糙/异味大
- 驾驶感受: 动力强/操控好/加速快/好开 | 动力弱/操控差/起步慢
- 续航: 续航长/续航扎实/能耗低/充电快 | 续航短/续航虚/掉电快/能耗高/充电慢/充电不便
- 性价比: 性价比高/配置丰富/价格实惠 | 性价比低/价格贵/减配
- 智能化: 辅助驾驶好用/车机流畅/语音好用/OTA便捷/泊车辅助好 | 辅助驾驶差/车机问题/OTA问题/语音问题/智能化不足
- 舒适: 座椅舒适/隔音好/悬挂舒适 | 隔音差/悬挂硬/噪音大/异响/座椅不舒适

## 提取规则

1. 从文本中提取买点(pro)和槽点(con)
2. 先判断属于哪个一级维度(tag_category)，再归纳具体观点为二级标签(tag_name)
3. **必须从上述封闭标签表中选择 tag_name，禁止新增**；二级标签应精炼（2-6字）
4. 如原文观点无法对应任何封闭标签，则不标该标签（允许多条口碑无标签）；每条口碑最多6个标签
5. 必须提供 source_text（原文片段）

## 输出格式

严格输出JSON：
{"tags": [{"tag_category": "一级维度", "tag_name": "二级标签", "sentiment": "pro或con", "confidence": 0.9, "source_text": "原文片段"}]}"""

TAGGER_USER_TEMPLATE = """请从以下车主口碑文本中提取两级标签：

【最满意】{best_text}

【最不满意】{worst_text}

请输出 JSON 格式的标签列表。"""

TAGGER_BATCH_SYSTEM_PROMPT = """你是一个汽车口碑两级标签提取器。从多条口碑文本中分别提取结构化标签。

## 两级标签体系
一级标签(tag_category)是维度分类，二级标签(tag_name)是具体观点。

一级标签和对应二级标签参考：
- 空间: 空间大/后排宽敞/后备箱大 | 空间小/后排拥挤/后备箱小
- 外观: 外观好看/造型时尚/颜值高 | 外观普通/车漆薄/颜色少
- 内饰: 内饰好看/用料好/做工精细 | 内饰差/塑料感强/做工粗糙/异味大
- 驾驶感受: 动力强/操控好/加速快/好开 | 动力弱/操控差/起步慢
- 续航: 续航长/续航扎实/能耗低/充电快 | 续航短/续航虚/掉电快/能耗高/充电慢/充电不便
- 性价比: 性价比高/配置丰富/价格实惠 | 性价比低/价格贵/减配
- 智能化: 辅助驾驶好用/车机流畅/语音好用/OTA便捷/泊车辅助好 | 辅助驾驶差/车机问题/OTA问题/语音问题/智能化不足
- 舒适: 座椅舒适/隔音好/悬挂舒适 | 隔音差/悬挂硬/噪音大/异响/座椅不舒适

## 提取规则
1. 从每条口碑的文本中分别提取买点和槽点
2. 先判断维度(tag_category)，再归纳观点(tag_name)
3. **必须从上述封闭标签表中选择 tag_name，禁止新增**；tag_name 精炼(2-6字)
4. 如原文观点无法对应任何封闭标签，则不标该标签（允许多条口碑无标签）；每条口碑最多6个标签
5. 必须提供 source_text

## 输出格式

严格输出JSON（不要markdown代码块）：
{"results": [{"id": "序号", "tags": [{"tag_category": "维度", "tag_name": "标签", "sentiment": "pro或con", "confidence": 0.9, "source_text": "原文片段"}]}]}"""


def _build_messages(best_text: str, worst_text: str) -> list[dict]:
    best = best_text.strip() if best_text else "（无内容）"
    worst = worst_text.strip() if worst_text else "（无内容）"
    return [
        {"role": "system", "content": TAGGER_SYSTEM_PROMPT},
        {"role": "user", "content": TAGGER_USER_TEMPLATE.format(best_text=best, worst_text=worst)},
    ]


def _infer_category(tag_name: str, sentiment: str) -> str:
    """Infer L1 category from L2 tag_name by checking L2_TAG_MAP."""
    for cat, sent_map in L2_TAG_MAP.items():
        for tag in sent_map.get(sentiment, []):
            if tag == tag_name:
                return cat
    for cat, sent_map in L2_TAG_MAP.items():
        for tag in sent_map.get(sentiment, []):
            if tag in tag_name or tag_name in tag:
                return cat
    return "其他"


def _finalize_tags(tags: list[dict]) -> list[dict]:
    """归一 → sentiment 校验 → 去重。两条解析路径统一出口。"""
    from src.nlp.tag_normalize import normalize_tag, get_valid_pairs
    valid_pairs = get_valid_pairs()
    valid_names = {p[0] for p in valid_pairs}
    unknown_count = 0
    invalid_count = 0
    seen = set()
    result = []
    for tag in tags:
        original = tag.get("tag_name", "")
        normalized = normalize_tag(original, tag.get("tag_category", ""))
        tag["tag_name"] = normalized
        senti = tag.get("sentiment", "")
        if (normalized, senti) not in valid_pairs:
            # 尝试纠正 sentiment
            if (normalized, "pro") in valid_pairs:
                tag["sentiment"] = "pro"
                senti = "pro"
            elif (normalized, "con") in valid_pairs:
                tag["sentiment"] = "con"
                senti = "con"
            else:
                invalid_count += 1
                continue
        if normalized not in valid_names:
            unknown_count += 1
        key = (normalized, senti)
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
    if unknown_count > 0:
        logger.warning(f"标签归一：{unknown_count} 个未知标签未映射")
    if invalid_count > 0:
        logger.warning(f"标签校验：{invalid_count} 个非法组合已丢弃")
    return result


def _parse_response(response: dict) -> list[dict]:
    """解析 LLM 返回的 JSON 标签列表"""
    try:
        choices = response.get("choices", [])
        if not choices:
            return []
        content = choices[0].get("message", {}).get("content", "")
        content = content.strip()
        content = re.sub(r'<think[\s\S]*?</think\s*>', '', content, flags=re.IGNORECASE).strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        if content.startswith("```json"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        # GLM 有时在 JSON 后附"说明"文字导致 Extra data 错误——只取第一个完整 JSON 对象
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # 尝试提取第一个 {...} 块（忽略后面附带的说明文字）
            match = re.search(r'\{[\s\S]*\}', content)
            if match:
                data = json.loads(match.group())
            else:
                raise
        if isinstance(data, list):
            tags = data
        elif isinstance(data, dict):
            tags = data.get("tags", [])
        else:
            tags = []
        result = []
        for tag in tags:
            tag_name = tag.get("tag_name", "").strip()
            sentiment = tag.get("sentiment", "")
            if not tag_name or sentiment not in ("pro", "con"):
                continue
            tag_category = tag.get("tag_category", "").strip()
            if tag_category and tag_category not in L1_CATEGORIES:
                tag_category = _infer_category(tag_name, sentiment)
            elif not tag_category:
                tag_category = _infer_category(tag_name, sentiment)
            confidence = tag.get("confidence", 0.8)
            try:
                confidence = float(confidence)
            except (ValueError, TypeError):
                confidence = 0.8
            confidence = max(0.0, min(1.0, confidence))
            source_text = tag.get("source_text", "")[:100]
            result.append({
                "tag_category": tag_category,
                "tag_name": tag_name,
                "sentiment": sentiment,
                "confidence": confidence,
                "source_text": source_text,
            })
        result = _finalize_tags(result)
        return result
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"LLM 标签解析失败: {e}, content={content[:200] if 'content' in dir() else ''}")
        return []


def _parse_batch_response(response: dict, reviews: list[dict]) -> dict[str, list[dict]]:
    """Parse batch LLM response and map results to review IDs."""
    try:
        choices = response.get("choices", [])
        if not choices:
            return {}
        content = choices[0].get("message", {}).get("content", "")
        content = re.sub(r'<think[\s\S]*?</think\s*>', '', content, flags=re.IGNORECASE).strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        data = json.loads(content)
        results_list = data.get("results", []) if isinstance(data, dict) else data

        results = {}
        for item in results_list:
            try:
                idx = int(item.get("id", "0")) - 1
            except (ValueError, TypeError):
                continue
            if not (0 <= idx < len(reviews)):
                continue
            rid = reviews[idx].get("review_id", "")
            tags = []
            for tag in item.get("tags", []):
                tag_name = tag.get("tag_name", "").strip()
                sentiment = tag.get("sentiment", "")
                if not tag_name or sentiment not in ("pro", "con"):
                    continue
                tag_category = tag.get("tag_category", "").strip()
                if not tag_category or tag_category not in L1_CATEGORIES:
                    tag_category = _infer_category(tag_name, sentiment)
                confidence = tag.get("confidence", 0.8)
                try:
                    confidence = float(confidence)
                except (ValueError, TypeError):
                    confidence = 0.8
                tags.append({
                    "tag_category": tag_category,
                    "tag_name": tag_name,
                    "sentiment": sentiment,
                    "confidence": max(0.0, min(1.0, confidence)),
                    "source_text": tag.get("source_text", "")[:100],
                })
            if tags:
                results[rid] = _finalize_tags(tags)
        return results
    except Exception as e:
        logger.warning(f"Batch response parse failed: {e}")
        return {}


class LLMTagger:
    """LLM 标签提取器，基于 qwen3.5-27b"""

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None):
        self.base_url = base_url or TAGGER_BASE_URL
        self.api_key = api_key or TAGGER_API_KEY
        self.model = model or TAGGER_MODEL
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> "httpx.AsyncClient":
        if self._client is None:
            import httpx
            limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
            timeout = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=120.0)
            self._client = httpx.AsyncClient(timeout=timeout, limits=limits)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def extract_tags(self, best_text: str, worst_text: str,
                           max_retries: int = 1) -> list[dict]:
        """对单条口碑提取标签"""
        if not best_text.strip() and not worst_text.strip():
            return []

        messages = _build_messages(best_text, worst_text)
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 2048,
        }
        if not _is_reasoning_model(self.model):
            body["temperature"] = 0

        client = await self._get_client()
        last_error = None

        for attempt in range(max_retries):
            try:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=body,
                )
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", "5"))
                    logger.warning(f"标签提取限流，等待 {retry_after}s")
                    await asyncio.sleep(retry_after)
                    continue
                if resp.status_code >= 400:
                    err = resp.text[:500]
                    logger.error(f"标签提取 API 错误 {resp.status_code}: {err}")
                    resp.raise_for_status()
                result = resp.json()
                tags = _parse_response(result)
                return tags
            except Exception as e:
                last_error = e
                wait = 1 * (2 ** attempt)
                logger.warning(f"标签提取失败 (attempt {attempt + 1}/{max_retries}): {type(e).__name__}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(wait)

        logger.error(f"标签提取最终失败: {type(last_error).__name__}: {last_error}")
        return []

    async def _extract_batch(self, reviews: list[dict]) -> dict[str, list[dict]]:
        """Extract tags from multiple reviews in one API call."""
        if not reviews:
            return {}
        if len(reviews) == 1:
            tags = await self.extract_tags(
                reviews[0].get("best_review_text", ""),
                reviews[0].get("worst_review_text", ""),
            )
            rid = reviews[0].get("review_id", "")
            return {rid: tags} if tags else {}

        reviews_block = ""
        for i, r in enumerate(reviews, 1):
            best = (r.get("best_review_text") or "").strip() or "（无内容）"
            worst = (r.get("worst_review_text") or "").strip() or "（无内容）"
            reviews_block += f"\n### 口碑 #{i}\n【最满意】{best}\n【最不满意】{worst}\n"

        messages = [
            {"role": "system", "content": TAGGER_BATCH_SYSTEM_PROMPT},
            {"role": "user", "content": f"请从以下{len(reviews)}条车主口碑中分别提取标签：{reviews_block}"},
        ]
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": min(4096, 1024 * len(reviews)),
        }
        if not _is_reasoning_model(self.model):
            body["temperature"] = 0

        client = await self._get_client()

        for attempt in range(3):
            try:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=body,
                )
                if resp.status_code == 429:
                    await asyncio.sleep(int(resp.headers.get("Retry-After", "5")))
                    continue
                resp.raise_for_status()
                result = resp.json()
                return _parse_batch_response(result, reviews)
            except Exception as e:
                wait = 2 ** attempt
                logger.warning(f"Batch extraction failed (attempt {attempt + 1}/3): {e}")
                if attempt < 2:
                    await asyncio.sleep(wait)

        logger.warning("Batch extraction failed after 3 attempts, falling back to individual")
        fallback = {}
        for r in reviews:
            tags = await self.extract_tags(r.get("best_review_text", ""), r.get("worst_review_text", ""))
            if tags:
                fallback[r.get("review_id", "")] = tags
        return fallback

    async def batch_extract(self, reviews: list[dict],
                            concurrency: int = 0,
                            skip_review_ids: set | None = None,
                            progress_callback=None) -> dict[str, list[dict]]:
        """批量提取标签（每5条口碑合并一次API调用），返回 {review_id: [tag_dict, ...]}"""
        if concurrency <= 0:
            concurrency = int(os.environ.get("TAGGER_CONCURRENCY", "10"))
        skip = skip_review_ids or set()

        to_process = []
        skipped = 0
        for r in reviews:
            rid = r.get("review_id", "")
            if rid in skip:
                skipped += 1
                continue
            best = r.get("best_review_text", "") or ""
            worst = r.get("worst_review_text", "") or ""
            if not best.strip() and not worst.strip():
                skipped += 1
                continue
            to_process.append(r)

        if not to_process:
            return {}

        total = len(to_process)
        processed = 0
        lock = asyncio.Lock()
        results: dict[str, list[dict]] = {}

        batch_size = int(os.environ.get("TAGGER_BATCH_SIZE", "3"))
        batches = [to_process[i:i + batch_size] for i in range(0, len(to_process), batch_size)]
        semaphore = asyncio.Semaphore(concurrency)

        async def process_batch(batch):
            nonlocal processed
            async with semaphore:
                batch_result = await self._extract_batch(batch)
            async with lock:
                results.update(batch_result)
                processed += len(batch)
                if processed % 10 == 0 or processed >= total:
                    logger.info(f"LLM 标签提取进度: {processed}/{total} (跳过 {skipped})")
                    if progress_callback:
                        try:
                            progress_callback(processed, total, skipped)
                        except Exception:
                            pass

        await asyncio.gather(*[process_batch(b) for b in batches], return_exceptions=True)

        total_tags = sum(len(v) for v in results.values())
        logger.info(f"LLM 标签提取完成: 处理 {processed} 条, 跳过 {skipped} 条, 提取标签 {total_tags} 个")
        return results


_tagger: LLMTagger | None = None


async def get_tagger() -> LLMTagger:
    global _tagger
    if _tagger is None:
        _tagger = LLMTagger()
    return _tagger


async def close_tagger():
    global _tagger
    if _tagger:
        await _tagger.close()
        _tagger = None
