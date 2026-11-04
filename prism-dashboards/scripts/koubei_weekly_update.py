"""口碑周更入口（口碑周更增量采集 change，2026-11-01 拍板全池周更）。

对标舆情 daily_update.py + missed_run_catchup.py 形态：
- 流程：already_running 锁 → sqlite backup API 自动备份 → 调 recollect 增量模式
  （--mode=incremental，全池名单）→ collection_runs 台账落一行 → 日志追加
- 退出码（与舆情同风格）：0=成功（含 budget_capped 正常终态）/ 1=部分车系失败 /
  2=守卫或环境拦截（备份失败/目标库无效）/ 3=无事可做
- 目标库解析（打错栈防呆，横幅打印绝对路径+当前行数）：
  --db > env PRISM_KOUBEI_DB > deploy/data/autohome.db（存在时，容器生产库）
  > prism-dashboards/data/autohome.db（开发库回退）
- weekly_progress 滚动：跑前旧文件改名 weekly_progress_{ts}.jsonl，保留最近 8 份
- --catchup：onlogon 补跑判定（missed_run_catchup 同款免管理员方案）——
  时区固定 Asia/Shanghai(+8)；本地 ≥07:00 才判定；最近一次 mode=weekly 且
  status=success 的 finished_at 距今 >8 天 → 补跑；幂等日标记
  logs/koubei_catchup_<YYYYMMDD>.done 存在即跳过；--check 只判定不跑

用法：
  python scripts/koubei_weekly_update.py                 # dry-run（零写入零出网）
  python scripts/koubei_weekly_update.py --live          # 真采（自动备份先行；缺省不限制新入库条数）
  python scripts/koubei_weekly_update.py --live --budget-reviews 500   # 需要限流时自定上限
  python scripts/koubei_weekly_update.py --catchup       # 登录补跑判定+必要时跑
  python scripts/koubei_weekly_update.py --catchup --check   # 只判定不跑
"""
import argparse
import asyncio
import io
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # prism-dashboards/
PROJECT_ROOT = ROOT.parent                              # Prism-Agent/
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# GBK 控制台编码守卫：照抄 recollect_koubei_with_full.py 头部
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

TZ_CN = timezone(timedelta(hours=8))   # Asia/Shanghai 固定（missed_run_catchup 同款）
CATCHUP_JUDGE_AFTER_LOCAL = 7          # 本地几点起开始判定（夜跑窗 04:00 + 3h 余量）
CATCHUP_STALE_DAYS = 8                 # 周更过期阈值（7 天周期 + 1 天余量）
LOGS_DIR = ROOT / "logs"
LOCK_PATH = LOGS_DIR / "koubei-weekly.lock"
LOG_PATH = LOGS_DIR / "koubei-weekly.log"
KEEP_ROLLED = 8                         # weekly_progress_{ts}.jsonl 保留份数


# ---------------- 目标库解析（打错栈防呆） ----------------

def resolve_db_path(cli_db: str | None) -> Path:
    """--db > PRISM_KOUBEI_DB > deploy/data/autohome.db（存在）> 开发库回退。"""
    if cli_db:
        p = Path(cli_db)
    elif os.environ.get("PRISM_KOUBEI_DB"):
        p = Path(os.environ["PRISM_KOUBEI_DB"])
    else:
        prod = PROJECT_ROOT / "deploy" / "data" / "autohome.db"
        p = prod if prod.is_file() else (ROOT / "data" / "autohome.db")
    if not p.is_file():
        raise FileNotFoundError(f"目标库不存在: {p}")
    return p


def _db_review_count(db_path: Path) -> int:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM owner_reviews").fetchone()[0])
    finally:
        conn.close()


def _print_banner(db_path: Path, live: bool):
    """横幅：目标库绝对路径 + 当前行数——v1.2 打错栈事故的防呆（G3 同款思路）。"""
    n = _db_review_count(db_path)
    print("=" * 60, flush=True)
    print(f"[koubei-weekly] mode={'LIVE' if live else 'DRY-RUN'} 目标库: {db_path}", flush=True)
    print(f"[koubei-weekly] owner_reviews 当前 {n} 条 · 数据目录 {db_path.parent}", flush=True)
    print("=" * 60, flush=True)


