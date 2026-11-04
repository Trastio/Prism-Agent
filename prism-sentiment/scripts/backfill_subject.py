"""规则回填 analyzed_posts.subject（不调 LLM，免费快速）。

判定：统计 title+content 里主车型名/品牌 vs 其他汽车品牌的提及次数，
提及次数最多的类别决定 subject。
- 主车型提及 >=1 且 >= 竞品提及 → self
- 竞品提及 > 主车型提及 → competitor（subject_name=竞品名）
- 都无 → other

新帖走 analyzer 的 LLM 判定（更准）；此脚本只回填已分析的老数据。

用法：python scripts/backfill_subject.py [--vehicle-id VID] [--dry-run]
"""
import argparse
import re
import sqlite3
from collections import Counter

# 主车型从 Vehicle 表读；竞品品牌词硬编码（常见电车竞品）
COMPETITOR_BRANDS = {
    "比亚迪海豚": ["比亚迪海豚", "BYD海豚", "海豚荣耀"],
    "比亚迪海豹": ["比亚迪海豹", "BYD海豹", "海豹"],
    "比亚迪元": ["元PLUS", "元plus", "元 plus", "比亚迪元"],
    "比亚迪秦": ["秦PLUS", "秦plus", "比亚迪秦"],
    "比亚迪宋": ["宋PLUS", "宋plus", "比亚迪宋"],
    "特斯拉": ["特斯拉", "Tesla", "TESLA", "Model 3", "Model Y", "model3", "modely"],
    "小鹏": ["小鹏", "MONA"],
    "蔚来": ["蔚来", "NIO"],
    "理想": ["理想汽车", "理想L"],
    "埃安": ["埃安", "AION", "Aion"],
    "吉利银河": ["吉利银河", "银河E5", "银河L"],
    "零跑": ["零跑", "C10", "C11", "C16", "C01"],
    "五菱": ["五菱", "缤果", "星光"],
}


def count_mentions(text: str, words: list[str]) -> int:
    return sum(len(re.findall(re.escape(w), text)) for w in words)


def build_self_words(name: str, brand: str) -> list[str]:
    """从车型名/品牌派生 self 匹配词（含简称）。

    启源Q05 → ["启源Q05", "启源", "Q05"]；品牌过宽（长安有众多车型）默认不用，
    除非品牌名本身较独特。去重去空。
    """
    words = []
    if name:
        words.append(name)
        # 拆出中文段和字母数字段作为简称
        cn = re.findall(r"[一-龥]+", name)
        alnum = re.findall(r"[A-Za-z0-9]+", name)
        words += cn + alnum
    # brand 默认不加（"长安"过宽）；若品牌独特（如"蔚来"）可考虑，这里保守不加
    seen, out = set(), []
    for w in words:
        if w and w not in seen and len(w) >= 2:
            seen.add(w)
            out.append(w)
    return out


def classify(text: str, self_words: list[str]) -> tuple[str, str]:
    """返回 (subject, subject_name)。

    提及主车型（任一 self_word）即为 self——含对比帖（主车型视角对比竞品）。
    不提主车型但提竞品 → competitor。都不提 → other。
    """
    self_n = count_mentions(text, self_words)
    if self_n > 0:
        return ("self", "")
    comp_counts = {name: count_mentions(text, words) for name, words in COMPETITOR_BRANDS.items()}
    comp_best_name, comp_best_n = max(comp_counts.items(), key=lambda x: x[1])
    if comp_best_n > 0:
        return ("competitor", comp_best_name)
    return ("other", "")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vehicle-id", help="只回填指定车型（默认全部）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = ap.parse_args()

    con = sqlite3.connect("data/vehicle_sentiment.db")
    where = "WHERE a.subject_name IS NULL OR a.subject_name = ''"
    if args.vehicle_id:
        where += f" AND a.vehicle_id = '{args.vehicle_id}'"

    rows = con.execute(
        "SELECT a.id, COALESCE(r.title,'') || ' ' || COALESCE(r.content,''), "
        "v.name, v.brand "
        "FROM analyzed_posts a "
        "JOIN raw_posts r ON r.id = a.post_id "
        "JOIN vehicles v ON v.id = a.vehicle_id "
        + where,
    ).fetchall()
    print(f"待回填: {len(rows)} 条")

    updated = Counter()
    for ap_id, text, vname, vbrand in rows:
        self_words = build_self_words(vname or "", vbrand or "")
        subject, sname = classify(text, self_words)
        if subject == "self":
            sname = vname or ""  # self 帖应填主车型名，classify 不返回车名
        updated[subject] += 1
        if not args.dry_run:
            con.execute(
                "UPDATE analyzed_posts SET subject=?, subject_name=? WHERE id=?",
                (subject, sname or "", ap_id),
            )

    if not args.dry_run:
        con.commit()
    print("分布:", dict(updated))
    if args.dry_run:
        print("(dry-run，未写入)")


if __name__ == "__main__":
    main()
