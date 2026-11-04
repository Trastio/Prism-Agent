"""审计 P2-4：daily_update 撞上互动刷新不假完成——等刷新结束后重发采集。

背景：/collect 返回 already_running(phase=refreshing) 时，原轮询把 refreshing
当终态 → 立即"完成"跳车，该车当日增量实际没跑（refresh 不抓新帖）。
"""
import sys

import scripts.daily_update as du


def test_wait_refresh_done_returns_when_phase_leaves(monkeypatch):
    """refreshing→calculating→completed：先 sleep 后查（与 main 轮询同风格），
    2 个在途相位各睡一轮，第三轮睡完查到 completed 跳出。"""
    phases = iter(["refreshing", "calculating", "completed"])
    sleeps = []
    monkeypatch.setattr(du.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(du, "_get", lambda base, path, timeout=30: {"phase": next(phases)})
    du._wait_refresh_done("http://x", "v1", timeout_min=1)
    assert len(sleeps) == 3


def test_wait_refresh_done_gives_up_on_timeout(monkeypatch):
    """一直 refreshing：超时放弃不死循环（time.time 用计数器推进）。"""
    t = {"now": 0.0}
    monkeypatch.setattr(du.time, "time", lambda: t["now"])
    monkeypatch.setattr(du.time, "sleep", lambda s: t.__setitem__("now", t["now"] + s))
    monkeypatch.setattr(du, "_get", lambda base, path, timeout=30: {"phase": "refreshing"})
    du._wait_refresh_done("http://x", "v1", timeout_min=1)
    assert t["now"] >= 60  # deadline（60s）到了才返回


def test_main_recollected_after_refresh(monkeypatch, capsys):
    """main 撞 refreshing：等刷新 → 重发 /collect → 轮询到完成（不假完成跳车）。"""
    posts = []

    def fake_post(base, path, timeout=60):
        posts.append(path)
        if path.endswith("/collect"):
            if posts.count(path) == 1:
                return {"status": "already_running", "phase": "refreshing"}
            return {"status": "started", "phase": "collecting"}
        return {}

    def fake_get(base, path, timeout=30):
        if path == "/api/vehicles":
            return [{"id": "v1", "name": "M03", "status": "active"}]
        if path.endswith("/pipeline-status"):
            # 第一次给 _wait_refresh_done（跳出等待），第二次给主轮询（终态）
            return {"phase": "completed"}
        return {}

    monkeypatch.setattr(du, "_post", fake_post)
    monkeypatch.setattr(du, "_get", fake_get)
    monkeypatch.setattr(du.time, "sleep", lambda s: None)
    # 2026-10-16 事故补丁：main 收尾三件套必须全补——漏 _run_post_cleanup 曾致
    # 全量套件真删生产库（active 老帖 5,248）。新收尾一律加到这里。
    monkeypatch.setattr(du, "_run_post_cleanup", lambda: None)
    monkeypatch.setattr(du, "_run_backup", lambda: True)
    monkeypatch.setattr(sys, "argv", ["daily_update.py"])  # argparse 隔离 pytest 参数

    rc = du.main()
    assert rc == 0
    collect_calls = [p for p in posts if p.endswith("/collect")]
    assert len(collect_calls) == 2  # 第一次 already_running + 等刷新后重发


# ── T5/R22（2026-10-16）：--all 全量直通，频率分层删除 ────────────────────

def _fleet_25() -> list[dict]:
    """镜像生产车池：15 active + 6 paused + 4 inactive。"""
    cars = ([{"id": f"a{i}", "name": f"active车{i}", "status": "active"}
             for i in range(15)]
            + [{"id": f"p{i}", "name": f"paused车{i}", "status": "paused"}
               for i in range(6)]
            + [{"id": f"x{i}", "name": f"inactive车{i}", "status": "inactive"}
               for i in range(4)])
    return cars


def _run_main_with(argv: list[str], vehicles: list[dict], monkeypatch, capsys):
    """公共脚手架：mock 全部外呼与收尾三件套，跑 main 返回 (rc, collect_ids)。"""
    collected = []

    def fake_post(base, path, timeout=60):
        if path.endswith("/collect"):
            collected.append(path.split("/")[-2])
            return {"status": "started", "phase": "collecting"}
        return {}

    monkeypatch.setattr(du, "_post", fake_post)
    monkeypatch.setattr(du, "_get", lambda base, path, timeout=30:
                        vehicles if path == "/api/vehicles"
                        else {"phase": "completed"})
    monkeypatch.setattr(du.time, "sleep", lambda s: None)
    monkeypatch.setattr(du, "_run_post_cleanup", lambda: None)
    monkeypatch.setattr(du, "_run_backup", lambda: True)
    monkeypatch.setattr(sys, "argv", ["daily_update.py"] + argv)
    rc = du.main()
    return rc, collected, capsys.readouterr().out


def test_all_targets_all_15_active(monkeypatch, capsys):
    """--all：15 台 active 全跑，paused/inactive 一台不碰（R22 无频率跳过）。"""
    rc, collected, out = _run_main_with(["--all"], _fleet_25(), monkeypatch, capsys)
    assert rc == 0
    assert len(collected) == 15
    assert set(collected) == {f"a{i}" for i in range(15)}      # 无 paused/inactive
    assert "待更新 15 车" in out
    assert "[FREQ]" not in out                                   # 分层跳过路径已删


def test_all_equals_default_semantics(monkeypatch, capsys):
    """缺省与 --all 同义（同为全量 active）——计划任务旗标只是显式化。"""
    rc1, c1, _ = _run_main_with([], _fleet_25(), monkeypatch, capsys)
    rc2, c2, _ = _run_main_with(["--all"], _fleet_25(), monkeypatch, capsys)
    assert rc1 == rc2 == 0 and c1 == c2 and len(c1) == 15


def test_vehicle_substring_filter_still_works(monkeypatch, capsys):
    """--vehicle 子串过滤保留（两态通用）。"""
    rc, collected, _ = _run_main_with(["--vehicle", "active车3"], _fleet_25(),
                                      monkeypatch, capsys)
    assert rc == 0 and collected == ["a3"]
