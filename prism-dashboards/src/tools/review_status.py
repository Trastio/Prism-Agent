"""口碑任务状态派生：从 raw _task_status dict 推导出前端/调用方需要的所有视图字段。

纯函数设计：无副作用，方便单测；不依赖 DB / asyncio。
"""
from __future__ import annotations

import time
from typing import Any

# heartbeat 超过此秒数视为 task 死了（M2 自愈的触发阈值）
HEARTBEAT_STALE_SEC = 60


def derive_status(
    raw_status: dict[str, Any] | None,
    reviews_taggable: int,
    reviews_tagged: int,
    now: float | None = None,
) -> dict[str, Any]:
    """派生完整的状态机视图

    Returns dict with keys:
      stage: 'unknown' | 'collecting' | 'tagging' | 'analysis_ready' | 'tagging_failed'
      task_alive: bool — task 是否在最近 HEARTBEAT_STALE_SEC 内有心跳
      coverage: float — reviews_tagged / reviews_taggable（分母=有文本可提取的口碑数）
      eta_seconds: int — 预计完成秒数（completed/failed 时为 0）
      rate_per_sec: float — 当前处理速率
      last_error: str | None — 上次失败原因
      raw_status: dict | None — input passthrough (debugging aid)
    """
    now = now or time.time()
    out = {
        "stage": "unknown",
        "task_alive": False,
        "coverage": 0.0,
        "eta_seconds": 0,
        "rate_per_sec": 0.0,
        "last_error": None,
        "raw_status": raw_status,
    }

    if not raw_status:
        return out

    status = raw_status.get("status", "")
    started_at = float(raw_status.get("started_at") or 0)
    last_hb = float(raw_status.get("last_heartbeat") or started_at)
    coverage = (reviews_tagged / reviews_taggable) if reviews_taggable > 0 else 0.0
    out["coverage"] = round(coverage, 4)

    if status == "completed":
        out["stage"] = "analysis_ready"
        return out

    if status == "failed":
        out["stage"] = "tagging_failed"
        out["last_error"] = raw_status.get("error")
        return out

    # running: collecting / extracting_tags / started
    if status in ("collecting", "extracting_tags", "started"):
        out["stage"] = "tagging" if status != "collecting" else "collecting"
        out["task_alive"] = (now - last_hb) <= HEARTBEAT_STALE_SEC

        # 计算 rate / eta
        tag_progress = raw_status.get("tag_progress") or {}
        processed = int(tag_progress.get("processed") or 0)
        # 用全任务时长算 rate，避免单点 heartbeat 抖动
        window = now - started_at
        if processed > 0 and window > 0:
            rate = processed / max(window, 1.0)
            out["rate_per_sec"] = round(rate, 2)
            remaining = max(reviews_taggable - reviews_tagged, 0)
            out["eta_seconds"] = int(remaining / rate) if rate > 0 else 0
        return out

    return out
