"""Shared configuration loader."""
import json
import os

_SECRETS_PATH = os.getenv("SECRETS_PATH", ".secrets")


def load_api_config() -> dict:
    if not os.path.exists(_SECRETS_PATH):
        return {}
    with open(_SECRETS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def env_int(name: str, default: int) -> int:
    """env 整数读取：未设/空白回退默认，非法值回退默认。

    统一替代各模块本地 ``_env_int``。调用时读取（非 import 时），故在函数
    体内调用可被 ``monkeypatch.setenv`` 覆盖；模块级常量则在 import 时定型。
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_str(name: str, default: str) -> str:
    """env 字符串读取：未设回退默认。"""
    return os.getenv(name, default)
