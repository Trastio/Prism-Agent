"""T3 Tests: 30 天保留线老帖物理清理（方案 R40/R42）。

核心断言：边界日期（30 天龄保留/31 天删）、paused 豁免、三表级联、
published_at NULL 不删、dry-run 零副作用、引用审计（event_groups/watch_items）、
--vehicle 过滤。用临时 sqlite 库直构最小 schema（清理器走 raw sqlite3，
不走 ORM——与被测实现同路）。
"""
import json
import sqlite3
from datetime import date, timedelta

import pytest

from scripts.cleanup_posts import (
    audit_references,
    cutoff_date,
    prune_dangling_refs,
    run_cleanup,
    select_stale_posts,
)

TODAY = date(2026, 10, 16)


def _mkdb(tmp_path, seed=True):
    con = sqlite3.connect(tmp_path / "t.db")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE vehicles (id TEXT PRIMARY KEY, name TEXT, status TEXT);
        CREATE TABLE raw_posts (id TEXT PRIMARY KEY, vehicle_id TEXT,
                                published_at TEXT);
        CREATE TABLE post_comments (id TEXT PRIMARY KEY, post_id TEXT);
        CREATE TABLE analyzed_posts (post_id TEXT PRIMARY KEY);
        CREATE TABLE event_groups (id TEXT, vehicle_id TEXT, event_tag TEXT,
                                   start_date TEXT, end_date TEXT, post_count INTEGER,
                                   post_ids TEXT);
        CREATE TABLE watch_items (id TEXT, title TEXT, source_type TEXT,
                                  source_ref TEXT, vehicle_id TEXT);
        """
    )
    if seed:
        con.execute("INSERT INTO vehicles VALUES ('v1','银河E5','active')")
        con.execute("INSERT INTO vehicles VALUES ('v2','星愿','paused')")
        # p_old=31 天龄（删）p_edge=恰 30 天（留）p_new=1 天（留）p_null=无日期（留）
        old, edge = TODAY - timedelta(days=31), TODAY - timedelta(days=30)
        con.executemany(
            "INSERT INTO raw_posts VALUES (?,?,?)",
            [("p_old", "v1", old.isoformat()),
             ("p_edge", "v1", edge.isoformat()),
             ("p_new", "v1", (TODAY - timedelta(days=1)).isoformat()),
             ("p_null", "v1", None),
             ("p_paused", "v2", old.isoformat())])
        con.executemany(
            "INSERT INTO post_comments VALUES (?,?)",
            [("c1", "p_old"), ("c2", "p_old"), ("c3", "p_edge")])
        con.execute("INSERT INTO analyzed_posts VALUES ('p_old')")
    con.commit()
    return con


class TestBoundary:
    def test_31_day_deleted_30_day_kept(self, tmp_path):
        con = _mkdb(tmp_path)
        r = run_cleanup(con=con, today=TODAY)
        ids = {row[0] for row in con.execute("SELECT id FROM raw_posts")}
        assert ids == {"p_edge", "p_new", "p_null", "p_paused"}

    def test_cutoff_semantics(self):
        assert cutoff_date(TODAY, 30) == TODAY - timedelta(days=30)

    def test_null_published_not_deleted(self, tmp_path):
        con = _mkdb(tmp_path)
        run_cleanup(con=con, today=TODAY)
        assert con.execute(
            "SELECT count(*) FROM raw_posts WHERE id='p_null'").fetchone()[0] == 1


class TestPausedExemption:
    def test_paused_stock_frozen(self, tmp_path):
        con = _mkdb(tmp_path)
        r = run_cleanup(con=con, today=TODAY)
        assert con.execute(
            "SELECT count(*) FROM raw_posts WHERE id='p_paused'").fetchone()[0] == 1
        assert r["paused_kept"] == {"星愿": 1}


class TestCascade:
    def test_comments_and_analyzed_deleted_together(self, tmp_path):
        con = _mkdb(tmp_path)
        r = run_cleanup(con=con, today=TODAY)
        assert r["posts"] == 1
        assert r["comments_deleted"] == 2          # c1/c2 随 p_old 删，c3 留
        assert r["analyzed_deleted"] == 1
        assert con.execute(
            "SELECT count(*) FROM post_comments WHERE post_id='p_old'").fetchone()[0] == 0
        assert con.execute(
            "SELECT count(*) FROM post_comments WHERE id='c3'").fetchone()[0] == 1


class TestDryRunAndEmpty:
    def test_dry_run_no_side_effects(self, tmp_path):
        con = _mkdb(tmp_path)
        r = run_cleanup(dry_run=True, con=con, today=TODAY)
        assert r["posts"] == 1                       # 清单里有
        assert con.execute("SELECT count(*) FROM raw_posts").fetchone()[0] == 5  # 一行没删

    def test_empty_db(self, tmp_path):
        con = _mkdb(tmp_path, seed=False)
        r = run_cleanup(con=con, today=TODAY)
        assert r["posts"] == 0 and r["references"] == {"event_groups": [], "watch_items": []}


class TestVehicleFilter:
    def test_vehicle_substring_filter(self, tmp_path):
        con = _mkdb(tmp_path)
        r = run_cleanup(vehicle="不存在的车", con=con, today=TODAY)
        assert r["posts"] == 0


class TestReferenceAudit:
    def test_event_and_watch_hits_reported(self, tmp_path):
        con = _mkdb(tmp_path)
        con.execute(
            "INSERT INTO event_groups VALUES ('eg1','v1','降价维权','2026-09-01',"
            "'2026-09-20',2,'[\"p_old\",\"p_new\"]')")
        con.execute(
            "INSERT INTO watch_items VALUES ('w1','热帖关注','hot_post','p_old','v1')")
        con.execute(
            "INSERT INTO watch_items VALUES ('w2','事件关注','event','eg1','v1')")  # 非 post 引用，不报
        con.commit()
        refs = audit_references(con, {"p_old"})
        assert len(refs["event_groups"]) == 1
        assert refs["event_groups"][0]["dangling"] == 1
        assert refs["event_groups"][0]["total"] == 2
        assert len(refs["watch_items"]) == 1
        assert refs["watch_items"][0]["source_ref"] == "p_old"

    def test_no_hits_clean(self, tmp_path):
        con = _mkdb(tmp_path)
        refs = audit_references(con, {"p_old"})
        assert refs == {"event_groups": [], "watch_items": []}


class TestBatchDelete:
    def test_over_500_posts_batched(self, tmp_path):
        """批量分片路径：>500 帖也整批删净（DELETE IN 上限保护）。"""
        con = _mkdb(tmp_path, seed=False)
        con.execute("INSERT INTO vehicles VALUES ('v1','大pool','active')")
        old = (TODAY - timedelta(days=60)).isoformat()
        con.executemany(
            "INSERT INTO raw_posts VALUES (?,?,?)",
            [(f"p{i:04d}", "v1", old) for i in range(1200)])
        con.commit()
        r = run_cleanup(con=con, today=TODAY)
        assert r["posts"] == 1200
        assert con.execute("SELECT count(*) FROM raw_posts").fetchone()[0] == 0


class TestDailyUpdateHook:
    def test_hook_importable(self):
        """挂接函数可导入（import 级冒烟，不起服务）。"""
        from scripts.daily_update import _run_post_cleanup
        assert callable(_run_post_cleanup)

    def test_hook_defaults_to_dry_run(self, monkeypatch, capsys):
        """2026-10-16 事故回归：无 env 时钩子必须走 dry-run（防测试漏补丁真删生产库）。"""
        import scripts.daily_update as du
        import scripts.cleanup_posts as cp
        monkeypatch.delenv("PRISM_CLEANUP_LIVE", raising=False)
        called = {}
        monkeypatch.setattr(cp, "run_cleanup",
                            lambda dry_run=True, **kw: called.update(dry_run=dry_run) or {
                                "dry_run": dry_run, "posts": 3, "per_vehicle": {},
                                "paused_kept": {}, "references": {"event_groups": [], "watch_items": []},
                                "comments_deleted": 0, "analyzed_deleted": 0,
                                "retention_days": 30, "cutoff": "x", "elapsed_s": 0.0})
        monkeypatch.setattr(cp, "_print_report", lambda r: None)
        du._run_post_cleanup()
        assert called["dry_run"] is True

    def test_hook_live_only_with_env(self, monkeypatch):
        import scripts.daily_update as du
        import scripts.cleanup_posts as cp
        monkeypatch.setenv("PRISM_CLEANUP_LIVE", "1")
        called = {}
        monkeypatch.setattr(cp, "run_cleanup",
                            lambda dry_run=True, **kw: called.update(dry_run=dry_run) or {
                                "dry_run": dry_run, "posts": 0, "per_vehicle": {},
                                "paused_kept": {}, "references": {"event_groups": [], "watch_items": []},
                                "comments_deleted": 0, "analyzed_deleted": 0,
                                "retention_days": 30, "cutoff": "x", "elapsed_s": 0.0})
        monkeypatch.setattr(cp, "_print_report", lambda r: None)
        du._run_post_cleanup()
        assert called["dry_run"] is False


class TestEventGroupPruning:
    """Step6 S3：live 删除事务内修剪 event_groups.post_ids（空组保留）。"""

    def _seed_groups(self, con):
        con.executemany(
            "INSERT INTO event_groups VALUES (?,?,?,?,?,?,?)",
            [("eg-mixed", "v1", "银河E5提车潮", "2026-01-01", "2026-10-01", 2,
              '["p_old", "p_edge"]'),          # 一删一留 → 修剪剩 p_edge
             ("eg-paused", "v2", "星愿热议", "2026-01-01", "2026-10-01", 2,
              '["p_paused", "p_old"]'),        # paused 帖不删 → 剩 p_paused
             ("eg-allgone", "v1", "已完结话题", "2026-01-01", "2026-09-01", 1,
              '["p_old"]'),                    # 全删 → 空组保留 []
             ("eg-untouched", "v1", "近期话题", "2026-10-01", "2026-10-10", 1,
              '["p_new"]')])                   # 无交集 → 原样不动
        con.commit()

    def _group_ids(self, con, gid):
        import json as _json
        row = con.execute("SELECT post_ids FROM event_groups WHERE id=?", (gid,)).fetchone()
        return _json.loads(row["post_ids"])

    def test_live_prunes_deleted_ids_keeps_group_row(self, tmp_path):
        con = _mkdb(tmp_path)
        self._seed_groups(con)
        r = run_cleanup(dry_run=False, con=con, today=TODAY)
        assert r["event_groups_pruned"] == 3           # untouched 组不计
        assert self._group_ids(con, "eg-mixed") == ["p_edge"]
        assert self._group_ids(con, "eg-paused") == ["p_paused"]  # paused 帖不被修剪
        assert self._group_ids(con, "eg-allgone") == []  # 空组保留（话题记录）
        assert self._group_ids(con, "eg-untouched") == ["p_new"]
        assert con.execute("SELECT count(*) FROM event_groups").fetchone()[0] == 4

    def test_live_prune_syncs_post_count(self, tmp_path):
        """2026-10-20：修剪时 post_count 同步 len(kept)——轻卡 ≥2 兜底判据不漂移。"""
        con = _mkdb(tmp_path)
        self._seed_groups(con)
        run_cleanup(dry_run=False, con=con, today=TODAY)
        for gid, expect in [("eg-mixed", 1), ("eg-paused", 1), ("eg-allgone", 0),
                            ("eg-untouched", 1)]:
            row = con.execute(
                "SELECT post_count FROM event_groups WHERE id=?", (gid,)).fetchone()
            assert row["post_count"] == expect, gid

    def test_dry_run_leaves_event_groups_untouched(self, tmp_path):
        con = _mkdb(tmp_path)
        self._seed_groups(con)
        r = run_cleanup(dry_run=True, con=con, today=TODAY)
        assert r["event_groups_pruned"] == 0
        assert self._group_ids(con, "eg-mixed") == ["p_old", "p_edge"]  # 原样
        assert len(r["references"]["event_groups"]) == 3   # 审计仍报将悬空（供过目）


class TestPruneDanglingRefs:
    """2026-10-20 存量修复：--prune-only 剔除库中已不存在的 id + post_count 对齐。

    背景：10-16 首删执行时 S3 prune 未合入，存量悬空引用从未修剪
    （T7 21 事件全中招）；本路径幂等、零删帖、不需 LIVE 门。
    """

    def _seed(self, con):
        con.executemany(
            "INSERT INTO event_groups VALUES (?,?,?,?,?,?,?)",
            [("eg-ghost", "v1", "旧话题", "2026-09-01", "2026-10-01", 99,
              '["p_new", "p_ghost", "p_ghost2"]'),   # 2 悬空 id + count 漂移
             ("eg-clean", "v1", "干净话题", "2026-10-01", "2026-10-10", 1,
              '["p_new"]'),                          # 干净行不动
             ("eg-drift", "v1", "计数漂移", "2026-10-01", "2026-10-10", 5,
              '["p_new"]')])                         # 仅 post_count 漂移
        con.commit()

    def test_dry_run_reports_without_writing(self, tmp_path):
        con = _mkdb(tmp_path)
        self._seed(con)
        s = prune_dangling_refs(con, dry_run=True)
        assert s["groups_pruned"] == 1 and s["ids_removed"] == 2
        assert s["counts_fixed"] == 1
        row = con.execute("SELECT post_ids FROM event_groups WHERE id='eg-ghost'").fetchone()
        assert "p_ghost" in row["post_ids"]  # 未写入

    def test_live_removes_and_syncs(self, tmp_path):
        con = _mkdb(tmp_path)
        self._seed(con)
        s = prune_dangling_refs(con, dry_run=False)
        assert s["groups_pruned"] == 1 and s["ids_removed"] == 2
        g = con.execute("SELECT post_ids, post_count FROM event_groups WHERE id='eg-ghost'").fetchone()
        assert json.loads(g["post_ids"]) == ["p_new"]
        assert g["post_count"] == 1
        d = con.execute("SELECT post_count FROM event_groups WHERE id='eg-drift'").fetchone()
        assert d["post_count"] == 1  # 仅漂移行也只对齐 count
        c = con.execute("SELECT post_ids, post_count FROM event_groups WHERE id='eg-clean'").fetchone()
        assert json.loads(c["post_ids"]) == ["p_new"] and c["post_count"] == 1  # 原样

    def test_idempotent(self, tmp_path):
        con = _mkdb(tmp_path)
        self._seed(con)
        prune_dangling_refs(con, dry_run=False)
        s2 = prune_dangling_refs(con, dry_run=False)
        assert s2["groups_pruned"] == 0 and s2["ids_removed"] == 0 and s2["counts_fixed"] == 0
