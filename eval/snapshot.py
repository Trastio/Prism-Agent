#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prism-Agent · 评估环境快照工具（P0-#28，方案 v3.4.3 §4.1.1）。

把三件真值源导出成带时间戳的一致性副本 + manifest：
  autohome.db           <- VACUUM INTO 自 prism-dashboards/data/autohome.db
  vehicle_sentiment.db  <- VACUUM INTO 自 prism-sentiment/data/vehicle_sentiment.db
  market_source.json    <- 直接复制（CAM SOP 口径台账）
  manifest.json         <- as_of（记数据口径日，非快照创建日）/ sha256 / agent_version

用法：
  python eval/snapshot.py create [--name snap-YYYYMMDD-HHMM]
  python eval/snapshot.py list

纪律：
- VACUUM INTO 官方语义保证一致性快照（源库并发写入不破坏导出，仅可能拉长耗时）
- 被 EVAL_STATUS 批跑记录引用过的快照永不删；保留最近 3 份（约 320MB/份）
- 月更/CAM 导入后重算 eval/truth-expectations.json（生成工具 P2，当前手填）
- db 哈希口径 = 创建时指纹：eval 实例挂载可能使 db WAL 化（文件头漂移，数据不损），
  manifest.first_mounted_at 由 prism.py eval start 首挂时留痕；market_source.json 哈希长期有效
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAP_ROOT = Path(__file__).resolve().parent / "snapshots"

SOURCES = {
    "autohome.db": PROJECT_ROOT / "prism-dashboards" / "data" / "autohome.db",
    "vehicle_sentiment.db": PROJECT_ROOT / "prism-sentiment" / "data" / "vehicle_sentiment.db",
    "market_source.json": PROJECT_ROOT / "prism-dashboards" / "data" / "market_source.json",
}

