import logging
import re

import httpx
from simhash import Simhash

logger = logging.getLogger(__name__)

XHS_URL_PATTERNS = [
    re.compile(r"/explore/([a-f0-9]{24})"),
    re.compile(r"/discovery/item/([a-f0-9]{24})"),
    re.compile(r"/user/profile/\w+/([a-f0-9]{24})"),
    re.compile(r"/([a-f0-9]{24})(?:\?|#|$)"),
]


def deduplicate(posts: list[dict], threshold: int = 3) -> list[dict]:
    kept = []
    fingerprints = []  # (Simhash, 对应保留帖) 成对维护，丢弃帖能标记真正的孪生
    for post in sorted(posts, key=lambda p: p.get("published_at") or ""):
        text = f"{post.get('title', '')} {post.get('content', '')}"
        if not text.strip():
            kept.append(post)
            continue
        fp = Simhash(text)
        twin = next((kp for kf, kp in fingerprints if fp.distance(kf) <= threshold), None)
        if twin is not None:
            # 丢弃帖标记其"保留孪生帖"的 URL（原 duplicate_group_id 取
            # kept[-1]["id"] 恒为空串——post dict 无 id 键，死代码）。scheduler
            # 用该键把被丢弃帖的评论搬迁到保留帖上（T2.4：评论 unmatched
            # 根因即"评论先抓、帖后被去重丢弃"）。
            post["duplicate_of_url"] = twin.get("url", "")
        else:
            kept.append(post)
            fingerprints.append((fp, post))
    return kept


async def _resolve_short_link(short_url: str) -> str:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=5) as client:
            resp = await client.get(short_url)
            final_url = str(resp.url)
            # #17：SSRF 白名单——只允许跳转到 xiaohongshu.com（xhslink 是小红书短链）
            if "xiaohongshu.com" not in final_url:
                return short_url  # 重定向到非小红书域，不跟随
            return final_url
    except Exception:
        return short_url


async def resolve_note_id(post_url: str) -> str:
    url = post_url.strip()
    if "xhslink.com" in url:
        url = await _resolve_short_link(url)
    for pattern in XHS_URL_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return url.rsplit("/", 1)[-1].split("?")[0].split("#")[0]