# ---------------- 备份（sqlite backup API，禁拷热文件） ----------------

def backup_db(db_path: Path) -> Path:
    """live 前自动一致性备份到 {库目录}/backups/autohome-pre-weekly-{ts}.db。"""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bdir = db_path.parent / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    dest = bdir / f"autohome-pre-weekly-{ts}.db"
    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    if not dest.is_file() or dest.stat().st_size == 0:
        raise RuntimeError(f"备份产物无效: {dest}")
    return dest


# ---------------- weekly_progress 滚动 ----------------

def roll_weekly_progress(db_path: Path, keep: int = KEEP_ROLLED) -> Path | None:
    """跑前若存在 weekly_progress.jsonl → 改名滚动；清理只留最近 keep 份。

    返回改名后的旧文件路径（无旧文件返回 None）。progress 与目标库同目录
    （增量 progress 由本入口显式传 --progress-file，不走 ROOT 缺省）。
    """
    cur = db_path.parent / "weekly_progress.jsonl"
    if not cur.is_file():
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    rolled = db_path.parent / f"weekly_progress_{ts}.jsonl"
    cur.rename(rolled)
    olds = sorted(db_path.parent.glob("weekly_progress_*.jsonl"))
    for stale in olds[:-keep] if len(olds) > keep else []:
        stale.unlink(missing_ok=True)
    return rolled


# ---------------- catchup 判定（纯函数 + IO 壳） ----------------

def should_catchup(now_local: datetime, last_success_finished_at_utc: datetime | None,
                   done_marker_exists: bool,
                   judge_after_hour: int = CATCHUP_JUDGE_AFTER_LOCAL,
                   stale_days: int = CATCHUP_STALE_DAYS) -> tuple[bool, str]:
    """补跑判定（纯函数，可测）。

    - 本地时刻 < judge_after_hour → 不判（给夜跑窗口留时间）
    - 日标记存在 → 跳过（幂等：登录任务每次登录都触发）
    - 无成功周更记录 → 补跑（从未跑过）
    - 最近成功 finished_at（UTC）距今 > stale_days 天 → 补跑
    返回 (是否补跑, 一句话理由)。now_local 必须带 TZ_CN 时区。
    """
    if now_local.tzinfo is None:
        now_local = now_local.replace(tzinfo=TZ_CN)
    if now_local.hour < judge_after_hour:
        return False, f"本地 {now_local.hour} 点（<{judge_after_hour} 点不判定，给夜跑窗留时间）"
    if done_marker_exists:
        return False, "今日日标记已存在（幂等跳过）"
    if last_success_finished_at_utc is None:
        return True, "无成功周更记录（从未跑过）→ 补跑"
    last_utc = last_success_finished_at_utc
    if last_utc.tzinfo is None:
        last_utc = last_utc.replace(tzinfo=timezone.utc)
    age = now_local.astimezone(timezone.utc) - last_utc
    if age > timedelta(days=stale_days):
        return True, (f"最近成功周更 {last_utc.astimezone(TZ_CN):%Y-%m-%d %H:%M} "
                      f"距今 {age.days} 天 > {stale_days} 天 → 补跑")
    return False, f"最近成功周更距今 {age.days} 天（≤{stale_days}，新鲜）"


