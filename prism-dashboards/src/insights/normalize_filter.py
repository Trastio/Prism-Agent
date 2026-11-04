"""交叉透视筛选条件归一化 + 指纹 hash（specs/dashboards v5）。

归一化口径：年款从 spec_name 正则"XXXX款"提取；省份走 province_of；
版型/关键词 strip 空值归一为 ""。指纹用于 AI 总结缓存命中。
"""
from __future__ import annotations

import hashlib
import re

_YEAR_RE = re.compile(r"(20\d{2})款")
_UNKNOWN_YEAR = "未知年款"


def extract_year(spec_name: str | None) -> str:
    """从 spec_name 提取"XXXX款"；缺年款归"未知年款"（specs：99% 命中 + 脏值兜底）。"""
    if not spec_name:
        return _UNKNOWN_YEAR
    m = _YEAR_RE.search(spec_name)
    return f"{m.group(1)}款" if m else _UNKNOWN_YEAR


def _norm(v) -> str:
    """空值归一为空串（None/空串/纯空白 同 hash）。"""
    return (str(v).strip() if v else "")


def filter_hash(model_id: str, filt: dict) -> str:
    """筛选条件指纹（sha1，model_id+年款+版型+省份+关键词 归一化后）。

    字段顺序无关（按固定 key 顺序拼接），保证相同条件同 hash。
    """
    parts = [f"mid={_norm(model_id)}",
             f"year={_norm(filt.get('year'))}",
             f"spec={_norm(filt.get('spec'))}",
             f"prov={_norm(filt.get('prov'))}",
             f"kw={_norm(filt.get('kw'))}"]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
