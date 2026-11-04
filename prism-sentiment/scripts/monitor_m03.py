"""监控 m03（小鹏MONA M03）采集任务。

每 5 秒轮询：
1. 服务存活（GET /api/vehicles 200 OK）
2. m03 progress（阶段 + 平台状态 + env_warning）
3. m03 collection_status（status / error / last_collected_at）
4. 服务 stdout 抓 Traceback

输出到 logs/monitor.log + stdout；状态变化时打印，等异常时大声喊。
不动任何 mutation API，纯只读。
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

VEHICLE_ID = "6e79db2d-8452-42a8-a53e-644d47000548"
VEHICLE_NAME = "小鹏MONA M03"
BASE = "http://127.0.0.1:8000"
LOG_FILE = Path("logs/monitor.log")
LOG_FILE.parent.mkdir(exist_ok=True)


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_json(path: str, timeout: int = 30) -> dict | None:
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"_error": str(e)}


def main() -> int:
    log(f"=== 开始监控 {VEHICLE_NAME} ({VEHICLE_ID}) ===")
    last_progress_signature = None
    last_status_signature = None
    stuck_count = 0
    last_change_at = time.time()

    while True:
        now = time.time()
        ts = time.strftime("%H:%M:%S")

        # 1. 服务存活
        veh = get_json("/api/vehicles")
        if veh is None or "_error" in veh:
            log(f"❌ 服务异常：{veh}")
            time.sleep(5)
            continue

        # 2. progress
        prog = get_json(f"/api/vehicles/{VEHICLE_ID}/progress")
        if prog is None or "_error" in prog:
            log(f"⚠️  progress API 异常: {prog}")
            time.sleep(5)
            continue

        # 摘要化 progress（用于检测变化）
        prog_summary = {
            "overall_phase": prog.get("overall_phase"),
            "current_step": prog.get("current_step"),
            "posts_collected": prog.get("posts_collected"),
            "posts_enriched": prog.get("posts_enriched"),
            "analyzed": prog.get("analyzed"),
            "error": prog.get("error"),
            "env_warning": prog.get("env_warning"),
            "platforms": {k: v.get("phase") for k, v in (prog.get("platforms") or {}).items()},
        }
        prog_sig = json.dumps(prog_summary, sort_keys=True, ensure_ascii=False)

        if prog_sig != last_progress_signature:
            log(f"📊 progress 变化: {json.dumps(prog_summary, ensure_ascii=False)}")
            last_progress_signature = prog_sig
            last_change_at = now
            stuck_count = 0
        else:
            stuck_count += 1
            # 仅在未完成时报警（completed 状态允许稳定无变化）
            if stuck_count == 6 and (now - last_change_at) > 60:
                if prog_summary.get("overall_phase") != "completed":
                    log(f"⚠️  progress 60s 未变化（overall_phase={prog_summary.get('overall_phase')}, step={prog_summary.get('current_step')})")
                else:
                    stuck_count = 0  # completed 状态不计数，避免持续告警

        # 3. collection_status（DB 视角）— API 返回 list
        cs = get_json(f"/api/vehicles/{VEHICLE_ID}/collection-status")
        if isinstance(cs, list) and cs:
            # 取最新一条（按 last_collected_at）
            cs_latest = max(cs, key=lambda x: x.get("last_collected_at") or "")
            cs_summary = {
                "status": cs_latest.get("status"),
                "source": cs_latest.get("source"),
                "mode": cs_latest.get("mode"),
                "posts_collected": cs_latest.get("posts_collected"),
                "error": (cs_latest.get("error_message") or "")[:200],
                "last_collected_at": cs_latest.get("last_collected_at"),
            }
            cs_sig = json.dumps(cs_summary, sort_keys=True, ensure_ascii=False)
            if cs_sig != last_status_signature:
                log(f"💾 collection_status 变化: {json.dumps(cs_summary, ensure_ascii=False)}")
                last_status_signature = cs_sig

        time.sleep(10)


if __name__ == "__main__":
    sys.exit(main())