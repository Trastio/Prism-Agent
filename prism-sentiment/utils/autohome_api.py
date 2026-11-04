"""汽车之家内部 API 客户端

直接调用汽车之家站内的 JSON 接口和页面嵌入数据，纯 httpx，无 Playwright。
核心数据源：
- 品牌字母索引页: /grade/carhtml/{letter}.html — 品牌+车系完整列表
- 车系配置页嵌入 JSON: /config/series/{id}.html — config/option/bag/color/innerColor/dealerPrices/saleSpecs/specIDs
- 口碑 API: koubeiipv6.app.autohome.com.cn — 口碑列表+车系维度均分+版本分布
- 车型配置接口: /ashx/car/GetConfigNew.ashx — 结构化 JSON
- 资讯接口: /ashx/AjaxGetNewsList.ashx — 车型资讯文章
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Optional

import httpx
import os

logger = logging.getLogger(__name__)

_BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.autohome.com.cn/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_BRAND_CACHE: dict[str, list[dict]] = {}
_BRAND_CACHE_TIME: float = 0.0
_BRAND_CACHE_TTL = 3600 * 6

_SERIES_INDEX: dict[str, dict] = {}
_SERIES_INDEX_TIME: float = 0.0
_SERIES_INDEX_TTL = 3600 * 6
# 磁盘缓存：进程崩/重载后内存缓存丢失，磁盘索引保留，避免每次 suggest 都重建 26 字母页
_INDEX_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.cache', 'autohome_series_index.json')

_series_detail_cache: dict[str, dict] = {}
_series_detail_cache_time: float = 0.0
_series_detail_cache_ttl = 3600 * 2

_series_summary_cache: dict[str, dict] = {}
_series_summary_cache_time: float = 0.0
_series_summary_cache_ttl = 3600 * 4

KAOUBEI_API = "https://koubeiipv6.app.autohome.com.cn/pc/series/list"


class AutohomeAPI:
    """汽车之家内部 API 异步客户端（纯 httpx）"""

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=_BASE_HEADERS,
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _get_text(self, url: str, retries: int = 2) -> str:
        client = await self._get_client()
        for attempt in range(retries):
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.text
                logger.warning(f"GET {url} 返回 {resp.status_code}, 尝试 {attempt + 1}/{retries}")
            except httpx.HTTPError as e:
                logger.warning(f"GET {url} 失败: {e}, 尝试 {attempt + 1}/{retries}")
            if attempt < retries - 1:
                await asyncio.sleep(1.0 * (attempt + 1))
        return ""

    async def _get_json(self, url: str, params: dict | None = None,
                        retries: int = 2) -> dict | None:
        client = await self._get_client()
        for attempt in range(retries):
            try:
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except json.JSONDecodeError:
                        return {"_raw_text": resp.text}
                logger.warning(f"API {url} 返回 {resp.status_code}, 尝试 {attempt + 1}/{retries}")
            except httpx.HTTPError as e:
                logger.warning(f"API {url} 请求失败: {e}, 尝试 {attempt + 1}/{retries}")
            if attempt < retries - 1:
                await asyncio.sleep(1.0 * (attempt + 1))
        return None

    # ---- 品牌与车系列表 ----

    async def get_brand_list(self, use_cache: bool = True) -> list[dict]:
        """获取所有品牌列表（从字母索引页解析）"""
        global _BRAND_CACHE, _BRAND_CACHE_TIME
        if use_cache and _BRAND_CACHE and (time.time() - _BRAND_CACHE_TIME) < _BRAND_CACHE_TTL:
            all_brands = []
            for brands in _BRAND_CACHE.values():
                all_brands.extend(brands)
            return all_brands

        all_brands = []
        semaphore = asyncio.Semaphore(6)

        async def _fetch_brands(letter: str) -> list[dict]:
            async with semaphore:
                try:
                    return await self._fetch_brands_by_letter(letter)
                except Exception as e:
                    logger.warning(f"获取品牌字母 {letter} 失败: {e}")
                    return []

        tasks = [_fetch_brands(letter) for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
        results = await asyncio.gather(*tasks)

        for letter, brands in zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", results):
            if brands:
                _BRAND_CACHE[letter] = brands
                all_brands.extend(brands)

        _BRAND_CACHE_TIME = time.time()
        return all_brands

    async def _fetch_brands_by_letter(self, letter: str) -> list[dict]:
        url = f"https://www.autohome.com.cn/grade/carhtml/{letter}.html"
        html = await self._get_text(url)
        if not html:
            return []

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        brands = []
        for dl in soup.select("dl"):
            dt = dl.select_one("dt")
            if not dt:
                continue
            name_el = dt.select_one("div a")
            if not name_el:
                name_el = dt.select_one("a")
            if not name_el:
                continue
            name = name_el.text.strip()
            if not name:
                continue
            href = name_el.get("href", "")
            brand_id_match = re.search(r'brand-(\d+)', href)
            dl_id = dl.get("id", "")
            brand_id = brand_id_match.group(1) if brand_id_match else dl_id
            if not brand_id:
                continue
            brands.append({
                "id": brand_id,
                "name": name,
                "letter": letter,
            })
        return brands

    async def build_series_index(self, use_cache: bool = True) -> dict[str, dict]:
        """构建车系索引：从品牌页提取所有车系的 ID、名称、品牌、指导价"""
        global _SERIES_INDEX, _SERIES_INDEX_TIME
        # 1. 内存缓存
        if use_cache and _SERIES_INDEX and (time.time() - _SERIES_INDEX_TIME) < _SERIES_INDEX_TTL:
            return _SERIES_INDEX
        # 2. 磁盘缓存（进程崩/重载后内存丢，磁盘索引保留，秒级载入）
        if use_cache and os.path.exists(_INDEX_CACHE_FILE):
            try:
                mtime = os.path.getmtime(_INDEX_CACHE_FILE)
                if time.time() - mtime < _SERIES_INDEX_TTL:
                    with open(_INDEX_CACHE_FILE, 'r', encoding='utf-8') as f:
                        _SERIES_INDEX = json.load(f)
                    _SERIES_INDEX_TIME = time.time()
                    logger.info(f"车系索引从磁盘缓存载入，共 {len(_SERIES_INDEX)} 个车系")
                    return _SERIES_INDEX
            except Exception as e:
                logger.warning(f"读磁盘索引缓存失败: {e}")

        index = {}
        semaphore = asyncio.Semaphore(6)

        async def _fetch_with_semaphore(letter: str) -> list[dict]:
            async with semaphore:
                try:
                    return await self._fetch_series_by_letter(letter)
                except Exception as e:
                    logger.warning(f"构建车系索引字母 {letter} 失败: {e}")
                    return []

        tasks = [_fetch_with_semaphore(letter) for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
        results = await asyncio.gather(*tasks)

        for series_list in results:
            for s in series_list:
                index[s["series_id"]] = s

        _SERIES_INDEX = index
        _SERIES_INDEX_TIME = time.time()
        # 写磁盘缓存
        try:
            os.makedirs(os.path.dirname(_INDEX_CACHE_FILE), exist_ok=True)
            with open(_INDEX_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(index, f, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"写磁盘索引缓存失败: {e}")
        logger.info(f"车系索引构建完成，共 {len(index)} 个车系")
        return index

    async def _fetch_series_by_letter(self, letter: str) -> list[dict]:
        url = f"https://www.autohome.com.cn/grade/carhtml/{letter}.html"
        html = await self._get_text(url)
        if not html:
            return []

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        results = []

        current_brand = ""
        current_brand_id = ""
        for dl in soup.select("dl"):
            dt = dl.select_one("dt")
            if dt:
                name_el = dt.select_one("div a") or dt.select_one("a")
                current_brand = name_el.text.strip() if name_el else ""
                href = name_el.get("href", "") if name_el else ""
                brand_id_match = re.search(r'brand-(\d+)', href)
                current_brand_id = brand_id_match.group(1) if brand_id_match else dl.get("id", "")

            for li in dl.select("li[id^='s']"):
                li_id = li.get("id", "")
                series_id = li_id[1:] if li_id.startswith("s") else ""
                if not series_id:
                    continue
                h4 = li.select_one("h4 a")
                name = h4.text.strip() if h4 else ""
                if not name:
                    continue

                price = ""
                price_match = re.search(r'指导价[：:]\s*([\d.\-]+万?|暂无)', li.get_text())
                if price_match:
                    price = price_match.group(1).strip()
                    if price == "暂无":
                        price = ""

                level = ""
                level_el = li.select_one("a[href*='level_']")
                if level_el:
                    level = level_el.text.strip()
                if not level:
                    level_match = re.search(r'(\w+SUV|\w+MPV|微型车|小型车|紧凑型车|中型车|中大型车|大型车|跑车|皮卡|微卡|轻客|微面)', li.get_text())
                    if level_match:
                        level = level_match.group(1)

                results.append({
                    "series_id": series_id,
                    "name": name,
                    "brand_name": current_brand,
                    "brand_id": current_brand_id,
                    "price_range": price,
                    "level": level,
                    "letter": letter,
                })

        return results

    # ---- 搜索 ----

    async def search_series(self, keyword: str, limit: int = 20,
                            price_min: float = 0, price_max: float = 0,
                            level: str = "", energy: str = "") -> list[dict]:
        """按关键词搜索车系，支持价格区间和级别过滤"""
        keyword = keyword.strip()
        if not keyword and not price_min and not price_max and not level and not energy:
            return []

        index = await self.build_series_index()
        results = []
        seen = set()

        def _normalize(s: str) -> str:
            return re.sub(r'\s+', '', s).lower()

        keyword_norm = _normalize(keyword) if keyword else ""

        exact_matches = []
        contains_matches = []
        fuzzy_matches = []
        brand_matches = []
        price_level_matches = []

        for sid, s in index.items():
            name = s["name"]
            brand = s.get("brand_name", "")
            price_range = s.get("price_range", "")
            s_level = s.get("level", "")

            in_price = True
            if price_min > 0 or price_max > 0:
                in_price = self._check_price_range(price_range, price_min, price_max)

            in_level = True
            if level:
                level_lower = level.lower()
                s_level_lower = s_level.lower()
                name_lower = name.lower()
                level_map = {
                    "suv": ["suv"],
                    "轿车": ["轿车", "三厢", "两厢"],
                    "mpv": ["mpv"],
                    "跑车": ["跑车"],
                    "皮卡": ["皮卡"],
                    "微面": ["微面"],
                    "微卡": ["微卡"],
                    "轻客": ["轻客"],
                }
                matched_levels = level_map.get(level_lower, [level_lower])
                in_level = any(lv in s_level_lower or lv in name_lower for lv in matched_levels)

            in_energy = True
            if energy:
                energy_lower = energy.lower()
                name_lower = name.lower()
                energy_map = {
                    "纯电": ["纯电", "纯电动"],
                    "纯电动": ["纯电", "纯电动"],
                    "插电混动": ["插电混动", "插混"],
                    "插混": ["插电混动", "插混"],
                    "增程": ["增程"],
                    "混动": ["混动", "插混", "增程"],
                    "燃油": ["燃油", "汽油", "柴油"],
                }
                matched_energies = energy_map.get(energy_lower, [energy_lower])
                in_energy = any(en in name_lower for en in matched_energies)

            if keyword:
                name_norm = _normalize(name)
                brand_name_norm = _normalize(brand + name)
                if keyword == name or keyword == brand + name:
                    exact_matches.append(s)
                elif keyword in name:
                    contains_matches.append(s)
                elif keyword_norm in name_norm or keyword_norm in brand_name_norm:
                    fuzzy_matches.append(s)
                elif keyword in brand:
                    brand_matches.append(s)
            else:
                if in_price and in_level and in_energy:
                    price_level_matches.append(s)

        candidates = exact_matches + contains_matches + fuzzy_matches + brand_matches if keyword else price_level_matches

        if keyword and (price_min > 0 or price_max > 0 or level or energy):
            filtered = []
            for s in candidates:
                price_range = s.get("price_range", "")
                s_level = s.get("level", "")
                name = s.get("name", "")

                in_price = True
                if price_min > 0 or price_max > 0:
                    in_price = self._check_price_range(price_range, price_min, price_max)

                in_level = True
                if level:
                    level_lower = level.lower()
                    level_map = {
                        "suv": ["suv"],
                        "轿车": ["轿车", "三厢", "两厢"],
                        "mpv": ["mpv"],
                    }
                    matched_levels = level_map.get(level_lower, [level_lower])
                    in_level = any(lv in s_level.lower() or lv in name.lower() for lv in matched_levels)

                in_energy = True
                if energy:
                    energy_lower = energy.lower()
                    energy_map = {
                        "纯电": ["纯电", "纯电动"],
                        "纯电动": ["纯电", "纯电动"],
                        "插电混动": ["插电混动", "插混"],
                        "增程": ["增程"],
                        "混动": ["混动", "插混", "增程"],
                    }
                    matched_energies = energy_map.get(energy_lower, [energy_lower])
                    in_energy = any(en in name.lower() for en in matched_energies)

                if in_price and in_level and in_energy:
                    filtered.append(s)

            if filtered:
                candidates = filtered

        for s in candidates:
            if s["series_id"] not in seen:
                seen.add(s["series_id"])
                results.append({
                    "series_id": s["series_id"],
                    "name": s["name"],
                    "brand_name": s.get("brand_name", ""),
                    "price_range": s.get("price_range", ""),
                    "level": s.get("level", ""),
                    "source": "autohome_api",
                })
            if len(results) >= limit:
                break

        return results

    @staticmethod
    def _check_price_range(price_range: str, price_min: float = 0, price_max: float = 0) -> bool:
        if not price_range:
            return True
        nums = re.findall(r'[\d.]+', price_range)
        if not nums:
            return True
        low = float(nums[0])
        high = float(nums[-1]) if len(nums) > 1 else low
        if price_min > 0 and high < price_min:
            return False
        if price_max > 0 and low > price_max:
            return False
        return True

    # ---- 车系详情与配置 ----

    @staticmethod
    def _clean_anti_scraping(text: str) -> str:
        if not isinstance(text, str):
            return text
        cleaned = re.sub(r"<span\s+class='hs_kw\d+_\w+'></span>", "", text)
        cleaned = re.sub(r"&nbsp;", " ", cleaned)
        return cleaned.strip()

    # 汽车之家配置字段名反爬补全：关键字藏在空 span 里被丢弃，按 (类目, 残缺名) 还原
    _FIELD_NAME_RESTORE = {
        # 基本参数
        ("基本参数", "车型"): "车型名称",
        ("基本参数", "厂"): "厂商指导价(厂商)",  # 厂商
        ("基本参数", "厂()"): "厂商(厂商)",
        ("基本参数", "级别"): "级别",
        ("基本参数", "上市"): "上市时间",
        ("基本参数", "整车"): "整车质保",
        ("基本参数", "(kg)"): "整备质量(kg)",
        ("基本参数", "首任车主政策"): "首任车主质保政策",
        # 车身（6个连续 (mm) = 长/宽/高/轴距/前轮距/后轮距）
        ("车身", "(mm)"): "长×宽×高(mm)",  # 首个；其余由顺序补，见 _restore_field_name
        ("车身", "(个)"): "油箱容积(个)",
        ("车身", "后备厢(L)"): "后备厢容积(L)",
        ("车身", "阻系数(Cd)"): "风阻系数(Cd)",
        # 电池/充电
        ("电池/充电", "功能"): "快充功能",
        ("电池/充电", "电池(小时)"): "快充电量(小时)",
        ("电池/充电", "电池范围(%)"): "快充范围(%)",
        ("电池/充电", "百公里耗(kWh/100km)"): "百公里耗电量(kWh/100km)",
        ("电池/充电", "位置"): "电池位置",
        ("电池/充电", "对外放电功率(kW)"): "对外放电功率(kW)",
        # 变速箱
        ("变速箱", "简称"): "变速箱简称",
        # 底盘转向（前/后悬架 + 转向类型）
        ("底盘转向", "前类型"): "前悬架类型",
        ("底盘转向", "类型"): "后悬架类型",
        # 车轮制动
        ("车轮制动", "类型"): "制动类型",
        ("车轮制动", "类型2"): "前制动类型",
        ("车轮制动", "类型3"): "后制动类型",
        ("车轮制动", "驻车类型"): "前驻车类型",
        ("车轮制动", "驻车类型2"): "后驻车类型",
        # 被动安全（气囊）
        ("被动安全", "主/副驾驶座安全"): "主/副驾驶座安全气囊",
        ("被动安全", "/侧"): "前排侧气囊",
        ("被动安全", "/头部(气帘)"): "前后排头部气囊(气帘)",
        # 驾驶硬件
        ("驾驶硬件", "/后雷达"): "前/后雷达",
        ("驾驶硬件", "数量"): "超声波雷达数量",
        ("驾驶硬件", "辅助"): "驾驶辅助",
        # 驾驶功能
        ("驾驶功能", "辅助"): "辅助驾驶",
        # 外观
        ("外观/防盗", "轮圈"): "铝合金轮圈",
        # 灯光
        ("车外灯光", "光源"): "近远灯光源",
        # 天窗/玻璃
        ("天窗/玻璃", "/后电动车窗"): "前/后电动车窗",
        # 互联/智能化
        ("互联/智能化", "/车载"): "导航/车载",
        ("互联/智能化", "手机互联/映射"): "手机互联/映射",
        ("互联/智能化", "4G/5G网络"): "4G/5G网络",
        # 车内充电
        ("车内充电", "多媒体/充电"): "多媒体/充电接口",
        ("车内充电", "USB/Type-C数量"): "USB/Type-C接口数量",
        ("车内充电", "USB/Type-C最大充电功率"): "USB/Type-C最大充电功率",
        # 座椅
        ("座椅配置", "座椅"): "座椅材质",
        ("座椅配置", "主/副驾驶座电动"): "主/副驾驶座电动调节",
        ("座椅配置", "/后扶手"): "前/后扶手",
        ("座椅配置", "杯架"): "前/后杯架",
        # 音响
        ("音响/车内灯光", "品牌"): "音响品牌",
        ("音响/车内灯光", "数量"): "扬声器数量",
        # 空调
        ("空调/冰箱", "空调"): "空调温度控制方式",
    }

    # (类目, 残缺名, 类目内序号) -> 完整名。序号 0-based，同类目内重复残缺名按出现顺序。
    _FIELD_NAME_BY_INDEX = {
        # 车身 6 个 (mm)：长/宽/高/轴距/前轮距/后轮距
        ("车身", "(mm)", 0): "长度(mm)",
        ("车身", "(mm)", 1): "宽度(mm)",
        ("车身", "(mm)", 2): "高度(mm)",
        ("车身", "(mm)", 3): "轴距(mm)",
        ("车身", "(mm)", 4): "前轮距(mm)",
        ("车身", "(mm)", 5): "后轮距(mm)",
        # 车轮制动：前/后制动类型、前/后驻车类型、前/后轮胎规格
        ("车轮制动", "类型", 0): "前制动类型",
        ("车轮制动", "类型", 1): "后制动类型",
        ("车轮制动", "制动类型", 0): "驻车制动类型",
        ("车轮制动", "", 0): "前轮胎规格",
        ("车轮制动", "", 1): "后轮胎规格",
        ("车轮制动", "", 2): "备胎规格",
    }

    @classmethod
    def _restore_field_name(cls, name: str, category: str = "", index: int = 0) -> str:
        """补全被反爬打碎的配置字段名。index 为该残缺名在同类目内第几次出现（0-based）。"""
        if not name:
            return name
        # 1) 先查序号表（处理同类目重复残缺名）
        idx_key = (category, name, index)
        if idx_key in cls._FIELD_NAME_BY_INDEX:
            return cls._FIELD_NAME_BY_INDEX[idx_key]
        # 2) 再查 (类目, 名) 表
        key = (category, name)
        if key in cls._FIELD_NAME_RESTORE:
            return cls._FIELD_NAME_RESTORE[key]
        return name

    @staticmethod
    def _extract_var_json(html: str, var_name: str) -> dict | list | None:
        """从 HTML 中提取 var xxx = {...}; 或 var xxx = [...]; 格式的嵌入 JSON"""
        pattern = rf'var\s+{var_name}\s*=\s*'
        match = re.search(pattern, html)
        if not match:
            return None
        start = match.end()
        if start >= len(html):
            return None

        first_char = html[start]
        if first_char == '{':
            open_ch, close_ch = '{', '}'
        elif first_char == '[':
            open_ch, close_ch = '[', ']'
        elif html[start:start + 4] == 'null':
            return None
        elif html[start] == '"':
            end = html.index('"', start + 1) if '"' in html[start + 1:] else -1
            if end > 0:
                return html[start + 1:end]
            return None
        else:
            return None

        depth = 0
        in_string = False
        escape = False
        string_char = ""
        for i in range(start, len(html)):
            c = html[i]
            if escape:
                escape = False
                continue
            if c == '\\':
                escape = True
                continue
            if in_string:
                if c == string_char:
                    in_string = False
                continue
            if c in ('"', "'"):
                in_string = True
                string_char = c
                continue
            if c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    json_str = html[start:i + 1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        return None
        return None

    async def get_series_info(self, series_id: str) -> dict:
        """获取车系详细信息：提取配置页所有嵌入变量"""
        global _series_detail_cache, _series_detail_cache_time
        if (time.time() - _series_detail_cache_time) < _series_detail_cache_ttl and series_id in _series_detail_cache:
            return _series_detail_cache[series_id]

        url = f"https://car.autohome.com.cn/config/series/{series_id}.html"
        html = await self._get_text(url)
        if not html:
            return {"error": "无法获取车系信息", "series_id": series_id}

        info = {"series_id": series_id, "url": url}

        for var_name in ["config", "option", "saleSpecs", "specIDs",
                         "dealerPrices", "color", "innerColor", "bag"]:
            data = self._extract_var_json(html, var_name)
            if data is not None:
                info[f"{var_name}_data"] = data

        name_match = re.search(r'<title>(.*?)</title>', html)
        if name_match:
            title = name_match.group(1)
            parts = title.split("|")
            if len(parts) >= 2:
                info["name"] = parts[1].strip()
            else:
                clean_title = re.sub(r'[_|]汽车之家.*$', '', title).strip()
                if clean_title:
                    info["name"] = clean_title

        if not info.get("name"):
            option_data = info.get("option_data", {})
            option_result = option_data.get("result", {}) if isinstance(option_data, dict) else {}
            speclist = option_result.get("speclist", []) if isinstance(option_result, dict) else []
            if speclist:
                first_spec = speclist[0]
                info["name"] = self._clean_anti_scraping(first_spec.get("specname", first_spec.get("name", "")))

        if not info.get("name"):
            config_data = info.get("config_data", {})
            config_result = config_data.get("result", {}) if isinstance(config_data, dict) else {}
            param_items = config_result.get("paramtypeitems", []) if isinstance(config_result, dict) else []
            if param_items:
                first_item = param_items[0].get("paramitems", []) if isinstance(param_items[0], dict) else []
                if first_item:
                    name_raw = first_item[0].get("name", "")
                    info["name"] = self._clean_anti_scraping(name_raw)

        if not info.get("name"):
            info["name"] = f"series_{series_id}"

        if "level" not in info:
            from bs4 import BeautifulSoup as _BS
            soup = _BS(html, "html.parser")
            breadcrumb = soup.select_one(".breadnav, .breadcrumb, .path")
            if breadcrumb:
                bc_text = breadcrumb.get_text()
                level_match = re.search(
                    r'(微型车|小型车|紧凑型车|中型车|中大型车|大型车|'
                    r'小型SUV|紧凑型SUV|中型SUV|中大型SUV|大型SUV|'
                    r'小型MPV|紧凑型MPV|中型MPV|中大型MPV|大型MPV|'
                    r'跑车|皮卡|微卡|轻客|微面)',
                    bc_text)
                if level_match:
                    info["level"] = level_match.group(1)
            if "level" not in info:
                level_match = re.search(
                    r'(微型车|小型车|紧凑型车|中型车|中大型车|大型车|'
                    r'小型SUV|紧凑型SUV|中型SUV|中大型SUV|大型SUV|'
                    r'\w+MPV|跑车|皮卡|微卡|轻客|微面)',
                    html)
                if level_match:
                    info["level"] = level_match.group(1)

        _series_detail_cache[series_id] = info
        _series_detail_cache_time = time.time()
        return info

    async def get_series_specs(self, series_id: str) -> list[dict]:
        """获取车系下所有在售车型（版本）列表"""
        info = await self.get_series_info(series_id)
        specs = []
        seen_ids = set()

        config_data = info.get("config_data", {})
        config_result = config_data.get("result", {}) if isinstance(config_data, dict) else {}
        param_type_items = config_result.get("paramtypeitems", []) if isinstance(config_result, dict) else []

        name_map = {}
        price_map = {}
        if param_type_items:
            first_type = param_type_items[0]
            param_items = first_type.get("paramitems", []) if isinstance(first_type, dict) else []
            if len(param_items) >= 1:
                for vi in param_items[0].get("valueitems", []):
                    spec_id = str(vi.get("specid", ""))
                    name = self._clean_anti_scraping(vi.get("value", ""))
                    if spec_id:
                        name_map[spec_id] = name
            if len(param_items) >= 2:
                for vi in param_items[1].get("valueitems", []):
                    spec_id = str(vi.get("specid", ""))
                    price = self._clean_anti_scraping(vi.get("value", ""))
                    if spec_id:
                        price_map[spec_id] = price

        for spec_id, name in name_map.items():
            if spec_id not in seen_ids:
                seen_ids.add(spec_id)
                specs.append({
                    "spec_id": spec_id,
                    "name": name,
                    "price": price_map.get(spec_id, ""),
                    "series_id": series_id,
                })

        option_data = info.get("option_data", {})
        option_result = option_data.get("result", {}) if isinstance(option_data, dict) else {}
        for item in option_result.get("speclist", []) if isinstance(option_result, dict) else []:
            spec_id = str(item.get("specid", ""))
            if spec_id and spec_id not in seen_ids:
                seen_ids.add(spec_id)
                specs.append({
                    "spec_id": spec_id,
                    "name": name_map.get(spec_id, f"spec_{spec_id}"),
                    "price": price_map.get(spec_id, ""),
                    "series_id": series_id,
                })

        return specs

    async def get_config_by_specid(self, spec_id: str, config_type: str = "base") -> dict:
        """获取车型配置参数（结构化 JSON）"""
        url = "https://www.autohome.com.cn/ashx/car/GetConfigNew.ashx"
        data = await self._get_json(url, params={"type": config_type, "specid": spec_id})
        if not data:
            return {"error": f"无法获取{config_type}配置", "spec_id": spec_id}
        return {"spec_id": spec_id, "config_type": config_type, "data": data}

    # ---- 车系汇总（口碑 API 页级数据） ----

    async def get_series_summary(self, series_id: str) -> dict:
        """获取车系口碑汇总：维度均分、版本分布、价格、级别等

        利用口碑 API 首页返回的页级数据，包含丰富的汇总信息。
        """
        global _series_summary_cache, _series_summary_cache_time
        if (time.time() - _series_summary_cache_time) < _series_summary_cache_ttl and series_id in _series_summary_cache:
            return _series_summary_cache[series_id]

        url = (f"{KAOUBEI_API}?pm=3&seriesId={series_id}&pageIndex=1&pageSize=1"
               f"&yearid=0&ge=0&seriesSummaryKey=0&order=0")
        text = await self._get_text(url)
        if not text:
            return {"error": "无法获取车系汇总", "series_id": series_id}

        match = re.search(r'<pre>(.*?)</pre>', text, re.DOTALL)
        json_str = match.group(1) if match else text

        try:
            data = json.loads(json_str)
            result = data.get("result", {})
        except (json.JSONDecodeError, AttributeError):
            return {"error": "口碑API解析失败", "series_id": series_id}

        dimension_scores = []
        for item in result.get("seriesScoreList", []):
            dimension_scores.append({
                "name": item.get("typeName", ""),
                "score": item.get("score", 0),
                "rank": item.get("rank", 0),
            })

        spec_groups = []
        for group in result.get("specgroup", []):
            spec_groups.append({
                "name": group.get("groupname", ""),
                "year": group.get("year", 0),
                "year_id": group.get("yearId", 0),
                "count": group.get("count", 0),
                "onsell": group.get("onsell", 0),
                "specs": [
                    {"spec_id": str(s.get("specid", "")), "name": s.get("specname", ""),
                     "koubei_count": s.get("koubeicount", 0)}
                    for s in group.get("speclist", [])
                ],
            })

        summary = {
            "series_id": series_id,
            "series_name": result.get("seriesname", ""),
            "brand_name": result.get("brandName", ""),
            "brand_id": str(result.get("brandId", "")),
            "level_name": result.get("levelname", ""),
            "level_id": str(result.get("levelid", "")),
            "level_rank": result.get("levelrank", 0),
            "level_series_count": result.get("levelseriescount", 0),
            "price_range": result.get("pricerange", ""),
            "min_price": result.get("minPrice", 0),
            "max_price": result.get("maxPrice", 0),
            "average_score": float(result.get("average", 0)) if result.get("average") else None,
            "dimension_scores": dimension_scores,
            "review_count": result.get("rowcount", 0),
            "onsell_review_count": result.get("onsellrowcount", 0),
            "pph": result.get("newCarPPH", 0),
            "cmp_scores": [
                {
                    "series_id": str(item.get("seriesId", "")),
                    "name": item.get("seriesName", ""),
                    "score": item.get("score", ""),
                    "pph": item.get("newCarPPH", 0),
                    "best_dimension": item.get("maxItemName", ""),
                    "best_score": item.get("maxItemScore", ""),
                }
                for item in result.get("cmpSeriesScore", [])
            ],
            "cmp_pph": [
                {
                    "series_id": str(item.get("seriesId", "")),
                    "name": item.get("seriesName", ""),
                    "pph": item.get("newCarPPH", 0),
                    "sample_count": item.get("newCarPPHUserCount", 0),
                }
                for item in result.get("cmpSeriesPPH", [])
            ],
            "consumption": result.get("consumption", ""),
            "consumption_battery": result.get("consumption_battery", ""),
            "powertype": result.get("powertype", 0),
            "spec_groups": spec_groups,
            "data_source": "汽车之家口碑API",
        }

        _series_summary_cache[series_id] = summary
        _series_summary_cache_time = time.time()
        return summary

    # ---- 口碑采集（httpx 直接请求） ----

    async def fetch_koubei_page(self, series_id: str, page_index: int = 1,
                                page_size: int = 20, yearid: int = 0) -> dict | None:
        """请求口碑 API 单页，返回 result dict 或 None"""
        url = (f"{KAOUBEI_API}?pm=3&seriesId={series_id}&pageIndex={page_index}"
               f"&pageSize={page_size}&yearid={yearid}&ge=0&seriesSummaryKey=0&order=0")
        text = await self._get_text(url)
        if not text:
            return None

        match = re.search(r'<pre>(.*?)</pre>', text, re.DOTALL)
        json_str = match.group(1) if match else text

        try:
            data = json.loads(json_str)
            return data.get("result", {})
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning(f"口碑API解析失败: {e}")
            return None

    @staticmethod
    def parse_koubei_item(item: dict, series_display_name: str = "") -> dict:
        """完整解析口碑 API 单条数据，提取所有有价值字段"""
        best_text = ""
        worst_text = ""
        dimension_reviews = {}

        for c in item.get("contents", []):
            name = c.get("structuredname", "")
            content = c.get("content", "")
            if "满意" in name and "不满意" not in name:
                best_text = content
            elif "不满意" in name:
                worst_text = content
            elif content.strip():
                dimension_reviews[name] = content

        dimensions = {}
        for s in item.get("scoreList", []):
            name = s.get("name", "")
            value = s.get("value", "")
            try:
                dimensions[name] = int(value)
            except (ValueError, TypeError):
                pass

        koubei_id = item.get("Koubeiid") or item.get("showId", "")
        review_id = f"k_{koubei_id}" if koubei_id else f"k_api_{item.get('userid', 0)}_{item.get('posttime', '')}"

        series_name = item.get("seriesname", "")
        spec_name = item.get("specname", "")
        if series_name and series_name.lower() != "none":
            model_full_name = f"{series_name} {spec_name}".strip()
        elif series_display_name:
            model_full_name = f"{series_display_name} {spec_name}".strip()
        else:
            model_full_name = spec_name

        purposes = [p.get("name", "") for p in item.get("purposes", []) if p.get("name")]

        exinfo = {}
        for ex in item.get("exinfolist", []):
            if ex.get("name") and ex.get("value"):
                exinfo[ex["name"]] = ex["value"]

        return {
            "review_id": review_id,
            "owner_id": str(item.get("username", "")),
            "model_full_name": model_full_name,
            "spec_name": spec_name,
            "spec_id": str(item.get("specid", "")) if item.get("specid") else None,
            "purchase_date": item.get("boughtDate") or item.get("posttime", ""),
            "best_review_text": best_text,
            "worst_review_text": worst_text,
            "score": item.get("averageScore"),
            "dimensions": dimensions,
            "buy_price": item.get("buyprice", ""),
            "fuel_consumption": item.get("actual_battery_consumption", "") or item.get("actual_oil_consumption", ""),
            "mileage": item.get("distance", ""),
            "city": item.get("buyplace", "") or item.get("location", ""),
            "use_purposes": purposes,
            "dimension_reviews": dimension_reviews,
            "exinfo": exinfo,
            "source": "api",
            "_raw_item": item,
        }

    # ---- 颜色信息 ----

    async def get_series_colors(self, series_id: str) -> dict:
        """获取车系外观颜色和内饰颜色"""
        info = await self.get_series_info(series_id)

        colors = []
        color_data = info.get("color_data", {})
        if isinstance(color_data, dict):
            result = color_data.get("result", {})
            if isinstance(result, dict):
                for spec_item in result.get("specitems", []):
                    for c in spec_item.get("coloritems", []):
                        colors.append({
                            "name": c.get("name", ""),
                            "pic_num": c.get("picnum", 0),
                            "price": c.get("price", 0),
                        })

        inner_colors = []
        inner_color_data = info.get("innerColor_data", {})
        if isinstance(inner_color_data, dict):
            result = inner_color_data.get("result", {})
            if isinstance(result, dict):
                for spec_item in result.get("specitems", []):
                    for c in spec_item.get("coloritems", []):
                        inner_colors.append({
                            "name": c.get("name", ""),
                            "pic_num": c.get("picnum", 0),
                        })

        return {
            "series_id": series_id,
            "exterior_colors": colors,
            "interior_colors": inner_colors,
            "data_source": "汽车之家配置页",
        }

    # ---- 便捷方法 ----

    async def get_model_detail(self, series_id: str) -> dict:
        """获取车系核心信息摘要"""
        info = await self.get_series_info(series_id)
        if "error" in info and "config_data" not in info:
            return info

        detail = {
            "model_id": series_id,
            "name": info.get("name", ""),
            "url": info.get("url", f"https://www.autohome.com.cn/{series_id}/"),
        }

        config_data = info.get("config_data", {})
        config_result = config_data.get("result", {}) if isinstance(config_data, dict) else {}

        name_map = {}
        price_map = {}
        param_type_items = config_result.get("paramtypeitems", []) if isinstance(config_result, dict) else []
        if param_type_items:
            first_type = param_type_items[0]
            param_items = first_type.get("paramitems", []) if isinstance(first_type, dict) else []
            if len(param_items) >= 1:
                for vi in param_items[0].get("valueitems", []):
                    spec_id = str(vi.get("specid", ""))
                    name = self._clean_anti_scraping(vi.get("value", ""))
                    if spec_id:
                        name_map[spec_id] = name
            if len(param_items) >= 2:
                for vi in param_items[1].get("valueitems", []):
                    spec_id = str(vi.get("specid", ""))
                    price = self._clean_anti_scraping(vi.get("value", ""))
                    if spec_id:
                        price_map[spec_id] = price

        if price_map:
            prices = sorted(float(p) for p in price_map.values() if p and p.replace(".", "").isdigit())
            if prices:
                if len(prices) == 1:
                    detail["price_range"] = f"{prices[0]}万"
                else:
                    detail["price_range"] = f"{prices[0]}-{prices[-1]}万"

        for type_item in param_type_items:
            for param in type_item.get("paramitems", []) if isinstance(type_item, dict) else []:
                name_raw = param.get("name", "")
                name = self._clean_anti_scraping(name_raw)
                values = param.get("valueitems", [])
                if not values:
                    continue
                val = self._clean_anti_scraping(values[0].get("value", ""))
                if not val:
                    continue
                if "级别" in name_raw or "级别" in name:
                    detail["level"] = val
                elif "能源" in name_raw or "能源" in name:
                    detail["energy_type"] = val
                elif "厂商" in name_raw or "厂商" in name:
                    if "price_range" not in detail:
                        detail["manufacturer"] = val
                elif "长" in name_raw and "宽" in name_raw and "高" in name_raw:
                    detail["dimensions"] = val
                elif "轴距" in name_raw or "轴距" in name:
                    detail["wheelbase"] = val
                elif "发动机" in name_raw and ("型" in name_raw or "号" in name_raw):
                    detail["engine"] = val
                elif "最大马力" in name_raw or "最大马力" in name:
                    detail["max_power"] = val
                elif "变速箱" in name_raw or "变速箱" in name:
                    detail["transmission"] = val

        specs = await self.get_series_specs(series_id)
        detail["trim_count"] = len(specs)
        if specs:
            detail["trims"] = specs[:10]

        if "level" not in detail:
            if info.get("level"):
                detail["level"] = info["level"]

        summary = await self.get_series_summary(series_id)
        if "error" not in summary:
            detail["average_score"] = summary.get("average_score")
            detail["dimension_scores"] = summary.get("dimension_scores", [])
            detail["review_count"] = summary.get("review_count", 0)

        return detail

    async def get_full_config(self, series_id: str) -> dict:
        """获取车系完整配置参数"""
        info = await self.get_series_info(series_id)
        if "error" in info and "config_data" not in info:
            return info

        result = {
            "series_id": series_id,
            "url": f"https://car.autohome.com.cn/config/series/{series_id}.html",
            "categories": {},
        }

        config_data = info.get("config_data", {})
        config_result = config_data.get("result", {}) if isinstance(config_data, dict) else {}

        for type_item in config_result.get("paramtypeitems", []) if isinstance(config_result, dict) else []:
            cat_name = self._clean_anti_scraping(type_item.get("name", "基础参数"))
            params = {}
            _name_seen = {}
            for param in type_item.get("paramitems", []):
                _raw = self._clean_anti_scraping(param.get("name", ""))
                _idx = _name_seen.get(_raw, 0)
                _name_seen[_raw] = _idx + 1
                p_name = self._restore_field_name(_raw, cat_name, _idx)
                values = param.get("valueitems", [])
                if p_name and values:
                    if len(values) == 1:
                        params[p_name] = self._clean_anti_scraping(values[0].get("value", ""))
                    else:
                        spec_values = {}
                        for i, v in enumerate(values):
                            spec_id = str(v.get("specid", f"spec_{i}"))
                            spec_values[spec_id] = self._clean_anti_scraping(v.get("value", ""))
                        params[p_name] = spec_values
            if params:
                result["categories"][cat_name] = params

        option_data = info.get("option_data", {})
        option_result = option_data.get("result", {}) if isinstance(option_data, dict) else {}
        for type_item in option_result.get("configtypeitems", []) if isinstance(option_result, dict) else []:
            cat_name = self._clean_anti_scraping(type_item.get("name", "配置参数"))
            params = {}
            _name_seen = {}
            for config_item in type_item.get("configitems", []):
                _raw = self._clean_anti_scraping(config_item.get("name", ""))
                _idx = _name_seen.get(_raw, 0)
                _name_seen[_raw] = _idx + 1
                c_name = self._restore_field_name(_raw, cat_name, _idx)
                values = config_item.get("valueitems", [])
                if c_name and values:
                    if len(values) == 1:
                        params[c_name] = self._clean_anti_scraping(values[0].get("value", ""))
                    else:
                        spec_values = {}
                        for i, v in enumerate(values):
                            spec_id = str(v.get("specid", f"spec_{i}"))
                            spec_values[spec_id] = self._clean_anti_scraping(v.get("value", ""))
                        params[c_name] = spec_values
            if params:
                result["categories"][cat_name] = params

        if not result["categories"]:
            specs = await self.get_series_specs(series_id)
            if specs:
                spec_id = specs[0]["spec_id"]
                base = await self.get_config_by_specid(spec_id, "base")
                config = await self.get_config_by_specid(spec_id, "config")
                if "data" in base:
                    result["categories"]["基础参数"] = base["data"]
                if "data" in config:
                    result["categories"]["配置参数"] = config["data"]

        return result

    async def get_model_generations(self, series_id: str) -> dict:
        """获取车系年款/换代信息"""
        info = await self.get_series_info(series_id)
        if "error" in info and "config_data" not in info:
            return info

        specs = await self.get_series_specs(series_id)
        if not specs:
            return {"series_id": series_id, "generations": [], "count": 0}

        year_groups: dict[str, list[dict]] = {}
        for s in specs:
            name = s.get("name", "")
            year = "其他年款"
            year_match = re.search(r'(\d{4})款', name)
            if year_match:
                year = f"{year_match.group(1)}款"
            year_groups.setdefault(year, []).append({
                "spec_id": s.get("spec_id", ""),
                "name": name,
                "price": s.get("price", ""),
            })

        generations = []
        for year in sorted(year_groups.keys(), reverse=True):
            items = year_groups[year]
            prices = [s["price"] for s in items if s.get("price") and "万" in s["price"]]
            price_range = ""
            if prices:
                nums = []
                for p in prices:
                    found = re.findall(r'[\d.]+', p)
                    nums.extend(float(n) for n in found)
                if nums:
                    price_range = f"{min(nums)}-{max(nums)}万" if min(nums) != max(nums) else f"{min(nums)}万"
            generations.append({
                "year": year,
                "trim_count": len(items),
                "price_range": price_range,
                "trims": items,
            })

        model_name = info.get("name", series_id)
        return {
            "series_id": series_id,
            "model_name": model_name,
            "generations": generations,
            "total_trims": len(specs),
            "latest_year": generations[0]["year"] if generations else "",
            "data_source": f"汽车之家实时数据（{len(specs)}个版本，{len(generations)}个年款）",
        }

    async def get_similar_models(self, series_id: str, limit: int = 8) -> dict:
        """获取同级别竞品车型"""
        detail = await self.get_model_detail(series_id)
        if "error" in detail and "name" not in detail:
            return {"error": f"无法获取车型信息: {detail.get('error', '')}", "series_id": series_id}

        target_level = detail.get("level", "")
        target_energy = detail.get("energy_type", "")
        target_name = detail.get("name", "")
        price_str = detail.get("price_range", "")
        target_min_price = 0.0
        target_max_price = 999.0
        if price_str and price_str != "暂无":
            nums = re.findall(r'[\d.]+', price_str)
            if len(nums) >= 2:
                target_min_price = float(nums[0]) * 0.6
                target_max_price = float(nums[1]) * 1.4
            elif len(nums) == 1:
                target_min_price = float(nums[0]) * 0.6
                target_max_price = float(nums[0]) * 1.4

        index = await self.build_series_index()
        candidates = []
        for sid, s in index.items():
            if sid == series_id:
                continue
            score = 0
            s_price = s.get("price_range", "")
            s_level = s.get("level", "")
            s_min = 0.0
            s_max = 0.0
            if s_price:
                nums = re.findall(r'[\d.]+', s_price)
                if len(nums) >= 2:
                    s_min, s_max = float(nums[0]), float(nums[1])
                elif len(nums) == 1:
                    s_min = s_max = float(nums[0])
            if s_min > 0 and s_max > 0:
                if s_min >= target_min_price and s_max <= target_max_price:
                    score += 3
                elif s_min <= target_max_price and s_max >= target_min_price:
                    score += 1
            if target_level and s_level and target_level == s_level:
                score += 2
            if target_energy and s.get("energy_type", "") and target_energy == s.get("energy_type", ""):
                score += 1
            if score > 0:
                candidates.append((sid, s, score))

        candidates.sort(key=lambda x: x[2], reverse=True)

        top_candidates = candidates[:limit * 2]
        if target_level and len(top_candidates) > limit:
            verified = []
            sem = asyncio.Semaphore(6)

            async def _verify_one(sid, s, score):
                async with sem:
                    try:
                        d = await self.get_model_detail(sid)
                        if isinstance(d, dict):
                            s_level = d.get("level", "")
                            if s_level == target_level:
                                score += 5
                            elif target_level and s_level and (
                                ("SUV" in target_level and "SUV" in s_level) or
                                ("轿车" in target_level and "轿车" in s_level) or
                                ("MPV" in target_level and "MPV" in s_level)
                            ):
                                score += 3
                    except Exception:
                        pass
                return (sid, s, score)

            verified = await asyncio.gather(*[_verify_one(sid, s, score) for sid, s, score in top_candidates])
            verified = list(verified)
            verified.sort(key=lambda x: x[2], reverse=True)
            top_candidates = verified

        results = []
        seen = set()
        for sid, s, score in top_candidates:
            if sid in seen or len(results) >= limit:
                break
            seen.add(sid)
            results.append({
                "series_id": sid,
                "name": s.get("name", ""),
                "brand_name": s.get("brand_name", ""),
                "price_range": s.get("price_range", ""),
                "relevance": score,
            })

        return {
            "series_id": series_id,
            "model_name": target_name,
            "level": target_level,
            "energy_type": target_energy,
            "price_range": price_str,
            "similar_models": results,
            "count": len(results),
            "data_source": f"汽车之家车系索引（基于价格区间匹配，{len(results)}款竞品）",
        }

    async def search_news(self, series_id: str, keyword: str = "", page: int = 1,
                          page_size: int = 10) -> dict:
        """搜索车型相关资讯文章"""
        model_name = ""
        info = await self.get_series_info(series_id)
        if "name" in info:
            model_name = info["name"]

        search_kw = keyword.strip() if keyword.strip() else model_name
        if not search_kw:
            return {"articles": [], "count": 0, "series_id": series_id}

        try:
            url = "https://www.autohome.com.cn/ashx/AjaxGetNewsList.ashx"
            data = await self._get_json(url, params={
                "type": "1",
                "keyword": search_kw,
                "page": str(page),
                "pagesize": str(page_size),
            })
            if data and isinstance(data, dict):
                items = data.get("result", data.get("list", []))
                if isinstance(items, list):
                    articles = []
                    for item in items[:page_size]:
                        articles.append({
                            "title": item.get("title", ""),
                            "url": item.get("url", item.get("href", "")),
                            "date": item.get("pubdate", item.get("date", "")),
                            "summary": item.get("summary", item.get("description", ""))[:200],
                        })
                    if articles:
                        return {"articles": articles, "count": len(articles),
                                "series_id": series_id, "source": "autohome_news_api"}
        except Exception as e:
            logger.debug(f"资讯API失败: {e}")

        # 回退1：从车系首页 news 区块解析（AjaxGetNewsList.ashx 失效后）
        try:
            html = await self._get_text(f"https://www.autohome.com.cn/{series_id}/")
            if html:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                articles = []
                for a in soup.select("a[href]"):
                    href = a.get("href", "")
                    title = a.get_text(strip=True).lstrip("·").strip()
                    if ("/news/" in href or "/article/" in href) and title and len(title) > 5:
                        # 车系首页的资讯链接天然相关，不过滤关键词
                        articles.append({"title": title, "url": href,
                                         "date": "", "summary": ""})
                        if len(articles) >= page_size:
                            break
                if articles:
                    return {"articles": articles[:page_size], "count": len(articles[:page_size]),
                            "series_id": series_id, "source": "车系首页资讯区块"}
        except Exception as e:
            logger.debug(f"车系首页资讯解析失败: {e}")

        try:
            from src.search.engine import get_search_engine
            engine = get_search_engine()
            results = await engine.search(f"{search_kw} 汽车 资讯", num_results=page_size)
            articles = []
            for r in results:
                if r.title and len(r.title) > 4:
                    articles.append({
                        "title": r.title,
                        "url": r.url,
                        "date": "",
                        "summary": r.description[:200] if r.description else "",
                    })
            if articles:
                return {"articles": articles[:page_size], "count": len(articles[:page_size]),
                        "series_id": series_id, "source": "search_engine"}
        except Exception as e:
            logger.debug(f"搜索引擎降级失败: {e}")

        return {"articles": [], "count": 0, "series_id": series_id,
                "note": "资讯搜索暂不可用"}


_api_instance: AutohomeAPI | None = None
_api_lock = asyncio.Lock()


async def get_autohome_api() -> AutohomeAPI:
    global _api_instance
    async with _api_lock:
        if _api_instance is None:
            _api_instance = AutohomeAPI()
        return _api_instance


async def close_autohome_api():
    global _api_instance
    if _api_instance:
        await _api_instance.close()
        _api_instance = None


# ==== 待修复：销量 API 端点（2026-06 汽车之家迁移后失效）====
# 旧端点: car-web-api.autohome.com.cn/car/rank/getList?seriesId= — 返回"无数据"
# 新端点位于: 需从汽车之家 PC 端「销量频道」F12 抓包获取（可能带签名）
# 候选路径: car-nc.autohome.com.cn / api.sa.autohome.com.cn
#
# async def get_sales_data_v2(self, series_id: str, months: int = 6) -> dict:
#     """TODO: 逆向汽车之家2026新销量API后填充"""
#     pass
