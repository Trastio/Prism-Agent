"""抽样打印 irrelevant 帖子，供人工核查相关性过滤是否误杀（尤其负面帖）。

背景：启源Q05 negative 仅 3.4%，怀疑相关性过滤误剔了吐槽帖。本脚本随机抽样
30 条 irrelevant 帖，打印 title/content/relevance_score，人工判断是否有误杀。

用法（在项目根目录运行）：
    C:/Users/<you>/Anaconda3/python.exe scripts/audit_irrelevant.py [vehicle_id] [sample_size]
"""
import random
import sqlite3
import sys

DB = "data/vehicle_sentiment.db"
DEFAULT_VID = "67e33f8e-3f37-4855-b705-c83158b77d53"


def main():
    vehicle_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VID
    sample_size = int(sys.argv[2]) if len(sys.argv) > 2 else 30

    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT id, platform, title, substr(content,1,200), relevance_score, published_at "
        "FROM raw_posts WHERE vehicle_id=? AND analysis_status='irrelevant'",
        (vehicle_id,),
    ).fetchall()

    if not rows:
        print(f"vehicle {vehicle_id} 无 irrelevant 帖子")
        return

    total = len(rows)
    print(f"irrelevant 总数: {total}，抽样 {min(sample_size, total)} 条\n" + "=" * 70)
    sample = random.sample(rows, min(sample_size, total))
    for i, (pid, plat, title, content, score, pub) in enumerate(sample, 1):
        print(f"[{i}] platform={plat} score={score} date={pub}")
        print(f"    标题: {title or '(无)'}")
        print(f"    内容: {content}")
        print("-" * 70)
    print("\n核查要点：是否有明显讨论启源Q05的吐槽帖被误标 irrelevant？")
    print(f"误杀比例 = (误杀数 / {len(sample)})，若 >20% 需调整 relevance_filter 规则。")
    conn.close()


if __name__ == "__main__":
    main()
