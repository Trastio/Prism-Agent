import json


def sse_event(event_type: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    lines = [f"event: {event_type}", f"data: {payload}"]
    if event_type == "done":
        lines.append("")
        lines.append("[DONE]")
    else:
        lines.append("")
    return "\n".join(lines)