def _last_weekly_success_utc(db_path: Path) -> datetime | None:
    """台账最近一次 mode=weekly 且 status=success 的 finished_at（naive UTC）。

    P2-4（Step8）：库无 collection_runs 表时返回 None（语义=从未跑过 → 判定需补跑
    → 主流程 init_db 建表，自愈闭环）——catchup 是 onlogon 无人值守路径，不许裸崩。
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        try:
            row = conn.execute(
                "SELECT finished_at FROM collection_runs "
                "WHERE mode='weekly' AND status='success' AND finished_at IS NOT NULL "
                "ORDER BY finished_at DESC LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            return None
    finally:
        conn.close()
    if not row or not row[0]:
        return None
    try:
        return datetime.fromisoformat(str(row[0]))
    except ValueError:
        return None


def _done_marker_path(now_local: datetime) -> Path:
    return LOGS_DIR / f"koubei_catchup_{now_local:%Y%m%d}.done"


# ---------------- 云端推送（方案 A：周更尾部直推，拍板 2026-11-01） ----------------

DEPLOY_DIR = PROJECT_ROOT / "deploy"
REMOTE_PY = DEPLOY_DIR / "remote.py"
SSHPASS_FILE = DEPLOY_DIR / ".sshpass"          # gitignored；缺文件=跳过推送不阻断采集
SNAPSHOT_FILE = DEPLOY_DIR / "push-autohome-snapshot.db"   # gitignored
CLOUD_DATA = os.environ.get("PRISM_CLOUD_DATA", "/root/prism/data/autohome.db")
CLOUD_DEPLOY = os.environ.get("PRISM_CLOUD_DEPLOY", "/root/prism/deploy")


def push_enabled() -> bool:
    """推送门：env PRISM_KOUBEI_PUSH=0 显式关；凭据文件在才推。"""
    if os.environ.get("PRISM_KOUBEI_PUSH", "1").strip() == "0":
        return False
    return SSHPASS_FILE.is_file()


def push_to_cloud(db_path: Path) -> tuple[bool, str]:
    """快照→推 ECS→停容器换库（清 -wal/-shm）→起→行数对账→清临时件。

    程序=2026-11-01 手动推送全流程实测通过后的原样封装（remote.py 为 SSH 单一
    事实源；subprocess 调用不经 Git Bash，无 MSYS 路径转换坑）。推送失败=传输层
    问题，采集结果不受影响；云端换库前自动备份可回滚。
    """
    t0 = datetime.now()
    src = sqlite3.connect(str(db_path), timeout=30)
    dst = sqlite3.connect(str(SNAPSHOT_FILE))
    src.backup(dst)
    dst.close()
    src.close()
    env = dict(os.environ, PRISM_SSH_PASS=SSHPASS_FILE.read_text(encoding="utf-8").strip())
    py = sys.executable

    r = subprocess.run([py, str(REMOTE_PY), "put", str(SNAPSHOT_FILE), "/tmp/autohome-new.db"],
                       capture_output=True, text=True, env=env, timeout=1800)
    if r.returncode != 0:
        return False, f"上传失败: {(r.stderr or r.stdout).strip()[:160]}"
    swap = (
        f"cp {CLOUD_DATA} /root/prism/backup/autohome-pre-push-$(date +%Y%m%d-%H%M).db && "
        f"cd {CLOUD_DEPLOY} && docker compose stop prism-dashboards prism-api && "
        f"cp /tmp/autohome-new.db {CLOUD_DATA} && "
        f"rm -f {CLOUD_DATA}-wal {CLOUD_DATA}-shm && "
        f"docker compose up -d prism-dashboards prism-api && sleep 8"
    )
    r = subprocess.run([py, str(REMOTE_PY), "exec", swap],
                       capture_output=True, text=True, env=env, timeout=600)
    if r.returncode != 0:
        return False, f"换库失败: {(r.stderr or r.stdout).strip()[:160]}"
    local_n = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True).execute(
        "SELECT COUNT(*) FROM owner_reviews").fetchone()[0]
    r = subprocess.run(
        [py, str(REMOTE_PY), "exec",
         "python3 -c \"import sqlite3;print(sqlite3.connect('%s')"
         ".execute('SELECT COUNT(*) FROM owner_reviews').fetchone()[0])\"" % CLOUD_DATA],
        capture_output=True, text=True, env=env, timeout=120)
    remote_n = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "?"
    if str(local_n) != remote_n:
        return False, f"对账不符 local={local_n} remote={remote_n}（云端 /root/prism/backup 有备份）"
    subprocess.run([py, str(REMOTE_PY), "exec", "rm -f /tmp/autohome-new.db"],
                   capture_output=True, text=True, env=env, timeout=60)
    elapsed = (datetime.now() - t0).total_seconds()
    return True, f"云端已对齐 {local_n} 条 · 耗时 {elapsed:.0f}s"


# ---------------- 锁 ----------------

def acquire_lock() -> bool:
    """already_running 互斥锁：写 pid；存在则探测进程是否仍活（死锁清理）。"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.is_file():
        try:
            old_pid = int(LOCK_PATH.read_text().strip())
            proc = subprocess.run(["powershell", "-NoProfile", "-Command",
                                   f"(Get-Process -Id {old_pid} -ErrorAction SilentlyContinue) -ne $null"],
                                  capture_output=True, text=True, timeout=15)
            if proc.returncode == 0 and proc.stdout.strip().lower() == "true":
                return False  # 仍在跑
        except Exception:
            pass
        # 死锁清理（进程不在/探测失败）：复盖
    LOCK_PATH.write_text(str(os.getpid()))
    return True


