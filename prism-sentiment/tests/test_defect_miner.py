"""Tests: defect_miner — 全量评论聚类 + LLM 簇判定（发酵层数据源）。

覆盖：评论池口径三挂/截断保序/近7天窗、连通分量分簇/孤帖排除/8评论边界/
neg_ratio、LLM 判定混合真假/坏 JSON 降级/伪造 idx 丢弃、编排短路。
LLM 用 monkeypatch mock，不打网络。
"""
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.schemas import (
    AnalyzedPost, Base, PostComment, RawPost, Vehicle,
)


@pytest_asyncio.fixture
async def db():
    """每测独立内存库（避免共享 session-scope engine 的 commit 污染）。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


# ── 评论池 _complaint_pool ──────────────────────────────────────────────────

async def _seed_post(s, vid, pid, sentiment="neutral", author_type="organic",
                     subject="self", analysis_status="analyzed",
                     published_at=None, likes=10):
    """种子一条帖（RawPost + AnalyzedPost）。published_at 默认近 1 天（在 7 天窗内）。"""
    s.add(RawPost(
        id=pid, vehicle_id=vid, source="test", platform="weibo",
        title=f"帖{pid}", content=f"内容{pid}", author="作者",
        url=f"https://x/{pid}",
        published_at=published_at or (datetime.now() - timedelta(days=1)),
        likes=likes, comments=1, shares=0,
        analysis_status=analysis_status, author_type=author_type,
    ))
    s.add(AnalyzedPost(
        id=f"ap-{pid}", post_id=pid, vehicle_id=vid, sentiment=sentiment,
        model_used="test", subject=subject,
    ))


async def _seed_comment(s, cid, pid, vid, content, likes=0):
    s.add(PostComment(
        id=cid, post_id=pid, vehicle_id=vid, content=content,
        author="评论者", likes=likes, platform="weibo",
    ))


@pytest.mark.asyncio
async def test_complaint_pool_excludes_irrelevant_and_official(db):
    """irrelevant 帖 + 官方/经销商帖的评论不进池。"""
    s = db
    s.add(Vehicle(id="v1", name="测试车", brand="测试品牌"))
    await s.commit()
    # relevant organic 帖（应进）
    await _seed_post(s, "v1", "p1", sentiment="negative", author_type="organic")
    # irrelevant 帖（RELEVANT_ONLY 排除）
    await _seed_post(s, "v1", "p2", sentiment="negative", analysis_status="irrelevant")
    # 官方帖（AUTHENTIC_AUTHOR 排除）
    await _seed_post(s, "v1", "p3", sentiment="positive", author_type="brand_official")
    # 经销商帖
    await _seed_post(s, "v1", "p4", sentiment="positive", author_type="dealer")
    await s.commit()
    await _seed_comment(s, "c1", "p1", "v1", "刹车异响", likes=5)
    await _seed_comment(s, "c2", "p2", "v1", "无关帖评论", likes=99)
    await _seed_comment(s, "c3", "p3", "v1", "官方帖评论", likes=99)
    await _seed_comment(s, "c4", "p4", "v1", "经销商帖评论", likes=99)
    await s.commit()

    from pipeline.analysis.defect_miner import _complaint_pool
    pool = await _complaint_pool(s, "v1")
    post_ids = {c["post_id"] for c in pool}
    assert post_ids == {"p1"}  # 只剩 organic relevant 帖的评论
    assert pool[0]["content"] == "刹车异响"
    assert pool[0]["post_sentiment"] == "negative"  # 挂帖情感回填


@pytest.mark.asyncio
async def test_complaint_pool_excludes_competitor_subject(db):
    """subject=competitor 的帖不进池（SELF_ONLY）。"""
    s = db
    s.add(Vehicle(id="v1", name="测试车", brand="测试品牌"))
    await s.commit()
    await _seed_post(s, "v1", "p1", subject="self", sentiment="negative")
    await _seed_post(s, "v1", "p2", subject="competitor", sentiment="negative")
    await s.commit()
    await _seed_comment(s, "c1", "p1", "v1", "自车型评论")
    await _seed_comment(s, "c2", "p2", "v1", "竞品评论")
    await s.commit()

    from pipeline.analysis.defect_miner import _complaint_pool
    pool = await _complaint_pool(s, "v1")
    assert {c["post_id"] for c in pool} == {"p1"}


@pytest.mark.asyncio
async def test_complaint_pool_seven_day_window(db):
    """近 7 天窗外的帖评论不进池；NULL published_at 用 collected_at 兜底。"""
    s = db
    s.add(Vehicle(id="v1", name="测试车", brand="测试品牌"))
    await s.commit()
    # 窗内
    await _seed_post(s, "v1", "p1", sentiment="negative",
                     published_at=datetime.now() - timedelta(days=2))
    # 窗外（10 天前）
    await _seed_post(s, "v1", "p2", sentiment="negative",
                     published_at=datetime.now() - timedelta(days=10))
    # published_at=NULL，collected_at=now（coalesce 兜底应进）
    s.add(RawPost(
        id="p3", vehicle_id="v1", source="test", platform="weibo",
        title="帖p3", content="内容p3", author="作者", url="https://x/p3",
        published_at=None, collected_at=datetime.now(),
        likes=10, comments=1, shares=0,
        analysis_status="analyzed", author_type="organic",
    ))
    s.add(AnalyzedPost(id="ap-p3", post_id="p3", vehicle_id="v1",
                       sentiment="negative", model_used="test", subject="self"))
    await s.commit()
    await _seed_comment(s, "c1", "p1", "v1", "窗内评论")
    await _seed_comment(s, "c2", "p2", "v1", "窗外评论")
    await _seed_comment(s, "c3", "p3", "v1", "NULL时间评论")
    await s.commit()

    from pipeline.analysis.defect_miner import _complaint_pool
    pool = await _complaint_pool(s, "v1")
    post_ids = {c["post_id"] for c in pool}
    assert post_ids == {"p1", "p3"}  # p2 窗外排除；p3 coalesce 兜底进


@pytest.mark.asyncio
async def test_complaint_pool_orders_by_likes_and_caps(db, monkeypatch):
    """likes 降序 + 5000 上限截断保序。"""
    s = db
    s.add(Vehicle(id="v1", name="测试车", brand="测试品牌"))
    await s.commit()
    await _seed_post(s, "v1", "p1", sentiment="neutral")
    await s.commit()
    # 3 条评论，likes 乱序
    await _seed_comment(s, "c1", "p1", "v1", "低赞", likes=1)
    await _seed_comment(s, "c2", "p1", "v1", "高赞", likes=100)
    await _seed_comment(s, "c3", "p1", "v1", "中赞", likes=50)
    await s.commit()

    from pipeline.analysis import defect_miner
    monkeypatch.setattr(defect_miner, "_MAX_COMMENTS", 2)  # 压低上限验证截断保序
    pool = await defect_miner._complaint_pool(s, "v1")
    assert len(pool) == 2
    assert pool[0]["likes"] == 100  # 降序
    assert pool[1]["likes"] == 50


@pytest.mark.asyncio
async def test_complaint_pool_empty_when_no_posts(db):
    """无口径内帖 → 空池。"""
    from pipeline.analysis.defect_miner import _complaint_pool
    pool = await _complaint_pool(db, "no-such-vehicle")
    assert pool == []


# ── 聚类 _cluster_complaints ────────────────────────────────────────────────

def _fake_extract(text, top_k=5, generic_names=None):
    """确定性切词：测试评论以空格分隔关键词（绕过 jieba TF-IDF 抖动）。"""
    return [w for w in text.split() if w]


def _mk_pool(keywords_groups, posts_per_group, comments_per_post, sentiment="negative"):
    """构造评论池：每组关键词 × 多帖 × 多评论。

    keywords_groups: [[kw1, kw2], [kw3, kw4]] 每组关键词
    返回 list[dict]，content=空格连接的关键词（供 _fake_extract 解析）。
    """
    pool = []
    for gi, kws in enumerate(keywords_groups):
        content = " ".join(kws)
        for pi in range(posts_per_group):
            pid = f"p{gi}-{pi}"
            for ci in range(comments_per_post):
                pool.append({
                    "post_id": pid, "content": content, "likes": comments_per_post - ci,
                    "post_sentiment": sentiment,
                })
    return pool


def test_cluster_two_disjoint_groups(monkeypatch):
    """两簇不相连关键词 → 正确分两个簇。"""
    from pipeline.analysis import defect_miner
    monkeypatch.setattr(defect_miner, "extract_keywords", _fake_extract)
    # 刹车组 vs 续航组，各 2 帖 × 8 评论 = 16 评论/组
    pool = _mk_pool(
        [["刹车", "异响"], ["续航", "虚标"]],
        posts_per_group=2, comments_per_post=8,
    )
    clusters = defect_miner._cluster_complaints(pool)
    assert len(clusters) == 2
    # 两簇帖集合不交叠
    all_posts = [set(c["posts"]) for c in clusters]
    assert all_posts[0].isdisjoint(all_posts[1])
    for c in clusters:
        assert c["comments"] == 16
        assert len(c["posts"]) == 2
        assert c["neg_ratio"] == 1.0  # 全 negative


def test_cluster_single_post_excluded(monkeypatch):
    """孤帖（posts=1）即使评论数够也不进簇。"""
    from pipeline.analysis import defect_miner
    monkeypatch.setattr(defect_miner, "extract_keywords", _fake_extract)
    # 单帖 × 10 评论（comments>=8 但 posts=1）
    pool = []
    for i in range(10):
        pool.append({
            "post_id": "only", "content": "刹车 异响", "likes": 10 - i,
            "post_sentiment": "negative",
        })
    clusters = defect_miner._cluster_complaints(pool)
    assert clusters == []  # 孤帖排除


def test_cluster_comment_threshold_boundary(monkeypatch):
    """7 评论不进（<8），8 评论进（>=8）。"""
    from pipeline.analysis import defect_miner
    monkeypatch.setattr(defect_miner, "extract_keywords", _fake_extract)

    # 7 评论 × 2 帖 → 不进
    pool7 = _mk_pool([["刹车", "异响"]], posts_per_group=2, comments_per_post=4)  # 8 评论
    # 改成 7：删一条
    pool7 = pool7[:7]
    # 但删一条后 posts 可能仍 2，comments=7 < 8
    assert len({c["post_id"] for c in pool7}) == 2
    clusters7 = defect_miner._cluster_complaints(pool7)
    assert clusters7 == []

    # 8 评论 × 2 帖 → 进
    pool8 = _mk_pool([["刹车", "异响"]], posts_per_group=2, comments_per_post=4)  # 8
    clusters8 = defect_miner._cluster_complaints(pool8)
    assert len(clusters8) == 1
    assert clusters8[0]["comments"] == 8


def test_cluster_neg_ratio_mixed_sentiment(monkeypatch):
    """neg_ratio = 簇内负面帖评论占比（混合情感计算）。"""
    from pipeline.analysis import defect_miner
    monkeypatch.setattr(defect_miner, "extract_keywords", _fake_extract)
    # 2 帖 × 8 评论 = 16；其中 4 negative + 12 positive → neg_ratio=0.25
    pool = _mk_pool([["刹车", "异响"]], posts_per_group=2, comments_per_post=8,
                    sentiment="positive")
    # 把前 4 条改 negative
    for c in pool[:4]:
        c["post_sentiment"] = "negative"
    clusters = defect_miner._cluster_complaints(pool)
    assert len(clusters) == 1
    assert clusters[0]["neg_ratio"] == 0.25
    # score = 16 × (0.5 + 0.25) = 12
    assert clusters[0]["score"] == 12.0


def test_cluster_top_k_limit(monkeypatch):
    """超过 K=5 个簇只取 top5（按 score）。"""
    from pipeline.analysis import defect_miner
    monkeypatch.setattr(defect_miner, "extract_keywords", _fake_extract)
    monkeypatch.setattr(defect_miner, "_TOP_K", 2)
    # 3 个不相连簇，各 2 帖 × 8 评论
    pool = _mk_pool(
        [["刹车", "异响"], ["续航", "虚标"], ["车机", "死机"]],
        posts_per_group=2, comments_per_post=8,
    )
    clusters = defect_miner._cluster_complaints(pool)
    assert len(clusters) <= 2  # top K=2


def test_cluster_empty_pool(monkeypatch):
    """空池 → 空簇列表。"""
    from pipeline.analysis import defect_miner
    monkeypatch.setattr(defect_miner, "extract_keywords", _fake_extract)
    assert defect_miner._cluster_complaints([]) == []


def test_cluster_no_keywords_filtered(monkeypatch):
    """所有评论切词后无关键词 → 空簇。"""
    from pipeline.analysis import defect_miner
    monkeypatch.setattr(defect_miner, "extract_keywords", lambda *a, **k: [])
    pool = [{"post_id": "p1", "content": "x", "likes": 1, "post_sentiment": "negative"}]
    assert defect_miner._cluster_complaints(pool) == []


# ── LLM 判定 _judge_defect_clusters ─────────────────────────────────────────

def _mk_cluster(idx_unused, keywords=None, comments=10, posts=None, neg_ratio=0.8):
    return {
        "keywords": keywords or ["刹车", "异响"],
        "comments": comments,
        "posts": posts or ["p1", "p2"],
        "neg_ratio": neg_ratio,
        "score": comments * (0.5 + neg_ratio),
        "rep_comments": [
            {"content": "刹车异响严重", "likes": 5, "post_id": "p1"},
            {"content": "刹车失灵了", "likes": 3, "post_id": "p2"},
            {"content": "4S店说正常", "likes": 1, "post_id": "p1"},
        ],
    }


@pytest.mark.asyncio
async def test_judge_mixed_defect_and_non_defect(monkeypatch):
    """混合判定：簇0 is_defect=true 保留，簇1 is_defect=false 丢弃。"""
    from pipeline.analysis import defect_miner
    clusters = [_mk_cluster(0, ["刹车", "异响"]), _mk_cluster(1, ["降价", "优惠"])]

    fake_resp = '{"clusters": [{"idx": 0, "is_defect": true, "name": "刹车异响", "severity": "high", "suggestion": "排查刹车片"}, {"idx": 1, "is_defect": false, "name": "降价", "severity": "low", "suggestion": ""}]}'
    monkeypatch.setattr(defect_miner, "call_llm", lambda *a, **k: _async_return(fake_resp))

    result = await defect_miner._judge_defect_clusters(clusters)
    assert len(result) == 1
    assert result[0]["name"] == "刹车异响"
    assert result[0]["severity"] == "high"
    assert result[0]["suggestion"] == "排查刹车片"
    assert result[0]["comments"] == 10
    assert result[0]["posts"] == ["p1", "p2"]
    assert len(result[0]["rep_comments"]) == 3


@pytest.mark.asyncio
async def test_judge_string_boolean_false_discarded(monkeypatch):
    """LLM 返回字符串 'false'（弱模型常见）时，非缺陷簇必须被丢弃。

    回归 review Important#1：bool('false')==True 会导致 if not j.get('is_defect') 误留。
    """
    from pipeline.analysis import defect_miner
    clusters = [_mk_cluster(0, ["刹车", "异响"]), _mk_cluster(1, ["天气", "不错"])]
    # is_defect 用字符串 "false"——旧代码 bool("false")==True 会误留簇1
    fake_resp = '{"clusters": [{"idx": 0, "is_defect": "true", "name": "刹车异响", "severity": "high", "suggestion": ""}, {"idx": 1, "is_defect": "false", "name": "天气", "severity": "low", "suggestion": ""}]}'
    monkeypatch.setattr(defect_miner, "call_llm", lambda *a, **k: _async_return(fake_resp))
    result = await defect_miner._judge_defect_clusters(clusters)
    assert len(result) == 1
    assert result[0]["name"] == "刹车异响"


@pytest.mark.asyncio
async def test_judge_duplicate_idx_deduped(monkeypatch):
    """LLM 返回重复 idx 时，只保留第一个（去重）。"""
    from pipeline.analysis import defect_miner
    clusters = [_mk_cluster(0, ["刹车", "异响"])]
    fake_resp = '{"clusters": [{"idx": 0, "is_defect": true, "name": "刹车异响", "severity": "high", "suggestion": ""}, {"idx": 0, "is_defect": true, "name": "重复簇", "severity": "low", "suggestion": ""}]}'
    monkeypatch.setattr(defect_miner, "call_llm", lambda *a, **k: _async_return(fake_resp))
    result = await defect_miner._judge_defect_clusters(clusters)
    assert len(result) == 1
    assert result[0]["name"] == "刹车异响"


@pytest.mark.asyncio
async def test_judge_severity_chinese_normalized(monkeypatch):
    """LLM 返回中文 severity（高/中/低）时归一化为 high/mid/low（CSS 只认英文）。"""
    from pipeline.analysis import defect_miner
    clusters = [_mk_cluster(0, ["续航", "虚标"])]
    fake_resp = '{"clusters": [{"idx": 0, "is_defect": true, "name": "续航虚标", "severity": "高", "suggestion": ""}]}'
    monkeypatch.setattr(defect_miner, "call_llm", lambda *a, **k: _async_return(fake_resp))
    result = await defect_miner._judge_defect_clusters(clusters)
    assert len(result) == 1
    assert result[0]["severity"] == "high"  # "高" → "high"


@pytest.mark.asyncio
async def test_judge_prompt_contains_vehicle_anchor(monkeypatch):
    """车型锚（2026-10-20）：judge prompt 必须带本车名 + 他车簇判非缺陷指令——
    防跨车簇（对比帖评论谈他车）被收成本车缺陷。"""
    from pipeline.analysis import defect_miner
    captured = {}
    fake_resp = '{"clusters": [{"idx": 0, "is_defect": true, "name": "刹车异响", "severity": "high", "suggestion": ""}]}'

    async def _capture(prompt, *a, **k):
        captured["prompt"] = prompt
        return fake_resp
    monkeypatch.setattr(defect_miner, "call_llm", _capture)
    await defect_miner._judge_defect_clusters([_mk_cluster(0)], vehicle_name="风云T7")
    assert "风云T7" in captured["prompt"]
    assert "主要讨论其他车型" in captured["prompt"]  # 他车簇 is_defect=false 指令在


@pytest.mark.asyncio
async def test_judge_bad_json_raises(monkeypatch):
    """坏 JSON → raise DefectJudgeError（2026-10-20 改：失败不得伪装成"无缺陷"，
    上游据此保旧载荷——原静默返回 [] 会把好载荷清空覆盖，T11 实证）。"""
    from pipeline.analysis import defect_miner
    clusters = [_mk_cluster(0)]
    monkeypatch.setattr(defect_miner, "call_llm", lambda *a, **k: _async_return("这不是JSON"))
    with pytest.raises(defect_miner.DefectJudgeError):
        await defect_miner._judge_defect_clusters(clusters)


@pytest.mark.asyncio
async def test_judge_llm_exception_raises(monkeypatch):
    """LLM 调用抛异常 → raise DefectJudgeError。"""
    from pipeline.analysis import defect_miner
    clusters = [_mk_cluster(0)]

    async def _raise(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(defect_miner, "call_llm", _raise)
    with pytest.raises(defect_miner.DefectJudgeError):
        await defect_miner._judge_defect_clusters(clusters)


@pytest.mark.asyncio
async def test_judge_forged_idx_dropped(monkeypatch):
    """伪造/越界 idx 丢弃（不崩溃）。"""
    from pipeline.analysis import defect_miner
    clusters = [_mk_cluster(0)]  # 只有 idx 0 合法
    fake_resp = '{"clusters": [{"idx": 5, "is_defect": true, "name": "x", "severity": "high", "suggestion": ""}, {"idx": 0, "is_defect": true, "name": "刹车异响", "severity": "high", "suggestion": ""}]}'
    monkeypatch.setattr(defect_miner, "call_llm", lambda *a, **k: _async_return(fake_resp))
    result = await defect_miner._judge_defect_clusters(clusters)
    assert len(result) == 1
    assert result[0]["name"] == "刹车异响"  # idx=5 被丢，idx=0 保留


@pytest.mark.asyncio
async def test_judge_empty_clusters_short_circuits():
    """空簇列表短路返回空（不调 LLM）。"""
    from pipeline.analysis import defect_miner
    result = await defect_miner._judge_defect_clusters([])
    assert result == []


# ── 编排 mine_defect_themes ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mine_defect_themes_end_to_end(db, monkeypatch):
    """编排：池→聚类→判定 全链路（聚类 mock 切词，LLM mock 判定）。"""
    from pipeline.analysis import defect_miner
    s = db
    s.add(Vehicle(id="v1", name="测试车", brand="测试品牌"))
    await s.commit()
    # 2 帖，各 8 条评论，content 用空格关键词（供 _fake_extract）
    await _seed_post(s, "v1", "p1", sentiment="negative")
    await _seed_post(s, "v1", "p2", sentiment="negative")
    await s.commit()
    for i in range(8):
        await _seed_comment(s, f"c1-{i}", "p1", "v1", "刹车 异响", likes=8 - i)
        await _seed_comment(s, f"c2-{i}", "p2", "v1", "刹车 异响", likes=8 - i)
    await s.commit()

    monkeypatch.setattr(defect_miner, "extract_keywords", _fake_extract)
    fake_resp = '{"clusters": [{"idx": 0, "is_defect": true, "name": "刹车异响", "severity": "high", "suggestion": "排查刹车片"}]}'
    monkeypatch.setattr(defect_miner, "call_llm", lambda *a, **k: _async_return(fake_resp))

    themes, degraded = await defect_miner.mine_defect_themes("v1", s)
    assert degraded is False
    assert len(themes) == 1
    assert themes[0]["name"] == "刹车异响"
    assert themes[0]["comments"] == 16
    assert set(themes[0]["posts"]) == {"p1", "p2"}


@pytest.mark.asyncio
async def test_mine_defect_themes_short_circuits_on_empty_pool(db):
    """无评论 → 池空 → 短路返回空（不进聚类/LLM）。"""
    from pipeline.analysis import defect_miner
    s = db
    s.add(Vehicle(id="v1", name="测试车", brand="测试品牌"))
    await s.commit()
    themes, degraded = await defect_miner.mine_defect_themes("v1", s)
    assert themes == []
    assert degraded is False


@pytest.mark.asyncio
async def test_mine_defect_themes_short_circuits_on_no_clusters(db, monkeypatch):
    """有评论但聚不出簇（孤帖）→ 短路返回空（不调 LLM）。"""
    from pipeline.analysis import defect_miner
    s = db
    s.add(Vehicle(id="v1", name="测试车", brand="测试品牌"))
    await s.commit()
    await _seed_post(s, "v1", "p1", sentiment="negative")
    await s.commit()
    # 单帖 10 评论 → posts=1 不进簇
    for i in range(10):
        await _seed_comment(s, f"c-{i}", "p1", "v1", "刹车 异响", likes=10 - i)
    await s.commit()
    monkeypatch.setattr(defect_miner, "extract_keywords", _fake_extract)

    called = {"n": 0}

    async def _no_call(*a, **k):
        called["n"] += 1
        return ""
    monkeypatch.setattr(defect_miner, "call_llm", _no_call)
    themes, degraded = await defect_miner.mine_defect_themes("v1", s)
    assert themes == []
    assert degraded is False
    assert called["n"] == 0  # LLM 未被调用


@pytest.mark.asyncio
async def test_mine_defect_themes_degraded_on_judge_failure(db, monkeypatch):
    """judge 失败 → ([], True)：调用方保旧载荷信号（不清空覆盖）。"""
    from pipeline.analysis import defect_miner
    s = db
    s.add(Vehicle(id="v1", name="测试车", brand="测试品牌"))
    await s.commit()
    await _seed_post(s, "v1", "p1", sentiment="negative")
    await _seed_post(s, "v1", "p2", sentiment="negative")
    await s.commit()
    for i in range(8):
        await _seed_comment(s, f"c1-{i}", "p1", "v1", "刹车 异响", likes=8 - i)
        await _seed_comment(s, f"c2-{i}", "p2", "v1", "刹车 异响", likes=8 - i)
    await s.commit()
    monkeypatch.setattr(defect_miner, "extract_keywords", _fake_extract)

    async def _raise(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(defect_miner, "call_llm", _raise)
    themes, degraded = await defect_miner.mine_defect_themes("v1", s)
    assert themes == []
    assert degraded is True


# ── 端点 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_defect_themes_endpoint(db, monkeypatch):
    """GET /defect-themes/{vehicle_id} 返回 mine_defect_themes 结果。"""
    from api.main import app
    from models.database import get_session
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    from httpx import ASGITransport, AsyncClient

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    from models.schemas import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = override

    # mock 整条管线返回固定结果（2026-10-20 起 mine 返回 (themes, degraded) 元组）
    async def _fake_mine(vid, session, start=None, end=None):
        return ([{"name": "刹车异响", "severity": "high", "suggestion": "排查",
                  "comments": 10, "posts": ["p1", "p2"],
                  "neg_ratio": 0.9, "rep_comments": [], "keywords": ["刹车", "异响"]}],
                False)

    import pipeline.analysis.defect_miner as dm
    monkeypatch.setattr(dm, "mine_defect_themes", _fake_mine)

    async with factory() as s:
        s.add(Vehicle(id="v1", name="测试车", brand="测试品牌"))
        await s.commit()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/api/dashboard/defect-themes/v1")
            assert r.status_code == 200
            data = r.json()
            assert len(data) == 1
            assert data[0]["name"] == "刹车异响"

            # 404 for unknown vehicle
            r2 = await c.get("/api/dashboard/defect-themes/no-such")
            assert r2.status_code == 404
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


# ── 端点 TTL 读库 ──────────────────────────────────────────────────────────

def _fixed_clusters():
    """mine_defect_themes 的固定返回（供 mock）。"""
    return [{"name": "刹车异响", "severity": "high", "suggestion": "排查刹车片",
             "comments": 10, "posts": ["p1", "p2"], "neg_ratio": 0.9,
             "rep_comments": [], "keywords": ["刹车", "异响"]}]


@pytest.mark.asyncio
async def test_defect_themes_endpoint_reads_db_within_ttl(monkeypatch):
    """库有数据且<24h → 直接读库返回，不调 mine_defect_themes（不烧 LLM）。"""
    from api.main import app
    from models.database import get_session
    from models.schemas import Base, DefectTheme, Vehicle
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    from httpx import ASGITransport, AsyncClient

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = override

    import json as _json
    async with factory() as s:
        s.add(Vehicle(id="v1", name="测试车", brand="测试品牌"))
        # 预置一行新鲜数据（computed_at=now，TTL 内）
        s.add(DefectTheme(id="dt1", vehicle_id="v1",
                         payload=_json.dumps(_fixed_clusters()),
                         computed_at=datetime.now()))
        await s.commit()

    # mine_defect_themes 若被调用即失败
    called = {"n": 0}

    async def _should_not_call(*a, **k):
        called["n"] += 1
        return _fixed_clusters()

    import pipeline.analysis.defect_miner as dm
    monkeypatch.setattr(dm, "mine_defect_themes", _should_not_call)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/api/dashboard/defect-themes/v1")
            assert r.status_code == 200
            data = r.json()
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["name"] == "刹车异响"
        assert called["n"] == 0  # 未调 mine（读库命中）
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_defect_themes_endpoint_recomputes_when_ttl_expired(monkeypatch):
    """库有数据但>24h → 重算 + 落库新结果。"""
    from api.main import app
    from models.database import get_session
    from models.schemas import Base, DefectTheme, Vehicle
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    from httpx import ASGITransport, AsyncClient

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = override

    import json as _json
    stale = datetime.utcnow() - timedelta(hours=25)  # 超过 24h（T3.1：与 DB UTC 一致）
    async with factory() as s:
        s.add(Vehicle(id="v1", name="测试车", brand="测试品牌"))
        s.add(DefectTheme(id="dt-stale", vehicle_id="v1",
                         payload=_json.dumps([{"name": "旧结果"}]),
                         computed_at=stale))
        await s.commit()

    import pipeline.analysis.defect_miner as dm
    monkeypatch.setattr(dm, "mine_defect_themes",
                        lambda *a, **k: _async_return((_fixed_clusters(), False)))

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/api/dashboard/defect-themes/v1")
            assert r.status_code == 200
            data = r.json()
            assert data[0]["name"] == "刹车异响"  # 新结果，非"旧结果"
        # 落库新结果：旧行被删，新行 computed_at 新鲜
        async with factory() as s:
            from sqlalchemy import select
            rows = (await s.execute(
                select(DefectTheme).where(DefectTheme.vehicle_id == "v1")
            )).scalars().all()
            assert len(rows) == 1  # 旧行已删，只剩新行
            assert rows[0].computed_at > stale
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_defect_themes_endpoint_degraded_keeps_stale(monkeypatch):
    """TTL 过期 + mine degraded → 返回旧载荷且不落库（防清空覆盖，T11 实证路径）。"""
    from api.main import app
    from models.database import get_session
    from models.schemas import Base, DefectTheme, Vehicle
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    from httpx import ASGITransport, AsyncClient

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = override

    import json as _json
    stale = datetime.utcnow() - timedelta(hours=25)
    async with factory() as s:
        s.add(Vehicle(id="v1", name="测试车", brand="测试品牌"))
        s.add(DefectTheme(id="dt-stale", vehicle_id="v1",
                         payload=_json.dumps([{"name": "旧结果"}]),
                         computed_at=stale))
        await s.commit()

    import pipeline.analysis.defect_miner as dm
    monkeypatch.setattr(dm, "mine_defect_themes",
                        lambda *a, **k: _async_return(([], True)))  # LLM 失败信号

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/api/dashboard/defect-themes/v1")
            assert r.status_code == 200
            assert r.json()[0]["name"] == "旧结果"  # 返回旧载荷，非空列表
        # 库内旧行原封不动（未被空覆盖）
        async with factory() as s:
            from sqlalchemy import select
            rows = (await s.execute(
                select(DefectTheme).where(DefectTheme.vehicle_id == "v1")
            )).scalars().all()
            assert len(rows) == 1
            assert _json.loads(rows[0].payload)[0]["name"] == "旧结果"
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_defect_themes_endpoint_recomputes_when_no_data(monkeypatch):
    """库空 → 重算 + 落库。"""
    from api.main import app
    from models.database import get_session
    from models.schemas import Base, DefectTheme, Vehicle
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool
    from httpx import ASGITransport, AsyncClient

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = override

    async with factory() as s:
        s.add(Vehicle(id="v1", name="测试车", brand="测试品牌"))
        await s.commit()

    import pipeline.analysis.defect_miner as dm
    monkeypatch.setattr(dm, "mine_defect_themes",
                        lambda *a, **k: _async_return((_fixed_clusters(), False)))

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/api/dashboard/defect-themes/v1")
            assert r.status_code == 200
            assert r.json()[0]["name"] == "刹车异响"
        # 落库验证
        async with factory() as s:
            from sqlalchemy import select
            rows = (await s.execute(
                select(DefectTheme).where(DefectTheme.vehicle_id == "v1")
            )).scalars().all()
            assert len(rows) == 1
            import json as _json
            assert _json.loads(rows[0].payload) == _fixed_clusters()
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


# ── helpers ─────────────────────────────────────────────────────────────────

async def _async_return(value):
    """把同步值包成 awaitable（用于 mock call_llm 的 lambda）。"""
    return value
