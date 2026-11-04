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
        if use_cache and _SERIES_INDEX and (time.time() - _SERIES_INDEX_TIME) < _SERIES_INDEX_TTL:
            return _SERIES_INDEX

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

    # 字体加密 span → 明文字符映射缓存：{html: mapping}，单条以 html 文本为键。
    # get_series_info 抓到 html 后构建一次，下游所有 _clean_anti_scraping 调用复用。
    _kw_mapping_cache: dict[str, dict[str, str]] = {}

    @classmethod
    def _build_kw_mapping(cls, html: str) -> dict[str, str]:
        """从配置页 HTML 逆向提取之家字体加密 span 的明文映射。

        之家配置页用 ~1007 个空 ``<span class='hs_kw{N}_{suffix}'></span>`` 做反爬，
        真实字符由页面内 JS（3 个 IIFE script 块，每个对应一个 suffix）动态注入：
        ``$FillDicData$`` 拼接"字典字符串"、``$rulePosList$`` 给位置串、
        ``$InsertRuleRun$`` 用位置从字典 charAt 取字符填入 span。

        本方法纯 Python 复现该逻辑：解析每个 script 块里的混淆函数定义
        （var/function 多种变体，均退化为常量字符串或恒等函数），求值字典串与位置串，
        重建 {hs_kwN_suffix: 明文} 映射。
        """
        if not html:
            return {}
        cached = cls._kw_mapping_cache.get(html)
        if cached is not None:
            return cached
        mapping: dict[str, str] = {}
        for script in re.findall(r'<script[^>]*>(.*?)</script>', html, re.S):
            if 'hs_kw' not in script or 'GetClassName' not in script:
                continue
            mapping.update(cls._decode_kw_script(script))
        cls._kw_mapping_cache.clear()
        cls._kw_mapping_cache[html] = mapping
        return mapping

    @staticmethod
    def _decode_kw_script(script: str) -> dict[str, str]:
        """解码单个 suffix 的 IIFE script 块，返回 {hs_kwN_suffix: 明文}。"""
        D = '$'
        suf_m = re.search(
            r"return\s*'\.hs_kw'\s*\+\s*" + re.escape(D + 'index' + D) + r"\s*\+\s*'_(\w+)'",
            script)
        if not suf_m:
            return {}
        suffix = suf_m.group(1)
        vals = AutohomeAPI._resolve_kw_definitions(script)

        # 字典字符串：$ruleDict$ = $GetWindow$()[key](<dictexpr>)
        gwm = re.search(
            re.escape(D + 'ruleDict' + D) + r'\s*=\s*' + re.escape(D + 'GetWindow' + D + '()'),
            script)
        dictexpr = ''
        if gwm:
            j = gwm.end()
            while j < len(script) and script[j] != '[':
                j += 1
            depth = 0
            while j < len(script):
                if script[j] == '[':
                    depth += 1
                elif script[j] == ']':
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            j += 1
            while j < len(script) and script[j] != '(':
                j += 1
            depth = 0
            k = j
            while k < len(script):
                if script[k] == '(':
                    depth += 1
                elif script[k] == ')':
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            dictexpr = script[j + 1:k]

        # 位置串：$rulePosList$ = $Split$(<posexpr>, <sep>)
        rpl_key = D + 'rulePosList' + D + '=' + D + 'Split' + D + '('
        rpl_idx = script.find(rpl_key)
        posexpr = ''
        if rpl_idx >= 0:
            start = rpl_idx + len(rpl_key)
            depth = 0
            in_str = False
            j = start
            while j < len(script):
                ch = script[j]
                if ch == "'" and (j == 0 or script[j - 1] != '\\'):
                    in_str = not in_str
                elif not in_str:
                    if ch == '(':
                        depth += 1
                    elif ch == ')':
                        if depth == 0:
                            break
                        depth -= 1
                    elif ch == ',' and depth == 0:
                        break
                j += 1
            posexpr = script[start:j]

        dict_str = AutohomeAPI._eval_kw_expr(dictexpr, vals)
        pos_str = AutohomeAPI._eval_kw_expr(posexpr, vals)

        out: dict[str, str] = {}
        for idx, grp in enumerate(pos_str.split(';')):
            if not grp:
                continue
            chars = []
            for tok in grp.split(','):
                tok = tok.strip()
                if not tok:
                    continue
                try:
                    p = int(tok)
                except ValueError:
                    continue
                if 0 <= p < len(dict_str):
                    chars.append(dict_str[p])
            out[f'hs_kw{idx}_{suffix}'] = ''.join(chars)
        return out

    @staticmethod
    def _resolve_kw_definitions(script: str) -> dict[str, str]:
        """解析 IIFE script 块内所有混淆 var/function，返回 {名: 常量字符串}。

        恒等函数（return 其参数）不在此处登记——由 _eval_kw_expr 在调用点处理。
        所有控制流（if/else）都退化为常量：内部函数返回值与比较值相同→if 分支，
        否则→else 分支；分支可为字符串字面量或内部函数调用（==内部返回值）。
        """
        vals: dict[str, str] = {}
        # A) var NAME = 'lit';
        for m in re.finditer(r"var\s+(\w+)\s*=\s*'([^']*)'\s*;", script):
            vals[m.group(1)] = m.group(2)
        # B) function NAME(){'return NAME';return 'lit';}
        for m in re.finditer(r"function\s+(\w+)\(\)\s*\{\s*'return \w+'\s*;\s*return\s+'([^']*)'\s*;", script):
            vals[m.group(1)] = m.group(2)
        # G) var NAME=function(){'return NAME';return 'lit';};
        for m in re.finditer(r"var\s+(\w+)=function\(\)\{\s*'return \w+'\s*;\s*return\s+'([^']*)'\s*;", script):
            vals[m.group(1)] = m.group(2)
        # C) var NAME=function(){'NAME';var _X=function(){return 'lit';}; return _X();}
        for m in re.finditer(r"var\s+(\w+)=function\(\)\{'\w+';var _\w+=function\(\)\{return '([^']*)';\};\s*return _\w+\(\);\}", script):
            vals[m.group(1)] = m.group(2)
        # D) if/else dispatch：内函数返回 INNER，比较 CMP；INNER==CMP→if 分支，否则→else 分支
        for m in re.finditer(
            r"function\s+(\w+)\(\)\s*\{\s*function\s+_\w+\(\)\{return\s+'([^']*)';\};\s*"
            r"if\(_\w+\(\)=='([^']*)'\)\{\s*return\s+(?:'([^']*)'|(_\w+\(\)));\}\s*"
            r"else\s*\{\s*return\s+(?:'([^']*)'|(_\w+\(\)));",
            script):
            name, inner, cmpv = m.group(1), m.group(2), m.group(3)
            if_lit, if_call, else_lit, else_call = m.group(4), m.group(5), m.group(6), m.group(7)
            ifb = if_lit if if_lit is not None else (inner if if_call else '')
            elseb = else_lit if else_lit is not None else (inner if else_call else '')
            vals[name] = ifb if inner == cmpv else elseb
        # E) var NAME=function(){'NAME';var _X=function(arg){...return arg;}; return _X('lit');}
        for m in re.finditer(
            r"var\s+(\w+)=function\(\)\{'\w+';var _\w+=function\((\w+__)\)\{[^}]*return\s+\w+__;\};\s*"
            r"return _\w+\('([^']*)'\);\}", script):
            vals[m.group(1)] = m.group(3)
        return vals

    @staticmethod
    def _eval_kw_expr(expr: str, vals: dict[str, str]) -> str:
        """求值 JS 字符串拼接表达式（+ 连接的字面量/变量/函数调用/IIFE）。

        操作数形式：'lit'、NAME（裸变量→其值）、NAME()（无参调用→其值）、
        NAME('lit')（恒等函数调用→参数）、(function(){...return 'X';})()（IIFE→X）、
        (function(arg){...return arg;})('lit')（IIFE 恒等→参数）、(expr)（分组→递归求值）。
        """
        out: list[str] = []
        i, n = 0, len(expr)
        while i < n:
            c = expr[i]
            if c.isspace():
                i += 1
                continue
            if c == '+':
                i += 1
                continue
            if c == "'":
                j = i + 1
                while j < n and expr[j] != "'":
                    j += 1
                out.append(expr[i + 1:j])
                i = j + 1
                continue
            if c == '(':
                depth = 0
                j = i
                while j < n:
                    if expr[j] == '(':
                        depth += 1
                    elif expr[j] == ')':
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                inner = expr[i + 1:j].strip()
                i = j + 1
                if inner.startswith('function'):
                    # IIFE：(function(...){...})() 或 (function(arg){...})('lit')
                    while i < n and expr[i].isspace():
                        i += 1
                    arg: str | None = None
                    if i < n and expr[i] == '(':
                        depth = 0
                        k = i
                        while k < n:
                            if expr[k] == '(':
                                depth += 1
                            elif expr[k] == ')':
                                depth -= 1
                                if depth == 0:
                                    break
                            k += 1
                        callarg = expr[i + 1:k].strip()
                        i = k + 1
                        if callarg.startswith("'"):
                            arg = callarg[1:callarg.find("'", 1)]
                    m = re.search(r"return\s+'([^']*)'", inner)
                    if m:
                        out.append(m.group(1))
                    elif arg is not None:
                        out.append(arg)
                    else:
                        out.append('')
                else:
                    # 分组：(expr) → 递归求值
                    out.append(AutohomeAPI._eval_kw_expr(inner, vals))
                continue
            m = re.match(r'([A-Za-z_$][\w$]*)', expr[i:])
            if m:
                name = m.group(1)
                i += m.end()
                while i < n and expr[i].isspace():
                    i += 1
                if i < n and expr[i] == '(':
                    depth = 0
                    k = i
                    while k < n:
                        if expr[k] == '(':
                            depth += 1
                        elif expr[k] == ')':
                            depth -= 1
                            if depth == 0:
                                break
                        k += 1
                    callarg = expr[i + 1:k].strip()
                    i = k + 1
                    if callarg.startswith("'"):
                        # 恒等函数调用 NAME('lit') → lit
                        out.append(callarg[1:callarg.find("'", 1)])
                    elif callarg == '':
                        out.append(vals.get(name, ''))
                    else:
                        out.append('')
                else:
                    out.append(vals.get(name, ''))
                continue
            i += 1
        return ''.join(out)

    @classmethod
    def _clean_anti_scraping(cls, text: str,
                             kw_mapping: dict[str, str] | None = None) -> str:
        """清洗之家字体加密 span。

        用 kw_mapping（已构建的映射）把 span 替换为明文字符；
        无映射时退回旧逻辑（删除 span，仅保留可见文本）。
        生产调用方均先 _build_kw_mapping 再传 kw_mapping=。
        """
        if not isinstance(text, str):
            return text
        mapping = kw_mapping
        if mapping:
            def _repl(m: re.Match) -> str:
                return mapping.get(m.group(1), '')
            text = re.sub(r"<span\s+class='(hs_kw\d+_\w+)'></span>", _repl, text)
        else:
            text = re.sub(r"<span\s+class='hs_kw\d+_\w+'></span>", "", text)
        text = re.sub(r"&nbsp;", " ", text)
        return text.strip()

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

    # 之家 baike ID -> 完整字段名。ID 不受反爬影响，跨车系一致。
    # 来源：car.autohome.com.cn/baike/detail_7_24_{id}.html 页面标题核实。
    # baike ID 是唯一可靠还原途径——序号表在「轮距(mm)」与「(mm)」、「轮胎」与「」
    # 等反爬变体下 index 语义冲突/错位，ID 精确还原并修复多处 swap/丢字/错配。
    # 优先级最高（见 _restore_field_name），既有序号表/还原表仅作 field_id 缺失时兜底。
    _FIELD_NAME_BY_BAIKE_ID = {
        # 车轮制动（v7）
        1219: "前制动器类型",
        1220: "后制动器类型",
        1200: "驻车制动类型",
        1222: "前轮胎规格",
        1223: "后轮胎规格",
        1224: "备胎规格",
        9039: "备胎放置方式",
        # 车身（Task 6.2 P2-19：后轮距 swap 根治）
        # 1170 baike 页标题「轮距」，配置语义=前轮距（后轮距另有 id 9004）；
        # 9004 raw='(mm)' 被序号表错配为前轮距，baike ID 修正为后轮距。
        5886: "长度(mm)",
        5887: "宽度(mm)",
        5888: "高度(mm)",
        1169: "轴距(mm)",
        1170: "前轮距(mm)",
        9004: "后轮距(mm)",
        9123: "满载最小离地间隙(mm)",
        1172: "车门数(个)",        # 旧还原表误作「油箱容积(个)」
        1173: "座位数(个)",
        1174: "油箱容积(L)",
        1175: "后备厢容积(L)",
        1370: "风阻系数(Cd)",
        1147: "车身结构",
        8444: "车门开启方式",
        1176: "接近角(°)",
        1177: "离去角(°)",
        1267: "最小转弯半径(m)",
        # 被动安全（Task 6.3 P0-5）
        28: "主/副驾驶座安全气囊",
        27: "前排侧气囊",
        26: "前后排头部气囊(气帘)",
        # 座椅配置（Task 6.3 P0-5）
        87: "座椅材质",
        90: "主座椅调节方式",
        91: "副座椅调节方式",
        89: "主/副驾驶座电动调节",
        93: "前排座椅功能",        # 旧还原表误作「第二排座椅功能」
        92: "电动座椅记忆功能",
        101: "后排电动调节副驾驶位座椅",
        99: "第二排座椅调节",
        104: "座椅布局",
        105: "后排座椅放倒形式",
        95: "前/后排中央扶手",
        96: "后排杯架",
        # 空调/冰箱（Task 6.3 P0-5）
        150: "空调温度控制方式",
        8417: "热泵空调",
        1143: "后排独立空调",       # 旧还原表误作「空调温度控制方式」
        1144: "后座出风口",
        151: "温度分区控制",
        1142: "车载空气净化器",     # 旧残缺「车载净化器」
        1140: "车内PM2.5过滤装置",
        1146: "车内香氛装置",
        1145: "车载冰箱",
        1141: "负离子发生器",
        9104: "空气质量检测",
        # 排查整个同类（Task 6.1）：原 raw 为空被整条丢弃
        81: "全液晶仪表盘",         # 方向盘/内后视镜类目，baike「全液晶仪表」
        1194: "配气机构",           # 发动机类目，baike「发动机配气机构」
    }

    @classmethod
    def _restore_field_name(cls, name: str, category: str = "", index: int = 0,
                            field_id: int | None = None) -> str:
        """补全被反爬打碎的配置字段名。

        Args:
            name: 清洗后的残缺字段名（反爬 span 已去除）。
            category: 类目名。
            index: 该残缺名在同类目内第几次出现（0-based）。
            field_id: 之家 baike ID（param/config item 的 id 字段），不受反爬影响。
                      优先于序号表——当两种反爬变体（「轮胎」vs「」）使序号表 index
                      语义冲突时，ID 是唯一可靠还原途径。
        """
        # 1) 优先查 baike ID 表（最可靠，不受反爬变体影响）
        if field_id is not None and field_id in cls._FIELD_NAME_BY_BAIKE_ID:
            return cls._FIELD_NAME_BY_BAIKE_ID[field_id]
        # 2) 查序号表（处理同类目重复残缺名，含空名——车轮制动轮胎规格被反爬吃成 ""）
        idx_key = (category, name, index)
        if idx_key in cls._FIELD_NAME_BY_INDEX:
            return cls._FIELD_NAME_BY_INDEX[idx_key]
        # dashboard-v10 Task 6.1：删除 _FIELD_NAME_RESTORE 兜底分支——v9 字体解码
        # 稳定后字段名在 _clean_anti_scraping 阶段已完整还原，不再走手写 (类目,名)
        # 映射表。field_id 缺失且序号表未命中时，原名返回（解码已修复，残缺名不该出现）。
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

        # 字体加密 span 明文映射：整页构建一次，下游所有 _clean_anti_scraping 复用。
        kw_mapping = self._build_kw_mapping(html)
        if kw_mapping:
            info["_kw_mapping"] = kw_mapping

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
                info["name"] = self._clean_anti_scraping(
                    first_spec.get("specname", first_spec.get("name", "")), kw_mapping=kw_mapping)

        if not info.get("name"):
            config_data = info.get("config_data", {})
            config_result = config_data.get("result", {}) if isinstance(config_data, dict) else {}
            param_items = config_result.get("paramtypeitems", []) if isinstance(config_result, dict) else []
            if param_items:
                first_item = param_items[0].get("paramitems", []) if isinstance(param_items[0], dict) else []
                if first_item:
                    name_raw = first_item[0].get("name", "")
                    info["name"] = self._clean_anti_scraping(name_raw, kw_mapping=kw_mapping)

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
        kw = info.get("_kw_mapping")

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
                    name = self._clean_anti_scraping(vi.get("value", ""), kw_mapping=kw)
                    if spec_id:
                        name_map[spec_id] = name
            if len(param_items) >= 2:
                for vi in param_items[1].get("valueitems", []):
                    spec_id = str(vi.get("specid", ""))
                    price = self._clean_anti_scraping(vi.get("value", ""), kw_mapping=kw)
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

        # dashboards-tri-polish B方案：review_id 优先用 showId（长字符串，详情页 URL 用它）
        # Koubeigid/Koubeiid（短数字）作 fallback——详情页 view_{showId}.html 才是正确 URL，
        # 用短数字会 404（backfill 失败根因）。
        show_id = item.get("showId", "")
        koubei_id = show_id or item.get("Koubeiid") or item.get("Koubeigid", "")
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
        kw = info.get("_kw_mapping")

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
                    name = self._clean_anti_scraping(vi.get("value", ""), kw_mapping=kw)
                    if spec_id:
                        name_map[spec_id] = name
            if len(param_items) >= 2:
                for vi in param_items[1].get("valueitems", []):
                    spec_id = str(vi.get("specid", ""))
                    price = self._clean_anti_scraping(vi.get("value", ""), kw_mapping=kw)
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
                name = self._clean_anti_scraping(name_raw, kw_mapping=kw)
                values = param.get("valueitems", [])
                if not values:
                    continue
                val = self._clean_anti_scraping(values[0].get("value", ""), kw_mapping=kw)
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

    _TAG_RE = re.compile(r"<[^>]+>")

    @classmethod
    def _value_of(cls, value_item: dict, kw_mapping: dict[str, str] | None = None) -> str | list | None:
        """取参数值：value 为空时读 sublist（之家反爬把真实值迁到 sublist）。
        param 类真实值在 subvalue（如轮胎"235/55 R19"）；
        option 类真实文本在 subname（如"15.6英寸"），subvalue 是标配标记(1/2)。
        方案1（sublist 保结构，Task9）：sublist 不再 join 成字符串，保留为
        list[{name}] 供下游结构化解析（sublist_contains 抽取、复合功能展示）。
        字体加密 span：有 kw_mapping 时替换为明文字符，否则 _TAG_RE 通用去标签。"""
        val = (value_item.get("value") or "").strip() if isinstance(value_item, dict) else ""
        if val:
            return val
        subs = value_item.get("sublist") if isinstance(value_item, dict) else None
        if not subs:
            return None
        parts = []
        for s in subs:
            if not isinstance(s, dict):
                continue
            # subname 优先（option 类真实文本），subvalue 兜底（param 类真实值）；
            # 两者都可能带 hs_kw span——用映射解码，无映射时退回通用去标签。
            sn_raw = str(s.get("subname") or "")
            sv_raw = str(s.get("subvalue") or "")
            if kw_mapping:
                sn = cls._clean_anti_scraping(sn_raw, kw_mapping=kw_mapping)
                sv = cls._clean_anti_scraping(sv_raw, kw_mapping=kw_mapping)
            else:
                sn = cls._TAG_RE.sub("", sn_raw).strip()
                sv = cls._TAG_RE.sub("", sv_raw).strip()
            picked = sn or sv
            if picked:
                parts.append({"name": picked})
        return parts if parts else None

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
        # 丢弃计数（Task 6.1）：空名（解析失败）与空值分别计数，不再无声消失。
        dropped = {"no_name": 0, "no_values": 0}
        kw = info.get("_kw_mapping")

        config_data = info.get("config_data", {})
        config_result = config_data.get("result", {}) if isinstance(config_data, dict) else {}

        for type_item in config_result.get("paramtypeitems", []) if isinstance(config_result, dict) else []:
            cat_name = self._clean_anti_scraping(type_item.get("name", "基础参数"), kw_mapping=kw)
            params = {}
            _name_seen = {}
            for param in type_item.get("paramitems", []):
                _raw = self._clean_anti_scraping(param.get("name", ""), kw_mapping=kw)
                _idx = _name_seen.get(_raw, 0)
                _name_seen[_raw] = _idx + 1
                _fid = param.get("id")
                p_name = self._restore_field_name(_raw, cat_name, _idx, field_id=_fid)
                values = param.get("valueitems", [])
                if p_name and values:
                    if len(values) == 1:
                        params[p_name] = self._clean_anti_scraping(self._value_of(values[0], kw_mapping=kw), kw_mapping=kw)
                    else:
                        spec_values = {}
                        for i, v in enumerate(values):
                            spec_id = str(v.get("specid", f"spec_{i}"))
                            spec_values[spec_id] = self._clean_anti_scraping(self._value_of(v, kw_mapping=kw), kw_mapping=kw)
                        params[p_name] = spec_values
                else:
                    if not p_name:
                        dropped["no_name"] += 1
                    else:
                        dropped["no_values"] += 1
            if params:
                result["categories"][cat_name] = params

        option_data = info.get("option_data", {})
        option_result = option_data.get("result", {}) if isinstance(option_data, dict) else {}
        for type_item in option_result.get("configtypeitems", []) if isinstance(option_result, dict) else []:
            cat_name = self._clean_anti_scraping(type_item.get("name", "配置参数"), kw_mapping=kw)
            params = {}
            _name_seen = {}
            for config_item in type_item.get("configitems", []):
                _raw = self._clean_anti_scraping(config_item.get("name", ""), kw_mapping=kw)
                _idx = _name_seen.get(_raw, 0)
                _name_seen[_raw] = _idx + 1
                _fid = config_item.get("id")
                c_name = self._restore_field_name(_raw, cat_name, _idx, field_id=_fid)
                values = config_item.get("valueitems", [])
                if c_name and values:
                    if len(values) == 1:
                        params[c_name] = self._clean_anti_scraping(self._value_of(values[0], kw_mapping=kw), kw_mapping=kw)
                    else:
                        spec_values = {}
                        for i, v in enumerate(values):
                            spec_id = str(v.get("specid", f"spec_{i}"))
                            spec_values[spec_id] = self._clean_anti_scraping(self._value_of(v, kw_mapping=kw), kw_mapping=kw)
                        params[c_name] = spec_values
                else:
                    if not c_name:
                        dropped["no_name"] += 1
                    else:
                        dropped["no_values"] += 1
            if params:
                result["categories"][cat_name] = params

        # 丢弃披露：有解析失败时记入结果并告警（空值丢弃为数据缺失，仅计数不告警）
        if dropped["no_name"]:
            logger.warning(
                "get_full_config series=%s: %d 个参数因名称解析失败丢弃（no_values=%d）",
                series_id, dropped["no_name"], dropped["no_values"],
            )
        result["dropped_params"] = dropped["no_name"]
        result["dropped_no_values"] = dropped["no_values"]
        # dashboard-v10 Task 1.1：字体解码命中率 = 成功参数数 / (成功 + 名称解析失败)
        # no_values 丢弃是数据缺失（非解码失败）不计入分母；空配置 → 1.0（无失败）
        _successful = sum(len(p) for p in result["categories"].values())
        _total = _successful + dropped["no_name"]
        result["decode_hit_rate"] = (
            round(1 - dropped["no_name"] / _total, 4) if _total > 0 else 1.0)

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
