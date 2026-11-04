"""daily_update 入口 env 加载钉子（2026-10-21 R40 夜跑 dry-run 疣修复）。

根因：脚本是 HTTP 编排器，收尾清理跑在本进程而本进程从未 load_dotenv，
PRISM_CLEANUP_LIVE 恒缺 → 夜跑清理恒 dry-run。修复=main() 首行 load_dotenv()。
钉住：①main() 最先加载 .env（在服务健康检查前）；②override 语义=不覆盖
monkeypatch 已设值（测试隔离不破）。
"""
import sys


def test_main_loads_dotenv_first(monkeypatch):
    from scripts import daily_update as du

    calls = {"n": 0}

    def fake_load():
        calls["n"] += 1

    def _get_raises(base, path):
        raise RuntimeError("服务不可达（测试桩）")

    monkeypatch.setattr(du, "load_dotenv", fake_load)
    monkeypatch.setattr(du, "_get", _get_raises)
    monkeypatch.setattr(sys, "argv", ["daily_update.py"])

    rc = du.main()
    assert rc == 2  # 服务不可达路径（load_dotenv 之后）
    assert calls["n"] == 1, "main() 必须最先调用 load_dotenv"


def test_dotenv_no_override_semantics(monkeypatch):
    """override=False：monkeypatch 已设的 env 不被 .env 覆盖（测试隔离保障）。"""
    import os
    monkeypatch.setenv("PRISM_CLEANUP_LIVE", "0")
    from dotenv import load_dotenv
    load_dotenv()
    assert os.environ["PRISM_CLEANUP_LIVE"] == "0"