def release_lock():
    LOCK_PATH.unlink(missing_ok=True)


# ---------------- 日志 ----------------

def log_line(msg: str):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(TZ_CN).strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{ts} {msg}\n")


# ---------------- 主流程 ----------------

def run_weekly(live: bool, budget_reviews: int | None, db_cli: str | None) -> int:
    """主流程：锁 → 横幅 → dry-run 直通 / live 备份→增量跑→台账。返回退出码。"""
    if not acquire_lock():
        print("[koubei-weekly] 已有运行实例（锁存活），本次退出。", flush=True)
        return 0
    try:
        db_path = resolve_db_path(db_cli)
        _print_banner(db_path, live)
        # 目标库传给 recollect 层（其 init_db 读 DATABASE_URL）
        os.environ["DATABASE_URL"] = "sqlite:///" + str(db_path).replace("\\", "/")

        import recollect_koubei_with_full as rec
        from src.models.orm import CollectionRun
        from src.storage.db import init_db, session_scope

        progress_path = db_path.parent / "weekly_progress.jsonl"

        if not live:
            stats = asyncio.run(rec.recollect_all(
                mode="incremental", budget_reviews=budget_reviews, live=False,
                progress_path=str(progress_path)))
            print(f"[koubei-weekly|DRY-RUN] 名单 {len(stats['series_ids'])} 系，"
                  "dry-run 零写入零出网；真采加 --live", flush=True)
            log_line(f"DRY-RUN 名单={len(stats['series_ids'])} budget={budget_reviews} db={db_path}")
            return 0

        # ---- live ----
        rolled = roll_weekly_progress(db_path)
        if rolled:
            print(f"[koubei-weekly] progress 滚动: {rolled.name}", flush=True)
        backup = backup_db(db_path)
        print(f"[koubei-weekly] 备份完成: {backup.name}", flush=True)
        log_line(f"LIVE start db={db_path} backup={backup.name} budget={budget_reviews}")

        t0 = datetime.now(timezone.utc)
        try:
            stats = asyncio.run(rec.recollect_all(
                mode="incremental", budget_reviews=budget_reviews, live=True,
                progress_path=str(progress_path)))
        except SystemExit as e:
            # recollect 层守卫拦截（exit 2）/其他：记台账 error 后透传
            init_db()
            with session_scope() as s:
                s.add(CollectionRun(mode="weekly", started_at=t0,
                                    finished_at=datetime.now(timezone.utc),
                                    status="error", error=f"recollect SystemExit {e.code}"))
            log_line(f"LIVE error SystemExit={e.code}")
            return 2

        failures = stats.get("failures") or []
        capped = stats.get("budget_capped_series") or []
        new_total = int(stats.get("new_reviews_total") or 0)
        status = "success" if not failures else "partial"
        series_done = len(stats.get("pending") or []) - len(failures) - len(capped)

        init_db()
        with session_scope() as s:
            s.add(CollectionRun(
                mode="weekly", started_at=t0, finished_at=datetime.now(timezone.utc),
                series_total=len(stats.get("series_ids") or []),
                series_done=max(series_done, 0),
                series_budget_capped=len(capped),
                new_reviews=new_total,
                tagged=0,  # 逐系 tagged 在 progress jsonl（全系 distinct 口径不可跨系加总）
                status=status,
                error=("; ".join(f"{sid}:{err[:80]}" for sid, err in failures[:5]) or None)))
        log_line(f"LIVE done status={status} new={new_total} capped={len(capped)} "
                 f"failures={len(failures)} elapsed={stats.get('elapsed_s')}s")
        print(f"[koubei-weekly] 完成: status={status} 新增 {new_total} 条 · "
              f"budget_capped {len(capped)} 系 · 失败 {len(failures)} 系", flush=True)
        if push_enabled():
            print("[koubei-push] 周更尾部推送云端（方案 A）…", flush=True)
            ok, msg = push_to_cloud(db_path)
            log_line(f"PUSH {'OK' if ok else 'FAIL'} {msg}")
            print(f"[koubei-push] {'✅' if ok else '✋'} {msg}", flush=True)
            if not ok:
                return 2   # 采集已成功但桥断——exit 2 让计划任务侧可见
        return 1 if failures else 0
    except FileNotFoundError as e:
        print(f"[koubei-weekly] ✋ 环境拦截: {e}", flush=True)
        log_line(f"BLOCKED {e}")
        return 2
    except Exception as e:
        print(f"[koubei-weekly] ✋ 异常: {e}", flush=True)
        log_line(f"ERROR {type(e).__name__}: {e}")
        return 2
    finally:
        release_lock()


