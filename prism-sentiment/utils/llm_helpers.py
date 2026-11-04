"""Shared helpers for LLM response parsing."""
import json
import re


def extract_json_object(raw: str) -> dict | None:
    """Extract the first JSON object from LLM response text."""
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def extract_json_array(raw: str) -> list | None:
    """Extract the first JSON array from LLM response text (tolerates ```json fences)."""
    stripped = re.sub(r'^```json\s*|\s*```$', '', raw.strip(), flags=re.MULTILINE)
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    # 兜底：提取第一个 JSON 数组
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return None
    return None
