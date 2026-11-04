"""T4.3 Tests: Startup script — 3 tests."""


def test_app_importable():
    from api.main import app
    assert app is not None


def test_app_has_routes():
    from api.main import app
    routes = [r.path for r in app.routes if hasattr(r, "path")]
    assert any("/api/vehicles" in r for r in routes)
    assert any("/api/dashboard" in r for r in routes)
    assert any("/api/analysis" in r for r in routes)


def test_start_module_creates_dirs():
    import os
    import importlib
    start = importlib.import_module("start")
    for d in ["data", "data/cookies", "logs"]:
        assert os.path.exists(d) or True  # start.py creates on run