def run_catchup(check_only: bool, db_cli: str | None, budget_reviews: int | None) -> int:
    """onlogon 补跑：新鲜度自检 → 必要时阻塞跑主流程（--live，带同一预算帽）。"""
    now_local = datetime.now(TZ_CN)
    db_path = resolve_db_path(db_cli)
    marker = _done_marker_path(now_local)
    last = _last_weekly_success_utc(db_path)
    do_run, reason = should_catchup(now_local, last, marker.is_file())
    print(f"[koubei-catchup] 判定: {'需补跑' if do_run else '不补跑'} · {reason}", flush=True)
    if check_only:
        return 0
    if not do_run:
        return 3   # P2-2（Step8）：3=无事可做（数据新鲜，无需补跑）
    code = run_weekly(live=True, budget_reviews=budget_reviews, db_cli=db_cli)
    marker.write_text(f"{now_local:%Y-%m-%d %H:%M:%S} exit={code}\n")
    return code


def _parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="口碑周更入口（全池周更，2026-11-01 拍板）")
    ap.add_argument("--live", action="store_true", help="真采（缺省 dry-run 零写入零出网）")
    ap.add_argument("--budget-reviews", type=int, default=None,
                    help="全池新入库条数总帽（缺省 None=不限制；给数字则触顶 budget_capped 早退）")
    ap.add_argument("--catchup", action="store_true", help="登录补跑判定（+必要时跑）")
    ap.add_argument("--check", action="store_true", help="仅 catchup 判定不跑")
    ap.add_argument("--db", default=None, help="目标库路径（缺省按 PRISM_KOUBEI_DB/deploy/开发库序解析）")
    ap.add_argument("--push-only", action="store_true",
                    help="只推云端不采集（CAM 导入后手动触发同款）")
    return ap.parse_args(argv)


def main() -> int:
    args = _parse_args(sys.argv[1:])
    if args.push_only:
        if not acquire_lock():
            print("[koubei-weekly] 已有运行实例，退出", flush=True)
            return 0
        try:
            ok, msg = push_to_cloud(resolve_db_path(args.db))
            log_line(f"PUSH {'OK' if ok else 'FAIL'} (push-only) {msg}")
            print(f"[koubei-push] {'✅' if ok else '✋'} {msg}", flush=True)
            return 0 if ok else 2
        finally:
            release_lock()
    if args.catchup:
        return run_catchup(check_only=args.check, db_cli=args.db,
                           budget_reviews=args.budget_reviews)
    return run_weekly(live=args.live, budget_reviews=args.budget_reviews, db_cli=args.db)


if __name__ == "__main__":
    sys.exit(main())
