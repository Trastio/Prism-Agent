import asyncio
import json
import random
import re
import logging
from src.api.autohome_api import AutohomeAPI, get_autohome_api
from src.storage.db import session_scope
from src.models.orm import OwnerReview, ReviewTag, SeriesSummary
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy import func

logger = logging.getLogger(__name__)

TAG_KEYWORDS = {
    "pro": {
        "空间大": ["空间大", "空间宽敞", "空间充裕", "空间够用", "空间足", "后排空间", "乘坐空间大"],
        "外观好看": ["外观好看", "颜值高", "外观漂亮", "外观大气", "造型好看", "外观时尚", "外观满意"],
        "动力强": ["动力强", "动力足", "动力充沛", "加速快", "提速快", "动力够用", "动力满意"],
        "续航长": ["续航长", "续航够", "续航满意", "续航扎实", "续航足", "续航表现好"],
        "舒适性好": ["舒适", "座椅舒服", "座椅舒适", "悬挂软", "减震好", "隔音好", "静谧性好", "乘坐舒适"],
        "性价比高": ["性价比高", "性价比不错", "价格实惠", "值得买", "划算", "物有所值"],
        "操控好": ["操控好", "操控灵活", "方向盘轻", "转向精准", "好开", "驾驶感受好"],
        "配置丰富": ["配置丰富", "配置高", "功能多", "辅助驾驶", "L2", "自适应巡航", "自动泊车"],
        "油耗低": ["油耗低", "省油", "油耗满意", "油耗不错", "能耗低", "电耗低"],
        "内饰好": ["内饰好看", "内饰精致", "内饰满意", "用料好", "做工精细", "质感好"],
    },
    "con": {
        "空间小": ["空间小", "空间不够", "后排拥挤", "后备箱小", "乘坐空间小"],
        "外观不好看": ["外观不好看", "颜值低", "外观一般", "造型普通"],
        "动力弱": ["动力弱", "动力不足", "起步慢", "加速慢", "提速慢", "动力差"],
        "续航短": ["续航短", "续航不够", "续航虚", "续航打折", "掉电快"],
        "舒适性差": ["悬挂硬", "减震差", "隔音差", "噪音大", "胎噪大", "风噪大", "异响", "颠簸"],
        "性价比低": ["性价比低", "价格贵", "价格高", "不值", "减配"],
        "操控差": ["操控差", "方向盘重", "转向模糊", "不好开"],
        "内饰差": ["内饰差", "内饰一般", "用料差", "塑料感强", "做工粗糙"],
        "油耗高": ["油耗高", "费油", "油耗大", "能耗高", "电耗高"],
    },
}


def extract_tags(text: str, sentiment_hint: str = "") -> list[dict]:
    if not text or not text.strip():
        return []
    tags = []
    search_map = {}
    if sentiment_hint:
        search_map = {sentiment_hint: TAG_KEYWORDS.get(sentiment_hint, {})}
    else:
        search_map = TAG_KEYWORDS
    for sentiment, tag_map in search_map.items():
        for tag_name, keywords in tag_map.items():
            for kw in keywords:
                if kw in text:
                    tags.append({
                        "tag_name": tag_name,
                        "sentiment": sentiment,
                        "source_text": kw,
                        "confidence": 0.8,
                    })
                    break
    return tags


def _save_chunk_tags(session, model_id: str, chunk: list[dict],
                     llm_results: dict) -> int:
    """把一个 chunk 的 LLM 标签结果 upsert 入库。

    (review_id, tag_name, sentiment) 唯一：冲突时 ON CONFLICT DO UPDATE
    刷新 tag_category/source_text/confidence，不产生新行（幂等，并发安全）。
    返回：本 chunk 中写入了标签的口碑数。
    """
    chunk_saved = 0
    for rid, tags in llm_results.items():
        if not tags:
            continue
        review_info = next((r for r in chunk if r["review_id"] == rid), {})
        for tag in tags:
            stmt = insert(ReviewTag).values(
                review_id=rid,
                owner_id=review_info.get("owner_id", ""),
                model_full_name=review_info.get("model_full_name", ""),
                model_id=model_id,
                tag_category=tag.get("tag_category", ""),
                tag_name=tag["tag_name"],
                sentiment=tag["sentiment"],
                source_text=tag.get("source_text", ""),
                confidence=tag.get("confidence", 0.8),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["review_id", "tag_name", "sentiment"],
                set_={
                    "tag_category": stmt.excluded.tag_category,
                    "source_text": stmt.excluded.source_text,
                    "confidence": stmt.excluded.confidence,
                },
            )
            session.execute(stmt)
        chunk_saved += 1
    return chunk_saved


