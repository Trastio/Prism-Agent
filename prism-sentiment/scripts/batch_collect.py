"""批量采集脚本（串行触发 trigger 端点）。

修了 stall 误判：看 overall_phase 变化而非 posts_collected。
trigger 端点是异步的，返回 started 后采集实际跑 30-40 分钟，
评论 ABSA 阶段 posts 不涨但 phase 会从 collecting→analyzing→calculating→completed。

用法：
    python scripts/batch_collect.py [--exclude 元UP,元PLUS,...] [--only 0帖车]

环境：
    - 服务必须在跑（http://127.0.0.1:8000）
    - TikHub 余额充足
    - PYTHONIOENCODING=utf-8（.env 已配，新终端自动生效）

注意：
    - trigger 端点异步返回，本脚本只负责触发 + 等完成
    - 每辆 80 分钟超时保护（含采集+帖子分析+评论 ABSA）
    - DB 锁会导致采集失败，确保没有其他进程占 DB 连接
"""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
# 80 分钟超时（含评论 ABSA 全量循环，大车可能跑 1h+）
STALL_PHASE_TIMEOUT = 4800  # 单个 phase 不变化超过此秒数则跳过
POLL_INTERVAL = 30


def list_vehicles(exclude: set[str], only_zero: bool) -> list[tuple[str, str]]:
    con = sqlite3.connect("data/vehicle_sentiment.db")
    cur = con.cursor()
    rows = cur.execute("SELECT id, name FROM vehicles ORDER BY name").fetchall()
    out = []
    for vid, name in rows:
        if name in exclude:
            continue
        if only_zero:
            cnt = cur.execute(
                "SELECT COUNT(*) FROM raw_posts WHERE vehicle_id=?", (vid,)
            ).fetchone()[0]
            if cnt > 0:
                continue
        out.append((vid, name))
    con.close()
    return out


def trigger(vid: str) -> dict:
    req = urllib.request.Request(
        f"{BASE}/api/vehicles/{vid}/collect",
        method="POST",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        return {"error": str(e)}


def status(vid: str) -> dict:
    try:
        return json.loads(
            urllib.request.urlopen(
                f"{BASE}/api/vehicles/{vid}/progress", timeout=10
            ).read()
        )
    except Exception as e:
        return {"error": str(e)}


def collect_one(vid: str, name: str) -> bool:
    """触发采集并等待完成。返回 True 表示采到帖，False 表示 0 帖或失败。"""
    print(f"=== {name} ({vid[:8]}) ===", flush=True)
    st = status(vid)
    ph = st.get("overall_phase", "")
    if ph in ("collecting", "analyzing", "calculating"):
        print(f"  已在运行 phase={ph}, 等完成", flush=True)
    else:
        r = trigger(vid)
        err = r.get("error") or r.get("err")
        print(f"  trigger: {r.get('status', '')} err={err}", flush=True)
        if err:
            return False

    # stall 判断：看 overall_phase 变化，不看 posts（评论 ABSA 阶段 posts 不涨）
    last_phase = None
    phase_stall = 0
    while True:
        time.sleep(POLL_INTERVAL)
        st = status(vid)
        ph = st.get("overall_phase", "")
        posts = st.get("posts_collected", 0)
        err = st.get("error")
        print(
            f"  [{time.strftime('%H:%M:%S')}] phase={ph} posts={posts} "
            f"err={err[:60] if err else None}",
            flush=True,
        )
        if err:
            print(f"  ERROR, 跳过", flush=True)
            return False
        if ph in ("completed", "idle"):
            print(f"  DONE posts={posts}", flush=True)
            return posts > 0
        # phase 不变才算 stall（之前 bug：看 posts 不涨就跳，误判评论 ABSA 阶段）
        if ph == last_phase:
            phase_stall += POLL_INTERVAL
            if phase_stall >= STALL_PHASE_TIMEOUT:
                print(
                    f"  STALL {STALL_PHASE_TIMEOUT}s phase={ph}, 跳过", flush=True
                )
                return False
        else:
            phase_stall = 0
        last_phase = ph


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--exclude",
        default="元UP,元PLUS,零跑A10,华境s",
        help="逗号分隔的排除车型名",
    )
    parser.add_argument(
        "--only-zero",
        action="store_true",
        help="只采 0 帖的车（跳过已有库存）",
    )
    args = parser.parse_args()

    exclude = set(s.strip() for s in args.exclude.split(",") if s.strip())
    targets = list_vehicles(exclude, args.only_zero)
    print(f"[START] 待采集 {len(targets)} 辆", flush=True)
    for vid, name in targets:
        print(f"  {name} ({vid[:8]})", flush=True)

    results = []
    for i, (vid, name) in enumerate(targets):
        print(f"\n[{i + 1}/{len(targets)}]", flush=True)
        ok = collect_one(vid, name)
        results.append((name, ok))

    print(f"\n[ALL DONE] {len(targets)} 辆处理完", flush=True)
    print("\n结果汇总:", flush=True)
    for name, ok in results:
        print(f"  {'✅' if ok else '⚠️'} {name}", flush=True)


if __name__ == "__main__":
    main()