# 舆情库日期列探测（best-effort；全失败记 unknown 不阻塞）
SENTIMENT_DATE_PROBES = [
    "SELECT MAX(published_at) FROM raw_posts",
    "SELECT MAX(published_at) FROM analyzed_posts",
    "SELECT MAX(created_at) FROM raw_posts",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:%s" % h.hexdigest()


def vacuum_into(src: Path, dst: Path) -> None:
    if dst.exists():
        dst.unlink()
    conn = sqlite3.connect(str(src))
    try:
        # 字面量形式（非参数绑定）：部分 sqlite3 版本对 VACUUM INTO 的表达式参数支持不一
        conn.execute("VACUUM INTO '%s'" % str(dst).replace("'", "''"))
    finally:
        conn.close()


def as_of_sales() -> dict:
    ms = SOURCES["market_source.json"]
    if not ms.exists():
        return {"source": "market_source.json 缺失", "value": "unknown"}
    try:
        data = json.loads(ms.read_text(encoding="utf-8"))
        months = data.get("months")
        # months 可能是字符串（"2025年1月末→2026年9月末"）或列表——列表才 join，
        # 字符串直接用（Step9 实证：str 被逐字符 join 成 "2+0+2+5+年+…"）
        value = months if isinstance(months, str) else "+".join(months or [])
        return {
            "value": value or "unknown",
            "imported_at": data.get("imported_at"),
            "note": "销量口径=月末批（当前真值见 market_source.json）",
        }
    except Exception as e:
        return {"source": "market_source.json 解析失败", "value": "unknown", "error": str(e)}


def as_of_koubei(snap_dir: Path) -> dict:
    try:
        conn = sqlite3.connect(str(snap_dir / "autohome.db"))
        try:
            row = conn.execute("SELECT MAX(post_date) FROM owner_reviews").fetchone()
        finally:
            conn.close()
        return {"value": row[0] or "unknown", "note": "口碑=owner_reviews MAX(post_date)"}
    except Exception as e:
        return {"value": "unknown", "error": str(e)}


def as_of_sentiment(snap_dir: Path) -> dict:
    try:
        conn = sqlite3.connect(str(snap_dir / "vehicle_sentiment.db"))
        try:
            for sql in SENTIMENT_DATE_PROBES:
                try:
                    row = conn.execute(sql).fetchone()
                    if row and row[0]:
                        return {"value": str(row[0]), "note": sql.split()[-1]}
                except sqlite3.Error:
                    continue
        finally:
            conn.close()
    except Exception:
        pass
    return {"value": "unknown", "note": "舆情库日期表探测未命中（不阻塞，P2 校准表名）"}


def agent_version() -> str:
    try:
        pkg = json.loads((PROJECT_ROOT / "package.json").read_text(encoding="utf-8"))
        return pkg.get("version", "unknown")
    except Exception:
        return "unknown"


def cmd_create(name: str) -> int:
    snap_id = name or ("snap-%s" % datetime.now().strftime("%Y%m%d-%H%M"))
    snap_dir = SNAP_ROOT / snap_id
    if snap_dir.exists():
        print("已存在同名快照：%s（不覆盖，如需重打换 --name）" % snap_dir)
        return 1
    missing = [str(p) for p in SOURCES.values() if not p.exists()]
    if missing:
        print("真值源缺失，终止：\n  " + "\n  ".join(missing))
        return 1
    snap_dir.mkdir(parents=True)
    t0 = time.time()
    try:
        import shutil
        for fname, src in SOURCES.items():
            dst = snap_dir / fname
            if fname.endswith(".db"):
                print("VACUUM INTO %s ..." % fname, flush=True)
                vacuum_into(src, dst)
            else:
                shutil.copy2(src, dst)
    except Exception:
        # 中途失败清理半成品，否则重跑被同名检查挡住（审查 P2#6）
        import shutil
        shutil.rmtree(snap_dir, ignore_errors=True)
        raise
    manifest = {
        "snapshot_id": snap_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_sec": round(time.time() - t0, 1),
        "as_of": {
            "sales": as_of_sales(),
            "koubei": as_of_koubei(snap_dir),
            "sentiment": as_of_sentiment(snap_dir),
            "note": "as_of 记数据口径日（非快照创建日）——方案 §4.1.1",
        },
        "files": {},
        "agent_version": agent_version(),
        "source_dbs": {k: str(v) for k, v in SOURCES.items()},
    }
    for fname in SOURCES:
        p = snap_dir / fname
        manifest["files"][fname] = {"sha256": sha256_file(p), "bytes": p.stat().st_size}
    (snap_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    total_mb = sum(f["bytes"] for f in manifest["files"].values()) / (1 << 20)
    print("\n快照完成: %s（%.0f MB / %.1fs）" % (snap_dir, total_mb, manifest["elapsed_sec"]))
    for fname, f in manifest["files"].items():  # 审查 P2#8：哈希打印供复验
        print("  %-22s %s (%.0f MB)" % (fname, f["sha256"][:23], f["bytes"] / (1 << 20)))
    print("as_of: sales=%s koubei=%s sentiment=%s" % (
        manifest["as_of"]["sales"]["value"],
        manifest["as_of"]["koubei"]["value"],
        manifest["as_of"]["sentiment"]["value"]))
    n = len(list(SNAP_ROOT.glob("snap-*")))
    print("\n当前快照数: %d（保留最近 3 份；被 EVAL_STATUS 批跑引用过的永不删）" % n)
    print("启用: python prism.py eval start %s" % snap_id)
    return 0


def cmd_list() -> int:
    snaps = sorted(SNAP_ROOT.glob("snap-*"))
    if not snaps:
        print("尚无快照。先 python eval/snapshot.py create")
        return 0
    print("%-24s %-19s %-10s %-10s %-10s" % ("snapshot_id", "created_at", "sales", "koubei", "sentiment"))
    for d in snaps:
        mf = d / "manifest.json"
        if not mf.exists():
            print("%-24s (manifest 缺失)" % d.name)
            continue
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:  # 审查 P2#7：损坏 manifest 不致崩
            print("%-24s (manifest 损坏)" % d.name)
            continue
        a = m.get("as_of", {})
        def _v(k):
            v = a.get(k, {}).get("value", "unknown")
            return str(v)[:10]
        print("%-24s %-19s %-10s %-10s %-10s %s" % (
            m.get("snapshot_id", d.name), m.get("created_at", "")[:19],
            _v("sales"), _v("koubei"), _v("sentiment"),
            ("挂载于 " + m["first_mounted_at"][:16]) if m.get("first_mounted_at") else ""))
    return 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Prism 评估快照工具")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--name", default=None, help="快照 id（缺省 snap-YYYYMMDD-HHMM）")
    sub.add_parser("list")
    args = ap.parse_args()
    if args.cmd == "create":
        return cmd_create(args.name)
    return cmd_list()


if __name__ == "__main__":
    sys.exit(main())