class ReviewCollector:
    def __init__(self, api: AutohomeAPI | None = None):
        self.api = api
        self._series_name_cache: dict[str, str] = {}

    async def _ensure_api(self) -> AutohomeAPI:
        if self.api is None:
            self.api = await get_autohome_api()
        return self.api

    async def _get_series_display_name(self, series_id: str) -> str:
        if series_id in self._series_name_cache:
            return self._series_name_cache[series_id]
        try:
            api = await self._ensure_api()
            index = await api.build_series_index()
            info = index.get(series_id)
            name = info.get("name", "") if info else ""
            self._series_name_cache[series_id] = name
            return name
        except Exception as e:
            logger.warning(f"获取车系名称失败: {e}")
            return ""

    async def _save_series_summary(self, api: AutohomeAPI, series_id: str):
        """Persist series summary to DB during collection."""
        try:
            summary = await api.get_series_summary(series_id)
            if "error" in summary:
                return
            with session_scope() as session:
                stmt = insert(SeriesSummary).values(
                    series_id=series_id,
                    series_name=summary.get("series_name"),
                    brand_name=summary.get("brand_name"),
                    brand_id=summary.get("brand_id"),
                    level_name=summary.get("level_name"),
                    level_id=summary.get("level_id"),
                    price_range=summary.get("price_range"),
                    min_price=summary.get("min_price"),
                    max_price=summary.get("max_price"),
                    average_score=summary.get("average_score"),
                    dimension_scores=summary.get("dimension_scores"),
                    review_count=summary.get("review_count"),
                    onsell_review_count=summary.get("onsell_review_count"),
                    pph=summary.get("pph"),
                    level_rank=summary.get("level_rank"),
                    level_series_count=summary.get("level_series_count"),
                    powertype=summary.get("powertype"),
                    cmp_scores=summary.get("cmp_scores"),
                    cmp_pph=summary.get("cmp_pph"),
                    consumption=summary.get("consumption"),
                    consumption_battery=summary.get("consumption_battery"),
                    spec_groups=summary.get("spec_groups"),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["series_id"],
                    set_=dict(
                        series_name=summary.get("series_name"),
                        brand_name=summary.get("brand_name"),
                        price_range=summary.get("price_range"),
                        min_price=summary.get("min_price"),
                        max_price=summary.get("max_price"),
                        average_score=summary.get("average_score"),
                        dimension_scores=summary.get("dimension_scores"),
                        review_count=summary.get("review_count"),
                        onsell_review_count=summary.get("onsell_review_count"),
                        pph=summary.get("pph"),
                        level_rank=summary.get("level_rank"),
                        level_series_count=summary.get("level_series_count"),
                        powertype=summary.get("powertype"),
                        cmp_scores=summary.get("cmp_scores"),
                        cmp_pph=summary.get("cmp_pph"),
                        consumption=summary.get("consumption"),
                        consumption_battery=summary.get("consumption_battery"),
                        spec_groups=summary.get("spec_groups"),
                    )
                )
                session.execute(stmt)
            logger.info(f"车系汇总已保存: {series_id}")
        except Exception as e:
            logger.warning(f"保存车系汇总失败: {e}")

    async def resolve_target(self, input_str: str) -> dict:
        url_match = re.search(r'k\.autohome\.com\.cn/(\d+)/', input_str)
        if url_match:
            return {"series_id": url_match.group(1), "method": "url"}
        from src.scraper.searcher import ModelSearcher
        searcher = ModelSearcher()
        results = await searcher.search(input_str)
        if results:
            return {"series_id": results[0]["series_id"], "method": "search", "results": results}
        raise ValueError(f"未找到匹配车型: {input_str}")

    async def collect(self, series_id: str, max_pages: int | None = None,
                      use_llm: bool = True, progress_callback=None) -> int:
        if max_pages is not None and not isinstance(max_pages, int):
            max_pages = int(max_pages)
        api = await self._ensure_api()
        result = await api.fetch_koubei_page(series_id, page_index=1, page_size=20)
        if result and result.get("list"):
            return await self._collect_all(api, series_id, result, max_pages,
                                           use_llm=use_llm,
                                           progress_callback=progress_callback)

        logger.warning("口碑API不可用，无法采集")
        return 0

    async def _collect_all(self, api: AutohomeAPI, series_id: str,
                           first_result: dict, max_pages: int | None = None,
                           use_llm: bool = True, progress_callback=None) -> int:
        if max_pages is not None and not isinstance(max_pages, int):
            max_pages = int(max_pages)
        page_count = first_result.get("pagecount", 1)
        row_count = first_result.get("rowcount", 0)
        logger.info(f"口碑API: 共{row_count}条, {page_count}页")

        series_display_name = await self._get_series_display_name(series_id)

        await self._save_series_summary(api, series_id)

        all_reviews = []
        reviews = [api.parse_koubei_item(item, series_display_name) for item in first_result.get("list", [])]
        saved = self._save_reviews(reviews, series_id)
        all_reviews.extend(reviews)
        logger.info(f"第1/{page_count}页: {len(reviews)}条, 已保存{saved}条")

        if progress_callback:
            try:
                progress_callback(1, page_count, f"采集口碑 1/{page_count}页")
            except Exception:
                pass

        actual_pages = min(page_count, max_pages) if max_pages else page_count
        if actual_pages * 20 < row_count:
            actual_pages = (row_count + 19) // 20
            logger.info(f"API返回页数不足，按总量修正: {actual_pages}页")

        empty_page_count = 0
        MAX_EMPTY_PAGES = 3

        for page in range(2, actual_pages + 1):
            await asyncio.sleep(random.uniform(0.3, 0.8))
            result = await api.fetch_koubei_page(series_id, page_index=page, page_size=20)
            if not result or not result.get("list"):
                empty_page_count += 1
                logger.warning(f"第{page}页无数据（连续空页{empty_page_count}/{MAX_EMPTY_PAGES}）")
                if empty_page_count >= MAX_EMPTY_PAGES:
                    logger.warning(f"连续{MAX_EMPTY_PAGES}页无数据，停止采集")
                    break
                continue

            empty_page_count = 0
            page_reviews = [api.parse_koubei_item(item, series_display_name) for item in result["list"]]
            page_saved = self._save_reviews(page_reviews, series_id)
            all_reviews.extend(page_reviews)
            saved += page_saved
            logger.info(f"第{page}/{actual_pages}页: {len(page_reviews)}条, 累计{saved}条")

            if progress_callback:
                try:
                    progress_callback(page, actual_pages, f"采集口碑 {page}/{actual_pages}页，累计{saved}条")
                except Exception:
                    pass

        if len(all_reviews) < row_count:
            logger.warning(f"采集不完整: 期望{row_count}条, 实际{len(all_reviews)}条，按年款补采")
            await self._collect_by_years(api, series_id, all_reviews, row_count,
                                          series_display_name,
                                          progress_callback=progress_callback)

        if use_llm:
            if progress_callback:
                try:
                    progress_callback(len(all_reviews), len(all_reviews), "正在提取标签...")
                except Exception:
                    pass
            await self._llm_extract_all_tags(all_reviews, series_id)

        return saved

    async def _collect_by_years(self, api: AutohomeAPI, series_id: str,
                                 all_reviews: list, row_count: int,
                                 series_display_name: str,
                                 progress_callback=None):
        syear_ids = set()
        for r in all_reviews:
            raw = r.get("_raw_item", {})
            syid = raw.get("syearId")
            if syid:
                syear_ids.add(syid)

        if not syear_ids:
            logger.warning("未找到syearId，无法按年款补采")
            return

        logger.info(f"发现 {len(syear_ids)} 个年款: {sorted(syear_ids)}")
        existing_ids = {r["review_id"] for r in all_reviews}

        for syid in sorted(syear_ids):
            result = await api.fetch_koubei_page(series_id, page_index=1, page_size=10, yearid=syid)
            if not result or not result.get("list"):
                continue

            yr_pagecount = result.get("pagecount", 0)
            page_reviews = [api.parse_koubei_item(item, series_display_name) for item in result["list"]]
            new_reviews = [r for r in page_reviews if r["review_id"] not in existing_ids]
            if new_reviews:
                self._save_reviews(new_reviews, series_id)
                all_reviews.extend(new_reviews)
                existing_ids.update(r["review_id"] for r in new_reviews)

            for page in range(2, yr_pagecount + 1):
                await asyncio.sleep(random.uniform(0.3, 0.8))
                result = await api.fetch_koubei_page(series_id, page_index=page, page_size=10, yearid=syid)
                if not result or not result.get("list"):
                    break
                page_reviews = [api.parse_koubei_item(item, series_display_name) for item in result["list"]]
                new_reviews = [r for r in page_reviews if r["review_id"] not in existing_ids]
                if new_reviews:
                    self._save_reviews(new_reviews, series_id)
                    all_reviews.extend(new_reviews)
                    existing_ids.update(r["review_id"] for r in new_reviews)

            logger.info(f"年款{syid}: 补采完成, 总计{len(all_reviews)}条")

            if progress_callback:
                try:
                    progress_callback(len(all_reviews), row_count, f"按年款补采 {len(all_reviews)}/{row_count}")
                except Exception:
                    pass

        if len(all_reviews) >= row_count:
            logger.info(f"补采完成: 总计{len(all_reviews)}条 >= 期望{row_count}条")
        else:
            logger.warning(f"补采后仍不完整: {len(all_reviews)}/{row_count}条")

    def _save_reviews(self, reviews: list[dict], model_id: str) -> int:
        from datetime import date as date_type
        with session_scope() as session:
            count = 0
            for r in reviews:
                purchase_date = r.get("purchase_date")
                if isinstance(purchase_date, str) and purchase_date:
                    try:
                        from datetime import datetime
                        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y.%m.%d", "%Y.%m"):
                            try:
                                purchase_date = datetime.strptime(
                                    purchase_date.replace(".", "-"), fmt
                                ).date()
                                break
                            except ValueError:
                                continue
                        else:
                            purchase_date = None
                    except (ValueError, TypeError):
                        purchase_date = None
                elif not isinstance(purchase_date, date_type):
                    purchase_date = None

                raw_item = r.get("_raw_item", {})
                post_date = raw_item.get("posttime", "") or ""
                if isinstance(post_date, str):
                    post_date = post_date.strip()

                stmt = insert(OwnerReview).values(
                    review_id=r["review_id"],
                    owner_id=r["owner_id"],
                    model_full_name=r["model_full_name"],
                    spec_name=r.get("spec_name"),
                    spec_id=r.get("spec_id"),
                    model_id=model_id,
                    purchase_date=purchase_date,
                    post_date=post_date,
                    best_review_text=r["best_review_text"],
                    worst_review_text=r["worst_review_text"],
                    score=r.get("score"),
                    dimensions=r.get("dimensions"),
                    buy_price=r.get("buy_price"),
                    fuel_consumption=r.get("fuel_consumption"),
                    mileage=r.get("mileage"),
                    city=r.get("city"),
                    use_purposes=r.get("use_purposes"),
                    dimension_reviews=r.get("dimension_reviews"),
                    exinfo=r.get("exinfo"),
                    raw_json=r,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["review_id"],
                    set_=dict(
                        best_review_text=r["best_review_text"],
                        worst_review_text=r["worst_review_text"],
                        model_full_name=r["model_full_name"],
                        spec_name=r.get("spec_name"),
                        spec_id=r.get("spec_id"),
                        purchase_date=purchase_date,
                        post_date=post_date,
                        score=r.get("score"),
                        dimensions=r.get("dimensions"),
                        buy_price=r.get("buy_price"),
                        fuel_consumption=r.get("fuel_consumption"),
                        mileage=r.get("mileage"),
                        city=r.get("city"),
                        use_purposes=r.get("use_purposes"),
                        dimension_reviews=r.get("dimension_reviews"),
                        exinfo=r.get("exinfo"),
                        raw_json=r,
                        fetched_at=func.now(),
                    )
                )
                session.execute(stmt)

                best_text = r.get("best_review_text", "")
                worst_text = r.get("worst_review_text", "")
                r["_has_text"] = bool((best_text or "").strip() or (worst_text or "").strip())

                count += 1
        return count

    async def _llm_extract_all_tags(self, reviews: list[dict], model_id: str,
                                     progress_callback=None) -> int:
        text_reviews = [r for r in reviews if r.get("_has_text")]
        if not text_reviews:
            return 0

        with session_scope() as session:
            tagged_ids = {r[0] for r in session.query(ReviewTag.review_id).filter(
                ReviewTag.model_id == model_id
            ).distinct().all()}

        untagged = [r for r in text_reviews if r["review_id"] not in tagged_ids]
        if not untagged:
            logger.info(f"所有 {len(text_reviews)} 条口碑已有标签，跳过 LLM 提取")
            return 0

        logger.info(f"启动 LLM 增量标签提取: {len(untagged)}/{len(text_reviews)} 条无标签口碑")

        try:
            from src.nlp.tagger import get_tagger
            tagger = await get_tagger()
        except Exception as e:
            logger.error(f"获取 tagger 失败: {e}")
            return 0

        CHUNK_SIZE = 30
        saved = 0
        for i in range(0, len(untagged), CHUNK_SIZE):
            chunk = untagged[i:i + CHUNK_SIZE]
            chunk_end = min(i + CHUNK_SIZE, len(untagged))
            try:
                llm_results = await tagger.batch_extract(
                    chunk, concurrency=3, progress_callback=progress_callback
                )
            except Exception as e:
                logger.error(f"chunk {i}-{chunk_end} LLM 提取失败: {e}")
                continue

            # Save this chunk's results immediately
            try:
                with session_scope() as session:
                    chunk_saved = _save_chunk_tags(session, model_id, chunk, llm_results)
            except Exception as e:
                logger.error(f"chunk {i}-{chunk_end} 保存失败: {e}")
                continue

            saved += chunk_saved
            logger.info(f"chunk {i}-{chunk_end}: 保存 {chunk_saved} 条口碑标签 (累计 {saved})")

        logger.info(f"LLM 标签提取完成: {saved} 条口碑补充了标签")
        return saved
