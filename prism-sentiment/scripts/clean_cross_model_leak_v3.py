# -*- coding: utf-8 -*-
"""存量清理 v3：跨车型混入帖 → irrelevant（备份先行，dry-run 默认）。

口径（与审计 v3c 一致）：
  analysis_status != 'irrelevant'（RELEVANT_ONLY 通过）
  AND COALESCE(subject,'self') = 'self'（SELF_ONLY 通过）
  AND 帖文含外部车型名（其他在库车名/去品牌短名，含后缀边界）
  AND 帖文不含本车名/短名（排除对比帖——对比帖按设计相关）

外部车型模式自动生成（从 vehicles 表），非硬编码——新车自动纳入。

用法：
  python scripts/clean_cross_model_leak_v3.py --dry-run   # 报数+样本（默认）
  python scripts/clean_cross_model_leak_v3.py --apply     # 备份 + 清理 + 重算
"""
import argparse
import asyncio
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / "data" / "vehicle_sentiment.db"

BRAND_TOKEN_RE = re.compile(r'[一-鿿]+|[A-Za-z0-9]+')

# 库外常混车名词典（2026-10-08 复扫实证：在库车 foreign 判别不覆盖这些——
# 星舰7/C10/D99 等不在 vehicles 表但实测大量出现在兄弟车下）。跨品牌撞名
# （奥迪A7L/索尼A7）同列。后续新车上市在此追加（或入 vehicles 表自动纳入）。
_KNOWN_FOREIGN_NAMES = [
    # 吉利银河系（非在库）
    "星舰7", "星舰6", "星耀6", "银河L6", "银河L7", "星愿",
    # 奇瑞风云系库外变体
    "风云T6", "风云A8",
    # 零跑系（非在库）
    "C10", "C11", "C01", "A10", "A12", "T03", "D99", "B05",
    # 比亚迪海狮系库外变体
    "海狮05", "海狮07", "海狮07EV",
    # 跨品牌撞名（A7 的同名异车）
    "奥迪A7L", "奥迪A7", "索尼A7V", "索尼A7R", "索尼A7",
    # 特斯拉互串
    "Model S", "Model X",
    # 小鹏 MONA 系库外
    "M05", "MONA M05",
]


def name_variants(name: str, brand: str) -> list[str]:
    """车名 + 去品牌短名（比亚迪海豚→海豚）+ 已知车别名（C-1 共享表）。"""
    out = [name]
    if brand and name.startswith(brand):
        short = name[len(brand):].strip()
        if short:
            out.append(short)
    # v3 C-1/I-1：别名也是"本车变体"（own 守卫保护 + foreign 判别都要带上）
    try:
        from pipeline.analysis.relevance_filter import get_vehicle_aliases
        out += [a for a in get_vehicle_aliases(name) if a]
    except ImportError:
        pass
    return out


def alnum_token_pattern(variant: str):
    """Deprecated（review M-4 死代码）：保留空实现防外部引用。"""
    return None


