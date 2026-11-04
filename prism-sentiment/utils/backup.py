"""SQLite 在线备份 + 滚动保留 + 可选异地拷贝。

2026-09-15 落地（十二问审计 Q10）：此前只有清库前手动 .bak，主库与备份同盘、
无周期性——数据资产唯一副本是当时最大的风险敞口。daily_update.py 每日收尾调用。

- sqlite3 backup API：在线安全，服务可继续读写（分步拷页，不长锁）
- 滚动保留：日备留 14 份 + 每月 1 号锚点留 12 份（月锚点=当月 1 号那天跑出的
  备份；当天没跑则该月无锚点，属可接受的简化）；当日文件永不删
- 异地：BACKUP_OFFSITE_DIR（.env）配了就把当天备份拷过去——OneDrive/坚果云
  同步目录或外接盘皆可；未配置仅提示，本地滚动保留不受影响
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import shutil
import sqlite3
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "vehicle_sentiment.db"
DEFAULT_DEST = PROJECT_ROOT / "data" / "backups"

_BACKUP_RE = re.compile(r"^vehicle_sentiment_(\d{4})(\d{2})(\d{2})\.db\.gz$")


def backup_database(
    db_path: str | Path | None = None,
    dest_dir: str | Path | None = None,
    keep_daily: int = 14,
    keep_monthly: int = 12,
    offsite_dir: str | Path | None = None,
    today: date | None = None,
) -> dict:
    """备份数据库（在线安全）→ gzip 落盘 → 滚动清理 → 可选拷异地。

    offsite_dir：None=读 BACKUP_OFFSITE_DIR 环境变量；""=显式禁用（测试用）。
    同日重跑幂等（覆盖当天文件）。返回
    {ok, file, size_bytes, deleted, kept, offsite} 或 {ok: False, error}。
    """
    today = today or date.today()
    db_path = Path(db_path) if db_path else DEFAULT_DB
    dest_dir = Path(dest_dir) if dest_dir else DEFAULT_DEST
    if not db_path.exists():
        return {"ok": False, "error": f"数据库不存在: {db_path}"}

    dest_dir.mkdir(parents=True, exist_ok=True)
    final_path = dest_dir / f"vehicle_sentiment_{today:%Y%m%d}.db.gz"
    tmp_db = dest_dir / f".tmp_{today:%Y%m%d}.db"
    tmp_gz = dest_dir / (final_path.name + ".tmp")

    try:
        # 在线快照：源库只读打开，backup API 分步拷页（服务可继续写）
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(tmp_db)
        try:
            src.backup(dst, pages=4000)
        finally:
            dst.close()
            src.close()

        with open(tmp_db, "rb") as f_in, gzip.open(tmp_gz, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.replace(tmp_gz, final_path)  # 同日重跑 = 幂等覆盖
    except Exception as e:  # 备份失败不该带崩调用方（daily_update 只降退出码）
        logger.error("备份失败: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        tmp_db.unlink(missing_ok=True)
        tmp_gz.unlink(missing_ok=True)

    deleted = _prune_backups(dest_dir, today, keep_daily, keep_monthly)
    kept = len(_list_backups(dest_dir))
    offsite = _copy_offsite(final_path, offsite_dir)

    logger.info("备份完成: %s (%d bytes), 清理 %d 份, offsite=%s",
                final_path.name, final_path.stat().st_size, len(deleted), offsite)
    return {
        "ok": True,
        "file": str(final_path),
        "size_bytes": final_path.stat().st_size,
        "deleted": deleted,
        "kept": kept,
        "offsite": offsite,
    }


def _list_backups(dest_dir: Path) -> list[tuple[date, str]]:
    """列出 dest_dir 下符合命名约定的备份（date, name），按日期新→旧。"""
    entries = []
    for p in dest_dir.iterdir():
        m = _BACKUP_RE.match(p.name)
        if p.is_file() and m:
            entries.append((date(int(m[1]), int(m[2]), int(m[3])), p.name))
    entries.sort(reverse=True)
    return entries


def _prune_backups(dest_dir: Path, today: date, keep_daily: int, keep_monthly: int) -> list[str]:
    """滚动清理：月锚点（1 号）留 keep_monthly 份，其余日备留 keep_daily 份。

    非锚点老备份超出配额即删；当日文件无条件保留。返回被删文件名列表。
    """
    entries = _list_backups(dest_dir)
    survivors: set[str] = set()
    monthly = [name for d, name in entries if d.day == 1]
    daily = [name for d, name in entries if d.day != 1]
    survivors.update(monthly[:keep_monthly])
    survivors.update(daily[:keep_daily])

    deleted: list[str] = []
    for d, name in entries:
        if name not in survivors and d != today:
            (dest_dir / name).unlink()
            deleted.append(name)
    return deleted


def _copy_offsite(final_path: Path, offsite_dir: str | Path | None) -> str:
    """把当天备份拷到异地目录。返回 copied / not_configured / dir_missing / copy_failed。"""
    if offsite_dir is None:
        try:
            from dotenv import load_dotenv
            load_dotenv(PROJECT_ROOT / ".env")
        except Exception:
            pass
        offsite_dir = os.environ.get("BACKUP_OFFSITE_DIR", "")
    if not offsite_dir:
        return "not_configured"

    target_dir = Path(os.path.expanduser(str(offsite_dir)))
    if not target_dir.exists():
        logger.warning("BACKUP_OFFSITE_DIR 目录不存在，跳过异地拷贝: %s", target_dir)
        return "dir_missing"
    try:
        shutil.copy2(final_path, target_dir / final_path.name)
        return "copied"
    except OSError as e:
        logger.error("异地拷贝失败: %s", e)
        return "copy_failed"
