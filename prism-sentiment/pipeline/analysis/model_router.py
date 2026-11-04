import json
import os


class ModelRouter:
    def __init__(self):
        self._secrets = self._load_secrets()

    def _load_secrets(self) -> dict:
        path = ".secrets"
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def check_local_model(self) -> bool:
        try:
            from transformers import AutoModelForCausalLM
            return True
        except ImportError:
            return False

    def get_active_model(self) -> str:
        if os.getenv("USE_LOCAL_MODEL", "").strip() == "1" and self.check_local_model():
            return "local"
        return "api"

    def get_api_config(self) -> dict:
        ds = self._secrets.get("deepseek", {})
        return {
            "model": ds.get("model", "deepseek-chat"),
            "api_url": ds.get("api_url", "https://api.deepseek.com/v1/chat/completions"),
            "api_key": ds.get("api_key", ""),
        }

    def get_local_config(self) -> dict:
        return {
            "model_name": os.getenv("LOCAL_MODEL_NAME", "Qwen/Qwen3-4B-Instruct-2507"),
            "device": os.getenv("LOCAL_MODEL_DEVICE", "cuda"),
        }
