"""用户手填政策价格表：model_id:spec_id → {price: 元, note, updated_at}。

specs/dashboards v4：与 option_prices 同纪律——缺文件/坏文件视为空表（不抛）、
值校验（is_valid_price，0=无政策合法）、tmp+os.replace 原子写。键形
（model_id:spec_id）由写入端点校验，load 不猜。
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path

from src.api.option_prices import is_valid_price

# P3#34：Path(__file__) 绝对定位（同 option_prices），不依赖进程 cwd；转 str 保持类型兼容。
POLICY_PATH = str(Path(__file__).parent.parent.parent / "data" / "policy_prices.json")


def load_policy_prices(path: str | os.PathLike | None = None) -> dict[str, dict]:
    p = str(path or POLICY_PATH)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    for k, v in data.items():
        if not isinstance(v, dict):
            continue
        price = v.get("price")
        if is_valid_price(price):
            out[str(k)] = {"price": float(price),
                           "note": str(v.get("note") or ""),
                           "updated_at": str(v.get("updated_at") or "")}
    return out


# dashboard-v10 Task 1.3：写锁（对齐 option_prices 模式）——
# tmp+replace 已原子，但并发 read-modify-write 会丢更新。RLock 串行化写，
# 可重入：端点持锁做 read-modify-write 后调 save_policy_prices 再入不 deadlock。
_SAVE_LOCK = threading.RLock()


def save_policy_prices(prices: dict[str, dict], path: str | os.PathLike | None = None) -> None:
    p = str(path or POLICY_PATH)
    parent = os.path.dirname(p)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{p}.tmp.{os.getpid()}.{id(prices)}"  # P3#37：并发写不共用固定 .tmp
    with _SAVE_LOCK:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(prices, f, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(tmp, p)
