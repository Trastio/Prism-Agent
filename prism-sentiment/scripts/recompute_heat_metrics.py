"""重算 HeatMetric + 清 defect_themes + 清 AnalyzedPost 冗余。

清理脚本（v1+v2）只改 raw_posts.analysis_status='irrelevant'，没级联重算预计算表：
- HeatMetric 1708 行 created_at=2026-10-04 早于 10-06 清理 → 基于含混入帖旧数据
- defect_themes 14 行 TTL 24h 已过期 → 端点访问自动重算（这里只清表）
- AnalyzedPost 473 行关联 irrelevant raw_post → 看板 JOIN 过滤不显示但表里有冗余

用法：
    python -m scripts.recompute_heat_metrics [--db PATH] [--dry-run]
"""
import argparse
import asyncio
import sqlite3
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from models.schemas import HeatMetric, DefectTheme, AnalyzedPost, RawPost, Vehicle
from pipeline.analysis.heat_calculator import HeatMetricCalculator
from sqlalchemy import delete, select


async def recompute(db_path: str, dry_run: bool = False) -> dict:
    """重算 HeatMetric + 清 defect_themes + 清 AnalyzedPost 冗余。返回统计。"""
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    stats = {"heat_deleted": 0, "heat_recomputed": 0,
             "defect_deleted": 0, "analyzed_orphan_deleted": 0}

    # 1-3. 清表（一个事务）
    async with Session() as session:
        result = await session.execute(delete(HeatMetric))
        stats["heat_deleted"] = result.rowcount
        result = await session.execute(delete(DefectTheme))
        stats["defect_deleted"] = result.rowcount
        irrelevant_ids = (
            await session.execute(
                select(RawPost.id).where(RawPost.analysis_status == "irrelevant")
            )
        ).scalars().all()
        if irrelevant_ids:
            result = await session.execute(
                delete(AnalyzedPost).where(AnalyzedPost.post_id.in_(irrelevant_ids))
            )
            stats["analyzed_orphan_deleted"] = result.rowcount
        await session.commit()

    # 4. 重算 HeatMetric：active 车，近 90 天（calculate_range 内部自 commit）
    async with Session() as session:
        vehicles = (
            await session.execute(
                select(Vehicle).where(Vehicle.status == "active")
            )
        ).scalars().all()

        calc = HeatMetricCalculator(session)
        today = date.today()
        start = today - timedelta(days=90)
        for v in vehicles:
            try:
                await calc.calculate_range(v.id, start, today)
                stats["heat_recomputed"] += 1
            except Exception as e:
                print(f"  ⚠ {v.name} 重算失败: {e}")

    await engine.dispose()
    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/vehicle_sentiment.db")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    stats = asyncio.run(recompute(args.db, args.dry_run))
    print("=== 重算完成 ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
