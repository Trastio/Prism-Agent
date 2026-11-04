"""Pipeline progress tracking — per-platform granularity.

Replaces the old simple dict with structured progress objects so the
frontend can display collection status for each platform independently.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PlatformProgress:
    """Single-platform collection progress."""
    phase: str = "pending"          # pending / collecting / done / error / skipped
    posts_found: int = 0
    posts_stored: int = 0
    comments_stored: int = 0
    error: Optional[str] = None
    # 该平台采集失败的关键词列表（网络重试耗尽 / collector 内部重试耗尽）。
    # 前端采集进度面板按平台 chip 显示"失败 N"，让丢词不再静默。
    fetch_failures: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "posts_found": self.posts_found,
            "posts_stored": self.posts_stored,
            "comments_stored": self.comments_stored,
            "error": self.error,
            "fetch_failures": list(self.fetch_failures),
        }


@dataclass
class PipelineProgress:
    """Full pipeline progress across all platforms."""
    overall_phase: str = "idle"       # idle / collecting / enriching / analyzing / completed / error
    current_step: str = ""            # human-readable step label
    platforms: dict[str, PlatformProgress] = field(default_factory=dict)
    posts_collected: int = 0
    posts_enriched: int = 0
    analyzed: int = 0
    error: Optional[str] = None
    env_warning: Optional[str] = None   # 环境未就绪警告（如社媒 CDP 全跳过），非致命但须可见

    def init_platforms(self) -> None:
        """Initialise progress trackers for all active platforms.

        2026-10-15 舆情降本（R23/R31）：微博/快手/新闻源停采，进度面板随调度
        面收敛为 小红书/抖音/车质网 三平台。
        """
        for name in ("xiaohongshu", "douyin", "chezhiwang"):
            self.platforms[name] = PlatformProgress()

    def to_dict(self) -> dict:
        return {
            "overall_phase": self.overall_phase,
            "current_step": self.current_step,
            "posts_collected": self.posts_collected,
            "posts_enriched": self.posts_enriched,
            "analyzed": self.analyzed,
            "error": self.error,
            "env_warning": self.env_warning,
            "platforms": {
                name: p.to_dict() for name, p in self.platforms.items()
            },
        }


# Global progress registry: vehicle_id → PipelineProgress
pipeline_progress: dict[str, PipelineProgress] = {}

# Legacy compatibility — keep old simple dict for code that hasn't migrated
pipeline_phases: dict[str, dict] = {}


from datetime import datetime, timedelta

_PHASE_TTL = timedelta(minutes=30)  # 与 DB 锁 TTL 对齐


def _is_phase_stale(phase_info: dict) -> bool:
    """30 分钟无进展视为 zombie（与 DB 锁脏锁容错对齐）。

    无 _updated_at 视为非 stale（向后兼容旧调用方/测试数据）——_run_full_pipeline
    现在每次 phase 转换都设 _updated_at，zombie task 残留的 _updated_at 是死亡
    时间，30min 后 stale。
    """
    updated = phase_info.get("_updated_at")
    if not updated:
        return False  # 旧数据兼容
    return datetime.now() - updated > _PHASE_TTL
