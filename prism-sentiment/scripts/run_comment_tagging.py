"""评论打标夜跑入口（D3 手动触发模式）。

遍历全部 active 车的待打标评论队列（comment_polarity IS NULL AND dim_sentiment
IS NULL），500 条/批 commit、可断点续跑。

2026-10-20 引擎切换：默认走 DeepSeek v4-flash API（POLARITY_ENGINE=deepseek，
无需 GPU/模型加载）；POLARITY_ENGINE=local 环境变量回退本地 Qwen3-4B
（此时 TAG_IN_SERVICE=1 钥匙仍由本脚本注入）。

用法：
    cd prism-sentiment
    python scripts/run_comment_tagging.py              # DeepSeek（默认）
    POLARITY_ENGINE=local KMP_DUPLICATE_LIB_OK=TRUE python scripts/run_comment_tagging.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
os.environ.setdefault("POLARITY_ENGINE", "deepseek")  # 引擎默认（2026-10-20 切换）
os.environ["TAG_IN_SERVICE"] = "1"  # local 回退时的手动夜跑钥匙（B 决策 2026-10-17）
os.chdir(Path(__file__).resolve().parent.parent)  # DB/adapter 相对路径锚定

from sqlalchemy import select  # noqa: E402
from models.database import async_session  # noqa: E402
from models.schemas import Vehicle  # noqa: E402
from pipeline.analysis.batch_runner import BatchAnalysisRunner  # noqa: E402


async def main() -> int:
    engine = os.environ.get("POLARITY_ENGINE", "deepseek")
    total = 0
    async with async_session() as session:
        vids = (await session.execute(
            select(Vehicle.id, Vehicle.name).where(Vehicle.status == "active")
        )).all()
        print(f"active {len(vids)} 车，极性打标引擎={engine}"
              + ("（本地模型加载 ~60s）…" if engine == "local" else "（DeepSeek API，无需 GPU）…"),
              flush=True)
        for vid, name in vids:
            runner = BatchAnalysisRunner(session)
            n = await runner.run_comment_analysis(vid)
            total += n
            print(f"  [{name}] 本轮打标 {n} 条（累计 {total}）", flush=True)
    print(f"完成：共 {total} 条。剩余队列见 SQL：两列皆空计数。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
