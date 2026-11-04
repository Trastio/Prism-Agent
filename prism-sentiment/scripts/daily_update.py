"""每日更新入口 —— 供 prime-agent 层的统一调度调用（2026-09-12）。

用法（单命令，同步阻塞，退出码明确）：
    python scripts/daily_update.py                 # 所有 active 车辆
    python scripts/daily_update.py --all           # 同上（计划任务用显式旗标）
    python scripts/daily_update.py --vehicle M03   # 按名称过滤（子串匹配）
    python scripts/daily_update.py --base http://127.0.0.1:8000

行为：
1. 服务健康检查（GET /api/vehicles）
2. 逐车串行：POST /collect → 轮询 /pipeline-status 到终态（completed/error）
3. 汇总打印：每车帖数/分析数/错误 + 总耗时
4. 收尾：互动刷新 → 30 天清理（默认 dry-run）→ SQLite 在线备份

R22（2026-10-16 舆情降本）：全 active 车**每日直通**，频率分层不再决定
"谁今天跑"（hot/mid/cold 降级为展示排序，pipeline/frequency.py 模块保留
供看板消费）。原 --all 的分层跳过逻辑删除；--all 与缺省语义一致，留作
计划任务（PrismSentimentDaily，每日 03:00）的显式旗标。

退出码：0=全部成功；1=部分车失败或备份失败；2=服务不可达；3=无待更新车辆。
注意：服务须在运行（start.py supervisor 常驻）；超时默认 30 分钟/车。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

from dotenv import load_dotenv
from pathlib import Path

try:  # Windows GBK 控制台兜底
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 项目根（utils.backup）

# P2-4：refreshing 也在活跃集——原轮询把它当终态，撞上互动刷新时假完成跳车，
# 该车当日增量实际没跑
ACTIVE_PHASES = {"collecting", "analyzing", "calculating", "refreshing"}


def _get(base: str, path: str, timeout: int = 30) -> dict:
    with urllib.request.urlopen(f"{base}{path}", timeout=timeout) as r:
        return json.loads(r.read())


def _post(base: str, path: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(f"{base}{path}", method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# refresh 管线的两个相位（refreshing → calculating → completed）
_REFRESH_PHASES = {"refreshing", "calculating"}


def _wait_refresh_done(base: str, vid: str, timeout_min: int = 10) -> None:
    """等待在跑的互动刷新结束（P2-4）。

    refresh 不抓新帖：撞上 refreshing 时不能把当日增量记完成——等它结束，
    由调用方重发 /collect。超时放弃（调用方重发时后端互斥会再拦）。
    """
    deadline = time.time() + timeout_min * 60
    while time.time() < deadline:
        time.sleep(10)
        try:
            st = _get(base, f"/api/vehicles/{vid}/pipeline-status")
        except Exception:
            continue
        if st.get("phase") not in _REFRESH_PHASES:
            return


def main() -> int:
    # 2026-10-21 env 疣修复（R40 夜跑 dry-run 根因）：本脚本是 HTTP 编排器，
    # 采集/TikHub 调用都在常驻服务进程里（那边自有 load_dotenv），但收尾的
    # 30 天清理（_run_post_cleanup 读 PRISM_CLEANUP_LIVE）跑在本进程——
    # 此前本进程从未加载 .env，真删门恒 False → 夜跑清理一直 dry-run。
    # 入口统一加载（override=False 不覆盖已有 env，monkeypatch 的测试值安全）。
    load_dotenv()
    ap = argparse.ArgumentParser(description="舆情看板每日更新（prime-agent 入口）")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--vehicle", default="", help="按名称子串过滤（空=全部 active）")
    ap.add_argument("--all", action="store_true",
                    help="遍历全部 active 车（R22：无频率分层跳过；计划任务用旗标）")
    ap.add_argument("--timeout-min", type=int, default=30, help="单车超时分钟")
    args = ap.parse_args()

    t0 = time.time()
    try:
        vehicles = _get(args.base, "/api/vehicles")
    except Exception as e:
        print(f"[FAIL] 服务不可达 {args.base}: {e}")
        return 2

    # R22（2026-10-16）：全 active 每日直通——频率分层不再决定谁跑（原
    # --all 分支删除）。--all 保留为计划任务旗标，与缺省同义；--vehicle
    # 子串过滤两态通用（空串=全部 active）。
    targets = [v for v in vehicles
               if v.get("status") == "active"
               and args.vehicle in v.get("name", "")]
    if not targets:
        print(f"[WARN] 无匹配的 active 车辆（filter={args.vehicle!r}, all={args.all}）")
        return 3

    print(f"[{datetime.now():%H:%M:%S}] 待更新 {len(targets)} 车: "
          + ", ".join(v["name"] for v in targets))
    failed = []
    capped = []  # P1-1：预算触顶车单列（≠失败，次日自愈）
    for v in targets:
        name, vid = v["name"], v["id"]
        try:
            started = _post(args.base, f"/api/vehicles/{vid}/collect")
        except Exception as e:
            print(f"  [{name}] 触发失败: {e}")
            failed.append(name)
            continue
        if started.get("status") == "already_running":
            if started.get("phase") == "refreshing":
                # P2-4：撞上互动刷新——refresh 不抓新帖，等它结束后重发采集，
                # 否则当日增量被跳过（原轮询把 refreshing 当终态假完成）
                print(f"  [{name}] 互动刷新进行中，等待其完成后重发采集")
                _wait_refresh_done(args.base, vid)
                try:
                    started = _post(args.base, f"/api/vehicles/{vid}/collect")
                except Exception as e:
                    print(f"  [{name}] 重发采集失败: {e}")
                    failed.append(name)
                    continue
            if started.get("status") == "already_running":
                print(f"  [{name}] 已在运行，等待其完成")
            elif started.get("status") != "started":
                print(f"  [{name}] 触发异常响应: {started}")
                failed.append(name)
                continue
        elif started.get("status") != "started":
            print(f"  [{name}] 触发异常响应: {started}")
            failed.append(name)
            continue
        # 轮询到终态
        deadline = time.time() + args.timeout_min * 60
        final = None
        while time.time() < deadline:
            time.sleep(15)
            try:
                st = _get(args.base, f"/api/vehicles/{vid}/pipeline-status")
            except Exception as e:
                print(f"  [{name}] 状态查询失败: {e}")
                time.sleep(10)
                continue
            phase = st.get("phase")
            if phase not in ACTIVE_PHASES:
                final = st
                break
        if final is None:
            print(f"  [{name}] 超时（>{args.timeout_min}min），跳到下一车")
            failed.append(name)
            continue
        if final.get("phase") == "error":
            print(f"  [{name}] 失败: {final.get('error')}")
            failed.append(name)
        elif final.get("phase") == "budget_capped":
            # P1-1（Step7 审查）：护栏触顶≠失败——数据不丢，次日增量窗自动补；
            # 单列统计防"假完成"（skipped_vehicles 里有登记，as_of 不掩盖）。
            print(f"  [{name}] 预算触顶: {final.get('error')}（明日增量窗自动补）")
            capped.append(name)
        else:
            print(f"  [{name}] 完成: 新帖 {final.get('posts_collected', 0)}, "
                  f"分析 {final.get('analyzed', 0)}")

    mins = (time.time() - t0) / 60
    print(f"[{datetime.now():%H:%M:%S}] 结束: {len(targets) - len(failed) - len(capped)}/{len(targets)}"
          f" 成功, 耗时 {mins:.1f} 分钟")
    if capped:
        print(f"  ⚠ 预算触顶 {len(capped)} 车: {', '.join(capped)}"
              f"（TIKHUB_DAILY_BUDGET={os.environ.get('TIKHUB_DAILY_BUDGET', '2200')}，次日自动补采）")

    # 收尾：互动刷新已由服务端 Phase 9 逐车内嵌完成（collection.py 采集管线
    # refreshing 阶段）——2026-10-16 T7 实测发现原尾部 run_all 是第二遍全量
    # 刷新（≈300 次/天纯冗余，P2③·Step7），删除；手动全量刷新仍可直调
    # scripts/refresh_engagement.py 的 run_all。

    # 收尾：30 天保留线老帖物理清理（T3/R40+R42，paused 豁免）——
    # 排在备份之前，让备份落在清理后的库上
    _run_post_cleanup()

    # 收尾：数据库在线备份（失败只把 0 降为 1，不改写 2/3 的语义）
    backup_ok = _run_backup()

    if failed:
        print(f"[FAIL] 失败车辆: {', '.join(failed)}")
        return 1
    if not backup_ok:
        return 1
    return 0



def _run_post_cleanup() -> None:
    """收尾跑 30 天保留线清理（T3，R40/R42）。失败只打 WARN 不阻断主流程。

    **默认 dry-run**：真删须 env PRISM_CLEANUP_LIVE=1（T6 验收人工过目
    dry-run 清单后开启）——2026-10-16 事故教训：测试若漏补丁此钩子，
    默认真删会打到生产库。
    直调 run_cleanup（不走 main——后者解析 sys.argv，会撞 daily_update 的 --all）。
    """
    try:
        from scripts.cleanup_posts import run_cleanup, _print_report
        live = os.getenv("PRISM_CLEANUP_LIVE", "").strip() == "1"
        r = run_cleanup(dry_run=not live)
        _print_report(r)
        if not live and r["posts"]:
            print("[CLEANUP] dry-run 模式（PRISM_CLEANUP_LIVE=1 开启真删）")
    except Exception as e:
        print(f"[WARN] 老帖清理异常: {e}")


def _run_backup() -> bool:
    """daily_update 收尾备份：成功打一行摘要，失败打 WARN。返回是否成功。"""
    try:
        from utils.backup import backup_database
        res = backup_database()
    except Exception as e:
        print(f"[WARN] 备份异常: {e}")
        return False
    if not res.get("ok"):
        print(f"[WARN] 备份失败: {res.get('error')}")
        return False
    offsite = res.get("offsite")
    note = {
        "copied": "",
        "not_configured": "（提示: .env 配 BACKUP_OFFSITE_DIR=<网盘同步目录/外接盘> 可异地容灾）",
    }.get(offsite, f"（[WARN] 异地拷贝异常: {offsite}）")
    name = Path(res["file"]).name
    print(f"[BACKUP] {name} ({res['size_bytes'] / 1e6:.2f} MB), "
          f"滚动保留 {res['kept']} 份, 本次清理 {len(res['deleted'])} 份 {note}".rstrip())
    return True


if __name__ == "__main__":
    sys.exit(main())
