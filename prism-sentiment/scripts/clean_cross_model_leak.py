"""清理同品牌不同车型混入帖子（存量软删除）。

扫描全库，将"不含本车名 + 含其他车名"的帖子 analysis_status 改为 "irrelevant"。
看板查询已带 RELEVANT_ONLY 过滤会自动排除。备份后执行。

用法：
    python scripts/clean_cross_model_leak.py [--dry-run] [--db PATH]
"""
import argparse
import re
import shutil
import sqlite3
from datetime import datetime

# 复用 Rule 4 的别名感知校验，保证脚本与过滤口径一致
from pipeline.analysis.relevance_filter import VehicleProfile, _has_self_name
from models.schemas import Vehicle

# 7 主流品牌车名模式（库外车名识别，不限于 vehicles 表）
# 注意：单字车名（汉/唐）要求带数字，避免"汉朝/唐朝"误匹配
_CAR_NAME_PATTERNS = [
    # 比亚迪
    r"海狮0\d+", r"海豚\d*", r"元PLUS", r"元UP", r"宋PLUS", r"秦PLUS",
    r"汉\d+", r"唐\d+", r"方程豹\d+", r"豹\d+", r"海豹0\d+",
    # 特斯拉
    r"Model\s*[Y3SXC]",
    # 吉利银河
    r"银河[A-Z]\d+", r"银河L\d+", r"银河M\d+", r"星愿",
    # 奇瑞风云
    r"风云[AT]\d+L?",
    # 零跑
    r"零跑[A-ZT]\d+",
    # 小鹏
    r"MONA\s*M\d+", r"小鹏[GP]\d+",
    # 小米
    r"小米SU\d+",
]
_CAR_NAME_RE = re.compile("|".join(_CAR_NAME_PATTERNS))


def _normalize_car_name(raw: str) -> str:
    """归一车名：去空格、统一小写。Model3→model3, model 3→model3, ModelY→modely"""
    return re.sub(r"\s+", "", raw).lower()


def _extract_other_car_names(text: str, profile) -> list:
    """提取帖子里出现的其他车名（库内+库外），归一后排除本车（含别名/短名）。

    profile: VehicleProfile（与 _has_self_name 同口径）
    返回归一化后的其他车名列表（去重）。空列表=无其他车名。

    注：同车版本（海狮06EV/DMI、Model YL）保留靠 _has_self_name 的 substring
    匹配（"海狮06" 是 "海狮06EV" 的 substring），不在此函数处理。此函数只
    判断"是否含其他车名"。regex 只提取基础车名（数字/字母代号部分），
    "海狮06EV" 提取出 "海狮06" → 是本车 → 排除。
    """
    self_norm = {_normalize_car_name(profile.name)}
    self_norm.update(_normalize_car_name(a) for a in profile.aliases if a)
    # 短名（品牌前缀剥离，与 _has_self_name 同逻辑）
    if profile.brand and profile.name.startswith(profile.brand):
        short = profile.name[len(profile.brand):].strip()
        if short:
            self_norm.add(_normalize_car_name(short))

    others = set()
    for raw in _CAR_NAME_RE.findall(text):
        norm = _normalize_car_name(raw)
        if norm not in self_norm:
            others.add(norm)
    return list(others)


def clean_leaks(db_path: str = "data/vehicle_sentiment.db", dry_run: bool = False) -> int:
    """清理混入帖子，返回清理条数。

    v2: 库外车名识别（regex 7 品牌 + normalize + 同车版本靠 substring）。
    判定口径与 Rule 4 一致：含本车名/别名/品牌前缀剥离 → 保留（_has_self_name）；
    不含本车名 + 含其他车名（库内+库外）→ 标记 irrelevant。
    只扫 analysis_status='analyzed'（避免重复扫已 irrelevant 的）。
    """
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    vehicles = cur.execute("SELECT id, name, brand FROM vehicles").fetchall()
    profiles = {}
    for vid, name, brand in vehicles:
        v = Vehicle(id=vid, name=name, brand=brand)
        profiles[vid] = VehicleProfile.from_vehicle(v)

    cleaned = 0
    for vid, name, _ in vehicles:
        profile = profiles[vid]
        posts = cur.execute(
            "SELECT id, title, content FROM raw_posts WHERE vehicle_id=? AND analysis_status='analyzed'",
            (vid,)
        ).fetchall()
        for pid, title, content in posts:
            text = (title or "") + " " + (content or "")
            # 含本车名/别名 → 保留（含对比帖）
            if _has_self_name(text, profile):
                continue
            # 不含本车名 + 含其他车名（库内+库外）→ 标记 irrelevant
            others = _extract_other_car_names(text, profile)
            if others:
                if not dry_run:
                    cur.execute(
                        "UPDATE raw_posts SET analysis_status='irrelevant' WHERE id=?", (pid,)
                    )
                cleaned += 1
    if not dry_run:
        con.commit()
    con.close()
    return cleaned


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计不执行")
    parser.add_argument("--db", default="data/vehicle_sentiment.db")
    args = parser.parse_args()

    if not args.dry_run:
        bak = f"{args.db}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        shutil.copy(args.db, bak)
        print(f"备份: {bak}")

    cleaned = clean_leaks(args.db, args.dry_run)
    print(f"{'[DRY-RUN] ' if args.dry_run else ''}清理混入帖子: {cleaned} 条")


if __name__ == "__main__":
    main()
