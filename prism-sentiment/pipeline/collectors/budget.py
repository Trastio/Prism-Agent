"""TikHub 日预算护栏（2026-10-15 舆情降本 change T2，方案 L6/R43）。

执行层护栏（红线#5 哲学——护栏在执行层不在提示词）：挂在 TikHubClient._send
唯一通路，计数落 tikhub_daily_usage 表（date 主键），超 TIKHUB_DAILY_BUDGET
抛 TikHubBudgetExceeded，调用不发出去。

设计注：
- **TikHubBudgetExceeded 故意不继承 TikHubError**——scheduler 关键词级
  `except TikHubError` 会把它当业务失败吞掉记 fetch_failures；预算耗尽必须
  冒泡到 collect_vehicle 顶层才能标 budget_capped + 登记未采车。
- 计数用 stdlib sqlite3 直写业务库（与 aiosqlite 引擎同库不同连接）：
  WAL 模式下毫秒级本地写，busy_timeout 容忍与引擎的短并发；不引入 async
  开销。计数含所有走 client 的调用（搜索/评论/互动刷新/搜索指数——
  IndexCollector 复用同一 TikHubClient，自动计入，无需额外接线）。
- 表结构由 models.schemas.TikhubDailyUsage 经 create_all 建；此处再带
  CREATE TABLE IF NOT EXISTS 兜底（老库首次跑、测试临时库均自足）。
- 默认 2200 次/天 = 15 车 × ≈98 次/车 × 1.5 余量（账单对账后校准，方案§八④）。
"""
import logging
import os
import sqlite3
from datetime import datetime

logger = logging.getLogger(__name__)

_BUDGET_ENV = "TIKHUB_DAILY_BUDGET"
_BUDGET_DEFAULT = 2200

# 建表兜底幂等标记（按 path 缓存——测试会换临时库）
_ensured_paths: set[str] = set()


class TikHubBudgetExceeded(Exception):
    """当日 TikHub 调用数超过预算。故意不继承 TikHubError（见模块注）。"""


def daily_budget() -> int:
    """env TIKHUB_DAILY_BUDGET 整数（默认 2200），非法回退默认。"""
    raw = os.getenv(_BUDGET_ENV, "")
    try:
        v = int(raw)
        return v if v > 0 else _BUDGET_DEFAULT
    except (TypeError, ValueError):
        return _BUDGET_DEFAULT


def _db_path() -> str:
    # 与 models.database.DB_PATH 同源约定（默认值一致）。每次读 env：
    # monkeypatch 友好（测试换临时库无需重导模块）。
    return os.getenv("DB_PATH", "data/vehicle_sentiment.db")


def _connect() -> sqlite3.Connection:
    path = _db_path()
    if path not in _ensured_paths:
        con = sqlite3.connect(path, timeout=5)
        try:
            con.execute("PRAGMA busy_timeout=5000")
            con.execute(
                "CREATE TABLE IF NOT EXISTS tikhub_daily_usage ("
                "date TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0)")
            con.commit()
            _ensured_paths.add(path)
        finally:
            con.close()
    con = sqlite3.connect(path, timeout=5)
    con.execute("PRAGMA busy_timeout=5000")
    return con


def today_usage() -> int:
    """当日已计数调用数（只读，登记/观测用）。库不可达返回 -1 不炸调用方。"""
    try:
        con = _connect()
        try:
            cur = con.execute(
                "SELECT calls FROM tikhub_daily_usage WHERE date = ?",
                (datetime.now().date().isoformat(),))
            row = cur.fetchone()
            return row[0] if row else 0
        finally:
            con.close()
    except sqlite3.Error as e:  # 计数器故障不阻断采集主链路（只失护栏）
        logger.warning("预算计数器读失败（护栏降级为不设限）: %s", e)
        return -1


def count_and_check() -> int:
    """计数 +1 并校验预算；超限抛 TikHubBudgetExceeded（请求不发出）。

    Returns 本次计数后的当日总调用数。计数器本身故障（库不可写）时
    只告警放行——护栏失效好过采集瘫痪（降级语义与 today_usage 对齐）。
    """
    budget = daily_budget()
    today = datetime.now().date().isoformat()
    try:
        con = _connect()
        try:
            cur = con.execute(
                "INSERT INTO tikhub_daily_usage (date, calls) VALUES (?, 1) "
                "ON CONFLICT(date) DO UPDATE SET calls = calls + 1 "
                "RETURNING calls",
                (today,))
            row = cur.fetchone()
            con.commit()
        finally:
            con.close()
    except sqlite3.Error as e:
        logger.warning("预算计数器写失败（护栏降级为不设限）: %s", e)
        return -1
    calls = row[0] if row else -1
    if calls > budget:
        raise TikHubBudgetExceeded(
            f"当日 TikHub 调用数 {calls} 已超预算 {budget}"
            f"（env {_BUDGET_ENV}，方案 L6）")
    return calls
