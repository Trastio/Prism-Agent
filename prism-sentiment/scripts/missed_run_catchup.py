"""夜跑漏跑补跑（2026-10-21，S4U 提权两次被拒后的免管理员方案）。

背景：计划任务 PrismSentimentDaily 是 Interactive 形态（仅登录时运行），
无人登录的夜晚静默跳过（10-19/20 实际丢过两晚）。S4U 化需管理员，本方案
绕开提权：**onlogon 触发 + 数据新鲜度自检**——每次登录时检查"今日 03:00
的夜跑是否落了数据"，没落就后台补跑一次 daily_update --all。

判定口径（Asia/Shanghai 固定 +8，机器时区）：
- 本地 now >= 07:00（给夜跑留 3-19 点窗口；07:00 前登录不判），
  且库内 max(raw_posts.collected_at)（UTC 存储）< 今日本地 03:00 对应的
  UTC 时刻（today_local 03:00 − 8h）→ 判定夜跑没落数据 → 补跑。
- 幂等：当日标记文件 logs/catchup_<YYYYMMDD>.done 存在即跳过（登录任务
  每次登录都触发，防重复补跑）。
- 误判无害：夜跑跑了但恰好零新帖 → 补跑一次多花一轮调用，预算护栏
  （.env 1500）兜底；daily_update 自带 already_running 等待语义。

用法（计划任务 PrismSentimentCatchup，onlogon 触发，每次登录自动）：
    python scripts/missed_run_catchup.py          # 判定+必要时补跑（阻塞）
    python scripts/missed_run_catchup.py --check  # 只判定不跑（干跑测试）
"""
import argparse
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "vehicle_sentiment.db"
LOGS = ROOT / "logs"
TZ = timezone(timedelta(hours=8))  # Asia/Shanghai（机器固定时区，ECS 同款拍板）
JUDGE_AFTER_LOCAL = 7   # 本地几点起开始判定（夜跑窗 03:00 + 4h 余量）
NIGHT_LOCAL_HOUR = 3    # 夜跑时刻


def _freshness(now_local: datetime) -> tuple[bool, str]:
    """返回 (是否需要补跑, 原因)。库不可读时保守不补跑（fail-safe）。"""
    if now_local.hour < JUDGE_AFTER_LOCAL:
        return False, f"{now_local:%H:%M} 早于 {JUDGE_AFTER_LOCAL}:00，留夜跑窗口"
    # 今日本地 03:00 的 UTC 时刻 = 判新线
    night_local = now_local.replace(hour=NIGHT_LOCAL_HOUR, minute=0, second=0, microsecond=0)
    threshold_utc = night_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        last = con.execute("select max(collected_at) from raw_posts").fetchone()[0]
        con.close()
    except Exception as e:
        return False, f"库不可读（保守跳过）: {e}"
    if last is None:
        return True, "库内零帖（新库/空库）→ 补跑"
    last = str(last)[:16]
    if last >= threshold_utc:
        return False, f"数据新鲜（最新 {last} >= 夜跑线 {threshold_utc}）"
    return True, f"夜跑未落数据（最新 {last} < 夜跑线 {threshold_utc}）"


def _wait_service(timeout_s: int = 300) -> bool:
    """等服务就绪（Startup 与本任务同时触发，daily_update 健康检查会秒退 2）。"""
    import urllib.request
    for _ in range(timeout_s // 10):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/vehicles", timeout=5) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        import time as _t
        _t.sleep(10)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只判定不补跑")
    args = ap.parse_args()

    now_local = datetime.now(TZ)
    marker = LOGS / f"catchup_{now_local:%Y%m%d}.done"
    if marker.exists():
        print(f"[CATCHUP] 今日已处理（{marker.name}），跳过")
        return 0

    need, reason = _freshness(now_local)
    print(f"[CATCHUP] {now_local:%Y-%m-%d %H:%M} 判定: {'需补跑' if need else '无需'} — {reason}")
    if not need or args.check:
        return 0

    if not _wait_service():
        # 服务 5 分钟没起：写标记防本日重复，日志留痕（明日夜跑自愈）
        marker.parent.mkdir(exist_ok=True)
        marker.write_text(f"{now_local.isoformat()} 服务未就绪放弃\n", encoding="utf-8")
        print("[CATCHUP] 服务 5 分钟未就绪，放弃本日补跑")
        return 2

    log_file = LOGS / f"catchup_{now_local:%Y%m%d}.log"
    print(f"[CATCHUP] 启动补跑 → {log_file}（daily_update --all，阻塞至完成）")
    marker.parent.mkdir(exist_ok=True)
    marker.write_text(f"{now_local.isoformat()} {reason}\n", encoding="utf-8")
    with open(log_file, "ab") as lf:
        # CREATE_NO_WINDOW：Startup/任务环境不弹黑框；等待完成（onlogon 任务
        # 无界面，阻塞无妨——补跑约 90 分钟）
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "daily_update.py"), "--all"],
            cwd=str(ROOT), stdout=lf, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    print(f"[CATCHUP] 补跑结束 exit={r.returncode}")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
