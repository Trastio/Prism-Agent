"""夜跑漏跑补跑测试（2026-10-21 免管理员方案，S4U 两次被拒的替代路）。

覆盖：新鲜度判定全分支（时间窗/新鲜/过期/空库/库不可读fail-safe）、
UTC→本地换算边界、幂等标记、服务未就绪放弃。零外呼零真库。
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import missed_run_catchup as mc

TZ = mc.TZ


def _mk_db(path: Path, last_collected: str | None):
    con = sqlite3.connect(path)
    con.execute("create table raw_posts(collected_at text)")
    if last_collected:
        con.execute("insert into raw_posts values (?)", (last_collected,))
    con.commit()
    con.close()


def test_before_window_no_need(tmp_path, monkeypatch):
    db = tmp_path / "v.db"
    _mk_db(db, None)
    monkeypatch.setattr(mc, "DB", db)
    need, why = mc._freshness(datetime(2026, 10, 21, 6, 59, tzinfo=TZ))
    assert not need and "留夜跑窗口" in why


def test_stale_data_needs_catchup(tmp_path, monkeypatch):
    db = tmp_path / "v.db"
    # 最新帖停在昨天（UTC 10-19 20:00），本地 10-21 07:00 判定：夜跑线=UTC 10-20 19:00
    _mk_db(db, "2026-10-19 20:00")
    monkeypatch.setattr(mc, "DB", db)
    need, why = mc._freshness(datetime(2026, 10, 21, 7, 0, tzinfo=TZ))
    assert need and "夜跑未落数据" in why


def test_fresh_data_no_need(tmp_path, monkeypatch):
    db = tmp_path / "v.db"
    # 昨晚夜跑落了数据（UTC 10-20 20:27 = 本地 10-21 04:27）
    _mk_db(db, "2026-10-20 20:27")
    monkeypatch.setattr(mc, "DB", db)
    need, why = mc._freshness(datetime(2026, 10, 21, 7, 0, tzinfo=TZ))
    assert not need and "数据新鲜" in why


def test_utc_boundary_exact():
    """本地 03:00（+8）对应 UTC 前一天 19:00——阈值换算钉死。"""
    # 空库走 need 分支前先钉换算：直接构造内部逻辑同式
    now = datetime(2026, 10, 21, 7, 0, tzinfo=TZ)
    night_local = now.replace(hour=3, minute=0)
    thr = night_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    assert thr == "2026-10-20 19:00"


def test_empty_db_needs_catchup(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "DB", tmp_path / "v.db")
    _mk_db(tmp_path / "v.db", None)
    need, why = mc._freshness(datetime(2026, 10, 21, 8, 0, tzinfo=TZ))
    assert need and "零帖" in why


def test_unreadable_db_fail_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "DB", tmp_path / "nonexistent.db")  # 无表文件→查询报错
    (tmp_path / "nonexistent.db").write_text("not a sqlite", encoding="utf-8")
    need, why = mc._freshness(datetime(2026, 10, 21, 8, 0, tzinfo=TZ))
    assert not need and "保守跳过" in why


def test_marker_skips_run(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "LOGS", tmp_path)
    today = f"catchup_{datetime.now(TZ):%Y%m%d}.done"
    (tmp_path / today).write_text("x", encoding="utf-8")
    ran = {"n": 0}
    monkeypatch.setattr(mc.subprocess, "run", lambda *a, **k: ran.update(n=ran["n"] + 1) or None)
    monkeypatch.setattr(mc, "_wait_service", lambda: True)
    import sys as _s
    monkeypatch.setattr(_s, "argv", ["missed_run_catchup.py"])
    rc = mc.main()  # 今日标记存在 → 直接 0，判定与子进程都不该走
    assert rc == 0 and ran["n"] == 0


def test_service_not_ready_gives_up(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, "LOGS", tmp_path)
    monkeypatch.setattr(mc, "DB", tmp_path / "v.db")
    _mk_db(tmp_path / "v.db", "2026-10-19 20:00")
    monkeypatch.setattr(mc, "_wait_service", lambda: False)
    ran = {"n": 0}
    monkeypatch.setattr(mc.subprocess, "run", lambda *a, **k: ran.update(n=ran["n"] + 1) or None)
    import sys as _s
    monkeypatch.setattr(_s, "argv", ["missed_run_catchup.py"])
    monkeypatch.setattr(mc, "_freshness", lambda now: (True, "测试桩：需补跑"))
    rc = mc.main()
    assert rc == 2 and ran["n"] == 0
    assert (tmp_path / f"catchup_{datetime.now(TZ):%Y%m%d}.done").exists()  # 标记已写防重复
