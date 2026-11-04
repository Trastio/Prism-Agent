import json
from typing import Any


def validate_params(params: dict, schema: dict) -> tuple[bool, str]:
    """Validate tool parameters against schema. Returns (is_valid, error_message)."""
    required = schema.get("required", [])
    for key in required:
        if key not in params:
            return False, f"缺少必要参数: {key}"

    prop_schema = schema.get("properties", {})
    for key, value in params.items():
        if key in prop_schema:
            prop = prop_schema[key]
            expected_type = prop.get("type", "string")

            if expected_type == "integer":
                if not isinstance(value, int) or isinstance(value, bool):
                    return False, f"参数 {key} 应为整数，实际为 {type(value).__name__}"
                if "minimum" in prop and value < prop["minimum"]:
                    return False, f"参数 {key} 最小值为 {prop['minimum']}，实际为 {value}"
                if "maximum" in prop and value > prop["maximum"]:
                    return False, f"参数 {key} 最大值为 {prop['maximum']}，实际为 {value}"

            elif expected_type == "number":
                if not isinstance(value, (int, float)):
                    return False, f"参数 {key} 应为数字，实际为 {type(value).__name__}"

            elif expected_type == "boolean":
                if not isinstance(value, bool):
                    return False, f"参数 {key} 应为布尔值，实际为 {type(value).__name__}"

            elif expected_type == "string":
                if not isinstance(value, str):
                    return False, f"参数 {key} 应为字符串，实际为 {type(value).__name__}"
                if "minLength" in prop and len(value) < prop["minLength"]:
                    return False, f"参数 {key} 长度至少为 {prop['minLength']}"
                if "maxLength" in prop and len(value) > prop["maxLength"]:
                    return False, f"参数 {key} 长度最多为 {prop['maxLength']}"

            elif expected_type == "array":
                if not isinstance(value, list):
                    return False, f"参数 {key} 应为数组，实际为 {type(value).__name__}"
                if "minItems" in prop and len(value) < prop["minItems"]:
                    return False, f"参数 {key} 至少需要 {prop['minItems']} 个元素"
                if "maxItems" in prop and len(value) > prop["maxItems"]:
                    return False, f"参数 {key} 最多允许 {prop['maxItems']} 个元素"

    return True, ""


def safe_json_loads(text: str) -> tuple[dict, str]:
    """Parse JSON with error handling."""
    try:
        return json.loads(text), ""
    except json.JSONDecodeError as e:
        return {}, f"JSON 解析错误: {e}"
