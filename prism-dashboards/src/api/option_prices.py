"""用户自定义配置价格表：参数名 → 价格（元）。看板唯一可写持久化文件。

specs/dashboards：折价只认本表；缺文件/损坏文件视为空表（不抛），
保证看板在任意文件状态下可用。写走 tmp + os.replace 原子替换。
"""
from __future__ import annotations

import json
import math
import os
import threading
from pathlib import Path

# P3#34：Path(__file__) 绝对定位（与 concept_config.py 同款），不依赖进程 cwd——
# 从其它目录启动服务时 cwd 相对路径会静默找不到文件 → 价格表被当成空表。
# 转 str 保持模块常量类型兼容（调用方/测试按 str monkeypatch）。
PRICES_PATH = str(Path(__file__).parent.parent.parent / "data" / "option_prices.json")


def is_finite_number(v) -> bool:
    """排除 bool 的有限数值判定（bool 是 int 子类；NaN/inf 不算数）。
    价格/维度聚合的合法数值口径统一走这里，别处不要另抄一份。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def is_valid_price(v) -> bool:
    """合法价格：有限数值且 ≥0（0 元=免费配置，合法）。"""
    return is_finite_number(v) and v >= 0


def load_prices(path: str | os.PathLike | None = None) -> dict[str, float]:
    p = str(path or PRICES_PATH)
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    # 值过滤：堵手改文件混入 true/NaN/-5（合法口径见 is_valid_price）
    return {str(k): v for k, v in data.items() if is_valid_price(v)}


# P2-24：save_prices 写锁——tmp+replace 已原子，但并发写仍会丢更新
# （A 读旧表→B 读旧表→A 写→B 写覆盖 A）。进程内 RLock 串行化写。
# 用 RLock（可重入）：端点 read-modify-write 持锁后调 save_prices 再入锁不 deadlock。
_SAVE_LOCK = threading.RLock()


def save_prices(prices: dict[str, float], path: str | os.PathLike | None = None) -> None:
    """原子写价格表（tmp + os.replace）。P2-24：加进程内写锁防并发丢更新——
    两个并发 POST 同时读旧表写新表会互相覆盖。锁串行化写，保证后写基于先写结果。
    跨进程并发（多 worker）仍靠 tmp 唯一名 + os.replace 原子性兜底（不丢文件，最坏丢一行更新）。
    RLock 可重入：调用方持锁做 read-modify-write 后调本函数再入锁不 deadlock。"""
    p = str(path or PRICES_PATH)
    parent = os.path.dirname(p)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{p}.tmp.{os.getpid()}.{id(prices)}"  # P3#37：并发写不共用固定 .tmp
    with _SAVE_LOCK:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(prices, f, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(tmp, p)