def token_bounded(variant: str, text_lower: str) -> bool:
    if any(c.isascii() and c.isalnum() for c in variant):
        return bool(re.search(rf'(?<![a-z0-9]){re.escape(variant.lower())}(?![a-z0-9])', text_lower))
    return variant in text_lower


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际执行（默认 dry-run）")
    ap.add_argument("--dry-run", action="store_true", help="报数+样本（默认行为，显式旗标）")
    args = ap.parse_args()

    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    vehicles = cur.execute(
        "SELECT id, name, brand FROM vehicles WHERE status='active' OR status IS NULL"
    ).fetchall()

    # 每车的判别材料：本车变体（排除对比帖）+ 外部变体（判混入）
    own_by_vid = {}
    foreign_by_vid = {}
    for vid, name, brand in vehicles:
        own_by_vid[vid] = [v.lower() for v in name_variants(name or "", brand or "")]
    for vid, name, brand in vehicles:
        foreign = []
        for vid2, name2, brand2 in vehicles:
            if vid2 == vid:
                continue
            foreign.extend(name_variants(name2 or "", brand2 or ""))
        # v3 复扫补丁：库外常混车名（星舰7/C10/D99/奥迪A7L…）不在 vehicles 表，
        # 在库 foreign 判别不覆盖——词典补齐（同带边界）
        foreign += _KNOWN_FOREIGN_NAMES
        # 本车名若与词典词同名/子串（如本车就叫星愿）则从词典里剔除自身
        own_lower = {v.lower() for v in name_variants(name or "", brand or "")}
        foreign = [f for f in foreign if f.lower() not in own_lower]
        foreign_by_vid[vid] = foreign

    total_hits = []
    print("=" * 72)
    print(f"{'车名':<14}{'混入帖':>6}  样本")
    for vid, name, brand in vehicles:
        # I-2 修复：三列独立 COALESCE（title NULL 不再把整串变 NULL），加 full_content
        rows = cur.execute("""
            SELECT r.id, r.title, lower(COALESCE(r.title,'') || ' ' || COALESCE(r.content,'')
                                       || ' ' || COALESCE(r.full_content,''))
            FROM raw_posts r LEFT JOIN analyzed_posts a ON a.post_id = r.id
            WHERE r.vehicle_id=? AND r.analysis_status != 'irrelevant'
              AND COALESCE(a.subject,'self') = 'self'
        """, (vid,)).fetchall()
        hits = []
        for pid, title, text in rows:
            if not text.strip():
                continue
            # I-1 修复：own 判定带边界（风云A9 车下"风云A9L..."帖不再因裸子串
            # "风云a9" 命中而被保护；对比帖里独立的"a9"仍命中、仍保护）
            if any(token_bounded(o, text) for o in own_by_vid[vid]):
                continue  # 含本车名 → 对比帖或本车帖
            if any(token_bounded(f, text) for f in foreign_by_vid[vid]):
                hits.append((pid, title))
        if hits:
            total_hits += [(vid, name, pid, title) for pid, title in hits]
            s = " | ".join((t or "")[:24] for _, t in hits[:3])
            print(f"{(name or ''):<14}{len(hits):>6}  {s}")
    print("=" * 72)
    print(f"合计：{len(total_hits)} 帖待清理（dry-run={'否' if args.apply else '是'}）")

    if not args.apply:
        print("dry-run 结束。确认无误后加 --apply 执行（会先自动备份）。")
        return 0

    # ── apply ──
    from utils.backup import backup_database
    res = backup_database()
    if not res.get("ok"):
        print(f"[FAIL] 备份失败，中止：{res.get('error')}")
        return 1
    print(f"[BACKUP] {res['file']}")

    affected = set()
    for vid, name, pid, title in total_hits:
        cur.execute("UPDATE raw_posts SET analysis_status='irrelevant' WHERE id=?", (pid,))
        cur.execute("DELETE FROM analyzed_posts WHERE post_id=?", (pid,))
        affected.add(vid)
    con.commit()
    print(f"已标记 {len(total_hits)} 帖 irrelevant + 删除对应 analyzed_posts 行；"
          f"受影响车 {len(affected)}")

    # 级联重算预计算表（fleet-rebalance 先例：只改 raw_posts 不级联 = v1/v2 盲区）
    async def recompute():
        from models.database import async_session, engine
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        try:
            async with async_session() as session:
                for vid in affected:
                    end = date.today()
                    try:
                        await HeatMetricCalculator(session).calculate_range(
                            vid, end - timedelta(days=90), end)
                        print(f"  heat 重算完成: {vid}")
                    except Exception as e:
                        print(f"  heat 重算失败 {vid}: {e}")
        finally:
            await engine.dispose()

    asyncio.run(recompute())
    print("清理完成。跑 scripts/audit_cross_model_leak_v3c.py 复扫应归零。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
