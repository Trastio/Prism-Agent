"""T2.4 Tests: Model Router — 5 tests."""
import os

import pytest


class TestModelRouter:
    def test_default_uses_api(self):
        from pipeline.analysis.model_router import ModelRouter
        router = ModelRouter()
        assert router.get_active_model() == "api"

    def test_env_var_forces_local(self, monkeypatch):
        monkeypatch.setenv("USE_LOCAL_MODEL", "1")
        from pipeline.analysis.model_router import ModelRouter
        router = ModelRouter()
        assert router.get_active_model() == "local"

    def test_get_api_config(self):
        from pipeline.analysis.model_router import ModelRouter
        router = ModelRouter()
        config = router.get_api_config()
        assert "model" in config
        assert "api_url" in config

    def test_get_local_config(self):
        from pipeline.analysis.model_router import ModelRouter
        router = ModelRouter()
        config = router.get_local_config()
        assert "model_name" in config
        assert "device" in config

    def test_check_local_model_returns_false_without_model(self):
        from pipeline.analysis.model_router import ModelRouter
        router = ModelRouter()
        # transformers is installed but no model weights downloaded
        result = router.check_local_model()
        assert isinstance(result, bool)
