"""临时脚本：生成评论摘要（使用已抓取的评论）"""
import asyncio
import sys
sys.path.insert(0, ".")

from pipeline.analysis.batch_runner import BatchAnalysisRunner, select_top_posts_for_comments
from models.database import get_session
from sqlalchemy import select, desc
from models.schemas import PostComment


async def main():
    vehicle_id = "67e33f8e-3f37-4855-b705-c83158b77d53"

    async for session in get_session():
        # 检查选中的帖子有多少评论
        top_posts = await select_top_posts_for_comments(session, vehicle_id)
        print(f"[INFO] Selected {len(top_posts)} hot posts\n")

        for i, post in enumerate(top_posts, 1):
            comments_result = await session.execute(
                select(PostComment).where(
                    PostComment.post_id == post.id
                ).order_by(desc(PostComment.likes))
            )
            comments = comments_result.scalars().all()
            print(f"{i}. {post.platform} - {len(comments)} comments (need >=5)")

        # 生成摘要
        print("\n[INFO] Generating summaries...")
        runner = BatchAnalysisRunner(session)
        summary_count = await runner.run_comment_summaries(vehicle_id)
        print(f"[OK] Generated {summary_count} summaries")


if __name__ == "__main__":
    asyncio.run(main())