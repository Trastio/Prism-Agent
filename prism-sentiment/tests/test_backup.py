"""utils/backup.py 单测：在线备份可还原 / 幂等 / 滚动保留 / 异地拷贝。"""

import gzip
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from utils.backup import _prune_backups, backup_database

TODAY = date(2026, 9, 15)


@pytest.fixture
def db_file(tmp_path):
    p = tmp_path / "test.db"
    con = sqlite3.connect(p)
    con.execute("create table vehicles (id text, name text)")
    con.execute("insert into vehicles values ('v1', '测试车')")
    con.commit()
    con.close()
    return p


def _make_old(dest: Path, d: date, content: bytes = b"old"):
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"vehicle_sentiment_{d:%Y%m%d}.db.gz").write_bytes(content)


class TestBackupDatabase:
    def test_creates_gz_and_restores(self, db_file, tmp_path):
        """备份文件存在、命名正确、gzip 解开后是可查询的完整库。"""
        dest = tmp_path / "backups"
        res = backup_database(db_path=db_file, dest_dir=dest,
                              today=TODAY, offsite_dir="")

        assert res["ok"] is True
        f = Path(res["file"])
        assert f.name == "vehicle_sentiment_20260915.db.gz"
        assert f.exists() and res["size_bytes"] > 0

        restored = tmp_path / "restored.db"
        restored.write_bytes(gzip.open(f, "rb").read())
        con = sqlite3.connect(restored)
        assert con.execute("select name from vehicles").fetchall() == [("测试车",)]
        con.close()

    def test_same_day_rerun_overwrites(self, db_file, tmp_path):
        """同日重跑幂等：仍只有一份当天文件，且内容是最新库。"""
        dest = tmp_path / "backups"
        backup_database(db_path=db_file, dest_dir=dest, today=TODAY, offsite_dir="")

        con = sqlite3.connect(db_file)
        con.execute("insert into vehicles values ('v2', '第二台')")
        con.commit()
        con.close()
        res = backup_database(db_path=db_file, dest_dir=dest, today=TODAY, offsite_dir="")

        assert res["ok"] is True
        assert len(list(dest.glob("vehicle_sentiment_20260915*.db.gz"))) == 1
        restored = tmp_path / "restored.db"
        restored.write_bytes(gzip.open(Path(res["file"]), "rb").read())
        con = sqlite3.connect(restored)
        assert con.execute("select count(*) from vehicles").fetchone()[0] == 2
        con.close()

    def test_missing_db(self, tmp_path):
        res = backup_database(db_path=tmp_path / "nope.db",
                              dest_dir=tmp_path / "backups", today=TODAY)
        assert res["ok"] is False
        assert "不存在" in res["error"]

    def test_backup_while_db_open_for_write(self, db_file, tmp_path):
        """在线安全：源库保持一个写事务未提交时仍能备份（backup API 分步拷页）。"""
        con = sqlite3.connect(db_file)
        con.execute("insert into vehicles values ('v3', '未提交')")
        # 不 commit，保持连接占用
        try:
            res = backup_database(db_path=db_file, dest_dir=tmp_path / "backups",
                                  today=TODAY, offsite_dir="")
        finally:
            con.rollback()
            con.close()
        assert res["ok"] is True  # 能完成（未提交行进不进快照由 SQLite 保证一致性）


class TestOffsite:
    def test_offsite_copied(self, db_file, tmp_path):
        off = tmp_path / "offsite"
        off.mkdir()
        res = backup_database(db_path=db_file, dest_dir=tmp_path / "backups",
                              offsite_dir=off, today=TODAY)
        assert res["offsite"] == "copied"
        assert (off / "vehicle_sentiment_20260915.db.gz").exists()

    def test_offsite_dir_missing(self, db_file, tmp_path):
        res = backup_database(db_path=db_file, dest_dir=tmp_path / "backups",
                              offsite_dir=tmp_path / "nope", today=TODAY)
        assert res["offsite"] == "dir_missing"
        assert res["ok"] is True  # 异地失败不影响本地备份成功

    def test_offsite_disabled(self, db_file, tmp_path):
        """offsite_dir='' 显式禁用（不查环境变量）。"""
        res = backup_database(db_path=db_file, dest_dir=tmp_path / "backups",
                              offsite_dir="", today=TODAY)
        assert res["offsite"] == "not_configured"


class TestPruneBackups:
    def test_keeps_monthly_anchors_and_recent_dailies(self, tmp_path):
        """40 天连续日备（窗口 08-06..09-15，含 09-01 一个锚点）：
        月锚点全留、其余只留最近 14 天。"""
        for i in range(40):
            _make_old(tmp_path, TODAY - timedelta(days=i))
        deleted = _prune_backups(tmp_path, TODAY, keep_daily=14, keep_monthly=12)

        remaining = {p.name for p in tmp_path.iterdir()}
        anchors = [n for n in remaining if n[24:26] == "01"]
        assert anchors == ["vehicle_sentiment_20260901.db.gz"]  # 08-01 在 40 天窗外
        assert len(remaining) == 14 + 1  # 14 个日备 + 1 个锚点
        assert len(deleted) == 40 - 15
        # 今天必在
        assert "vehicle_sentiment_20260915.db.gz" in remaining

    def test_today_never_deleted(self, tmp_path):
        """今天的文件即使不满足任何保留条件也保留（配额 0 的极端情形）。"""
        _make_old(tmp_path, TODAY)
        deleted = _prune_backups(tmp_path, TODAY, keep_daily=0, keep_monthly=0)
        assert deleted == []
        assert (tmp_path / f"vehicle_sentiment_{TODAY:%Y%m%d}.db.gz").exists()

    def test_ignores_non_backup_files(self, tmp_path):
        """命名不符的文件（legacy/手动 .bak）不被清理。"""
        _make_old(tmp_path, TODAY - timedelta(days=60))
        legacy = tmp_path / "vehicle_sentiment.db.bak.20260912-pre-merge"
        legacy.write_bytes(b"legacy")
        _prune_backups(tmp_path, TODAY, keep_daily=14, keep_monthly=12)
        assert legacy.exists()
