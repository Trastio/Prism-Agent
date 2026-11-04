# published_at 采集层根治 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让抖音/微博/小红书新采集帖产出精确 `published_at`，并修复 event_tracker 用 `now()` 兜底 NULL 的独立 bug。

**Architecture:** 采集层新增统一解析函数 `_parse_datetime` 收口所有时间格式（Unix/ISO/微博英文串）；`_make_post`/`_make_comment` 切换到它；抖音 JS 读 `create_time`、小红书 JS 读日期元素；event_tracker 去掉 `or datetime.now()` 让 None 透传给本就能容错的下游。

**Tech Stack:** Python + FastAPI + SQLAlchemy async + SQLite；CDP Proxy（`localhost:3456`）+ Chrome（`:9222`）用于实采；pytest + pytest-asyncio。

**Spec:** `docs/superpowers/specs/2026-06-29-published-at-collection-root-fix-design.md`

---

## File Structure

| 文件 | 职责 | 动作 |
|------|------|------|
| `pipeline/collectors/cdp_collector.py` | 采集 + 标准化 | 新增 `_parse_datetime`；改 `_make_post`/`_make_comment`；抖音 `SEARCH_FETCH_JS` + `_search_douyin`；小红书 `DETAIL_JS` + `_search_xhs` |
| `pipeline/analysis/event_tracker.py` | 事件检测 | 484 行去掉 `or datetime.now()` |
| `tests/test_cdp_collector.py` | 采集层测试 | 加 `_parse_datetime` / `_make_post` 时解析 / 抖音 / 小红书 测试 |
| `tests/test_event_tracker.py` | 事件测试 | 加 None published_at 容错回归测试 |
| `scripts/diagnose_published_at.py` | 侦察三平台真实响应（**需 CDP 环境**） | 新建 |
| `scripts/verify_published_at.py` | 实采验证 DB 非 NULL（**需 CDP 环境**） | 新建 |

## Task 依赖与并行

- Task 1 → Task 2（`_make_post` 依赖 `_parse_datetime`）
- Task 3（侦察）→ Task 4、Task 5（JS 字段/选择器基于侦察结果）
- **Task 4 ‖ Task 5 ‖ Task 6** 可并行（抖音/小红书/event_tracker 互相独立）
- Task 7（实采）依赖 1-6 全完成

---

## Task 1: `_parse_datetime` 统一解析函数

**Files:**
- Modify: `pipeline/collectors/cdp_collector.py`（紧邻 `_ts_to_iso`，约 161 行后）
- Test: `tests/test_cdp_collector.py`（`TestHelpers` 类内 + 顶部 import）

- [ ] **Step 1: 加顶部 import + 写失败测试**

在 `tests/test_cdp_collector.py` 顶部 import 块（8-20 行）的 `from pipeline.collectors.cdp_collector import (...)` 中加入 `_parse_datetime`：

```python
from pipeline.collectors.cdp_collector import (
    CdpClient,
    CdpCollector,
    CdpError,
    DouyinExtractor,
    KuaishouExtractor,
    WeiboExtractor,
    XiaohongshuExtractor,
    _safe_int,
    _ts_to_iso,
    _parse_datetime,
    _make_post,
    _make_comment,
)
```

在 `TestHelpers` 类（73 行起）末尾、`test_ts_to_iso_empty`（86-87 行）之后加入：

```python
    def test_parse_datetime_seconds(self):
        assert _parse_datetime(1748217600) == "2025-05-26T00:00:00"

    def test_parse_datetime_milliseconds(self):
        assert _parse_datetime(1748217600000) == "2025-05-26T00:00:00"

    def test_parse_datetime_iso(self):
        assert _parse_datetime("2025-06-29T10:00:00") == "2025-06-29T10:00:00"

    def test_parse_datetime_weibo_english(self):
        assert _parse_datetime("Sun Jun 29 10:00:00 +0800 2025") == "2025-06-29T10:00:00"

    def test_parse_datetime_empty_and_none(self):
        assert _parse_datetime("") == ""
        assert _parse_datetime(None) == ""

    def test_parse_datetime_garbage(self):
        assert _parse_datetime("not a date") == ""
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_cdp_collector.py::TestHelpers -v`
Expected: FAIL（`ImportError: cannot import name '_parse_datetime'`）

- [ ] **Step 3: 实现 `_parse_datetime`**

在 `pipeline/collectors/cdp_collector.py` 的 `_ts_to_iso` 函数（145-161 行）**之后**插入：

```python
def _parse_datetime(raw) -> str:
    """Parse any timestamp format into a clean ISO-8601 string.

    Handles Unix seconds/ms, ISO-8601, and Weibo's English format
    ("Sun Jun 29 10:00:00 +0800 2025"). Returns "" on any failure so
    callers never crash and posts are never dropped for a bad timestamp.
    """
    if not raw:
        return ""
    # 1. Numeric timestamp (Unix seconds or ms)
    try:
        return _ts_to_iso(int(float(raw)))
    except (ValueError, TypeError):
        pass
    # 2. ISO-8601 (news sources / already-normalised)
    try:
        return datetime.fromisoformat(str(raw)).strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        pass
    # 3. Weibo English: "Sun Jun 29 10:00:00 +0800 2025"
    try:
        return datetime.strptime(str(raw), "%a %b %d %H:%M:%S %z %Y").strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        pass
    return ""
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_cdp_collector.py::TestHelpers -v`
Expected: PASS（6 个 `_parse_datetime` 测试全绿）

> ⚠️ 若 `test_parse_datetime_weibo_english` 失败（中文 Windows locale 导致 `%b` 不认 "Jun"），在 Step 3 微博分支后再加一个 `email.utils.parsedate_to_datetime` fallback；该问题由 Task 3 侦察实测确认。

- [ ] **Step 5: Commit**

```bash
git add pipeline/collectors/cdp_collector.py tests/test_cdp_collector.py
git commit -m "feat(cdp): _parse_datetime 统一时间解析（Unix/ISO/微博英文串）"
```

---

## Task 2: `_make_post`/`_make_comment` 切换到 `_parse_datetime`

**Files:**
- Modify: `pipeline/collectors/cdp_collector.py:188`（`_make_post`）、`:209`（`_make_comment`）
- Test: `tests/test_cdp_collector.py`（`TestHelpers` 类内）

- [ ] **Step 1: 写失败测试**

在 `TestHelpers` 类末尾加入：

```python
    def test_make_post_parses_int_timestamp(self):
        p = _make_post("标题", "内容", "作者", "http://x.com", 1, 2, 3, "dy", 1748217600)
        assert p["published_at"] == "2025-05-26T00:00:00"

    def test_make_post_parses_weibo_english(self):
        p = _make_post("微博", "内容", "u", "http://wb.cn", 1, 0, 0, "wb",
                       "Sun Jun 29 10:00:00 +0800 2025")
        assert p["published_at"] == "2025-06-29T10:00:00"

    def test_make_comment_parses_timestamp(self):
        c = _make_comment("评论", "u", 1, "wb", "http://wb.cn", "1", 1748217600)
        assert c["published_at"] == "2025-05-26T00:00:00"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_cdp_collector.py::TestHelpers::test_make_post_parses_int_timestamp tests/test_cdp_collector.py::TestHelpers::test_make_post_parses_weibo_english tests/test_cdp_collector.py::TestHelpers::test_make_comment_parses_timestamp -v`
Expected: FAIL（`_make_post` 仍用 `_ts_to_iso`，传入 int 时间戳/微博串返回 `""` 或原值）

- [ ] **Step 3: 改 `_make_post`（188 行）**

```python
# 旧
"published_at": _ts_to_iso(published_at) or published_at,
# 新
"published_at": _parse_datetime(published_at),
```

- [ ] **Step 4: 改 `_make_comment`（209 行）**

```python
# 旧
"published_at": published_at,
# 新
"published_at": _parse_datetime(published_at),
```

- [ ] **Step 5: 跑全量采集测试确认无回归**

Run: `python -m pytest tests/test_cdp_collector.py -v`
Expected: PASS（含既有 `test_make_post_all_fields`——传入 ISO 字符串经 `_parse_datetime` 仍返回原 ISO；微博/抖音/小红书采集测试不受影响，因为它们 mock 的 detail 数据不含 published_at 字段，走默认 `""`）

- [ ] **Step 6: Commit**

```bash
git add pipeline/collectors/cdp_collector.py tests/test_cdp_collector.py
git commit -m "refactor(cdp): _make_post/_make_comment 改用 _parse_datetime 收口时间格式"
```

---

## Task 3: 侦察三平台真实响应（需 CDP 环境）

> 侦察前置（spec §15）：实采前确认抖音 `create_time` 字段名/类型、微博 `created_at` 真实格式、小红书详情页 DOM 日期元素，避免 Task 4/5 基于错误假设写代码。

**Files:**
- Create: `scripts/diagnose_published_at.py`

**前置条件:** CDP Proxy 在线（`node ~/.claude/skills/web-access/scripts/cdp-proxy.mjs`）+ Chrome 调试端口 `:9222`。

- [ ] **Step 1: 创建侦察脚本**

```python
"""侦察三平台 published_at 真实字段/格式/选择器。

前置：CDP Proxy (localhost:3456) + Chrome (9222) 在线。
用法：python scripts/diagnose_published_at.py [关键词]

输出供人工确认：
- 抖音 aweme_info 是否含 create_time（字段名 + 类型）
- 微博 created_at 真实字符串格式
- 小红书详情页 DOM 里日期元素命中哪个选择器
"""
import asyncio
import json
import sys

from pipeline.collectors.cdp_collector import (
    CdpClient, DouyinExtractor, WeiboExtractor, XiaohongshuExtractor,
)


async def diagnose_douyin(keyword: str):
    client = CdpClient()
    tab = await client.new_tab(DouyinExtractor.search_url(keyword))
    print("=== 抖音：探测 aweme_info 时间字段 ===")
    try:
        await asyncio.sleep(6)
        # 临时探测 JS：打印第一个 aweme_info 里所有含 time/date 的字段名+值
        probe_js = DouyinExtractor.SEARCH_FETCH_JS.replace(
            "return JSON.stringify({ ok: true, count: vids.length, videos: vids.slice(0, 15) });",
            """const first = objs.find(o => (o.data||[]).some(it => it.aweme_info));
                const a = first ? first.data.find(it => it.aweme_info).aweme_info : {};
                const fields = {};
                for (const k of Object.keys(a)) { if (/time|date|creat/i.test(k)) fields[k] = a[k]; }
                return JSON.stringify({ ok: true, sample_fields: fields });"""
        )
        raw = await client.eval_js(tab, probe_js.replace("__KW__", json.dumps(keyword)))
        result = json.loads(raw) if isinstance(raw, str) else (raw or {})
        print("  aweme_info 时间相关字段:", json.dumps(result.get("sample_fields", {}), ensure_ascii=False))
        print("  → 确认 create_time 是否存在及是否为 Unix 秒")
    finally:
        await client.close_tab(tab)


async def diagnose_weibo(keyword: str):
    client = CdpClient()
    tab = await client.new_tab(WeiboExtractor.search_url(keyword))
    print("=== 微博：created_at 真实格式 ===")
    try:
        await asyncio.sleep(4)
        raw = await client.eval_js(tab, WeiboExtractor.SEARCH_JS)
        cards = json.loads(raw) if isinstance(raw, str) else (raw or [])
        if isinstance(cards, dict) and "error" in cards:
            print("  ERROR:", cards.get("error"))
        else:
            for c in (cards or [])[:3]:
                print("  created_at =", repr(c.get("created_at")))
    finally:
        await client.close_tab(tab)


async def diagnose_xhs(keyword: str):
    client = CdpClient()
    tab = await client.new_tab(XiaohongshuExtractor.search_url(keyword))
    print("=== 小红书：详情页日期元素探测 ===")
    try:
        await asyncio.sleep(8)
        raw = await client.eval_js(tab, XiaohongshuExtractor.SEARCH_JS)
        notes = json.loads(raw) if isinstance(raw, str) else (raw or [])
        if not notes:
            print("  搜索结果为空，无法探测详情页")
            return
        link = notes[0].get("link", "")
        if link.startswith("/"):
            link = f"https://www.xiaohongshu.com{link}"
        detail_tab = await client.new_tab(link)
        try:
            await asyncio.sleep(4)
            probe_js = r"""(() => {
                const sels = ['.date', '.publish-time', '.publish-date', '[class*=date]',
                              '.bottom-info .date', '.note-content .date', '.author-info .date', 'time'];
                const hit = {};
                for (const s of sels) {
                    const el = document.querySelector(s);
                    if (el && el.textContent.trim()) hit[s] = el.textContent.trim();
                }
                return JSON.stringify(hit);
            })()"""
            raw_d = await client.eval_js(detail_tab, probe_js)
            hit = json.loads(raw_d) if isinstance(raw_d, str) else (raw_d or {})
            print("  命中的日期选择器:", json.dumps(hit, ensure_ascii=False))
            print("  → 确认 DETAIL_JS 用哪个选择器")
        finally:
            await client.close_tab(detail_tab)
    finally:
        await client.close_tab(tab)


async def main():
    keyword = sys.argv[1] if len(sys.argv) > 1 else "MG 4X"
    if not await CdpClient().health():
        print("ERROR: CDP Proxy (localhost:3456) 不可达，请先启动 cdp-proxy.mjs")
        return
    await diagnose_douyin(keyword)
    await diagnose_weibo(keyword)
    await diagnose_xhs(keyword)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 运行侦察脚本并记录结论**

Run: `python scripts/diagnose_published_at.py MG 4X`

将输出填入以下结论（供 Task 4/5 使用）：
- 抖音 `create_time`：存在 / 不存在？值类型（Unix 秒）？若字段名不同，Task 4 改用真实字段名。
- 微博 `created_at`：真实格式 = `______`（确认是否为 "Sun Jun 29 10:00:00 +0800 2025"，以及 strptime 是否成功）
- 小红书日期选择器：命中 `______`，Task 5 用该选择器。

- [ ] **Step 3: Commit**

```bash
git add scripts/diagnose_published_at.py
git commit -m "chore(scripts): published_at 三平台侦察脚本"
```

---

## Task 4: 抖音提取 `create_time`（基于 Task 3 结论）

**前置:** Task 3 侦察已确认 `create_time` 字段存在且为 Unix 秒。若侦察结论字段名不同，以下代码用真实字段名替换。

**Files:**
- Modify: `pipeline/collectors/cdp_collector.py`（`DouyinExtractor.SEARCH_FETCH_JS` 约 428-432 行；`_search_douyin` 约 809-816 + 839-844 行）
- Test: `tests/test_cdp_collector.py`（`TestCdpCollectorDouyin` 类）

- [ ] **Step 1: 写失败测试（并修正现有 mock 数据格式）**

将 `TestCdpCollectorDouyin` 类中 `test_search_douyin_parses_videos`（243-254 行）替换为：

```python
    @pytest.mark.asyncio
    async def test_search_douyin_parses_videos_and_time(self):
        client = CdpClient()
        search_data = json.dumps({
            "ok": True, "count": 1,
            "videos": [{"video_id": "12345", "title": "启源Q05试驾", "create_time": 1748217600}]
        })
        detail_data = json.dumps({
            "likes": 687, "comments_count": 0, "shares": 139,
            "author": "大卫的车价", "text_snippet": "启源Q05试驾详解",
        })
        with patch.object(client, "new_tab", AsyncMock(side_effect=["tab-dy", "tab-detail"])):
            with patch.object(client, "eval_js", AsyncMock(side_effect=[search_data, detail_data])):
                with patch.object(client, "close_tab", AsyncMock()):
                    c = CdpCollector(client=client)
                    posts, _ = await c.search("启源Q05", "douyin")
        assert len(posts) == 1
        assert posts[0]["likes"] == 687
        assert posts[0]["platform"] == "dy"
        assert posts[0]["published_at"] == "2025-05-26T00:00:00"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_cdp_collector.py::TestCdpCollectorDouyin::test_search_douyin_parses_videos_and_time -v`
Expected: FAIL（`assert posts[0]["published_at"] == "2025-05-26T00:00:00"` —— 当前为 `""`，因 SEARCH_FETCH_JS 未返回 create_time、_search_douyin 未传 published_at）

- [ ] **Step 3: 改 `SEARCH_FETCH_JS` 的 `vids.push`（约 428-432 行）**

```javascript
                    vids.push({
                        video_id: String(a.aweme_id),
                        title: (a.desc || a.title || '').slice(0, 80),
                        create_time: a.create_time || 0,
                    });
```

- [ ] **Step 4: 改 `_search_douyin` 正常分支 `_make_post`（约 809-816 行）**

```python
                        posts.append(_make_post(
                            title=(detail.get("title") or detail.get("text_snippet") or v.get("title", ""))[:80],
                            content=detail.get("text_snippet", "") or detail.get("title", "") or v.get("title", ""),
                            author=detail.get("author", ""),
                            url=detail_url, likes=detail.get("likes", 0),
                            comments_count=detail.get("comments_count", 0),
                            shares=detail.get("shares", 0), platform="dy",
                            published_at=v.get("create_time", ""),
                        ))
```

- [ ] **Step 5: 改 `_search_douyin` 兜底分支 `_make_post`（约 839-844 行）**

```python
                    posts.append(_make_post(
                        title=v.get("title", "")[:80],
                        content=v.get("title", ""),
                        author="", url=detail_url,
                        likes=0, comments_count=0, shares=0, platform="dy",
                        published_at=v.get("create_time", ""),
                    ))
```

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/test_cdp_collector.py::TestCdpCollectorDouyin -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pipeline/collectors/cdp_collector.py tests/test_cdp_collector.py
git commit -m "feat(douyin): SEARCH_FETCH_JS 提取 create_time，_make_post 传 published_at"
```

---

## Task 5: 小红书 DETAIL_JS 提取日期（基于 Task 3 结论）

**前置:** Task 3 侦察已确认命中的日期选择器。以下代码用多个候选选择器兜底；若侦察发现唯一可靠选择器，可精简。

**Files:**
- Modify: `pipeline/collectors/cdp_collector.py`（`XiaohongshuExtractor.DETAIL_JS` 约 587-602 行；`_search_xhs` 约 875-882 行）
- Test: `tests/test_cdp_collector.py`（`TestCdpCollectorXhs` 类）

- [ ] **Step 1: 写失败测试**

将 `TestCdpCollectorXhs` 类中 `test_search_xhs_notes_and_comments`（268-283 行）的 `detail_data` 增加 `date` 字段，并在断言前加 published_at 断言：

```python
        detail_data = json.dumps({"title": "启源Q05续航", "author": "车主", "content": "开了两月", "likes": 238, "collects": 50, "comments_count": 15, "date": "2025-06-01"})
```

在 `assert posts[0]["platform"] == "xhs"` 之后加入：

```python
        assert posts[0]["published_at"] == "2025-06-01T00:00:00"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_cdp_collector.py::TestCdpCollectorXhs::test_search_xhs_notes_and_comments -v`
Expected: FAIL（`assert posts[0]["published_at"] == "2025-06-01T00:00:00"` —— 当前为 `""`，DETAIL_JS 未返回 date、_search_xhs 未传 published_at）

- [ ] **Step 3: 改 `DETAIL_JS`（587-602 行）增加日期提取 + date 返回字段**

```javascript
    DETAIL_JS = """
    (() => {
        const title = document.querySelector('.title, h1')?.textContent?.trim() || '';
        const author = document.querySelector('.username, .author .name')?.textContent?.trim() || '';
        const content = document.querySelector('.desc, .note-text, .content')?.textContent?.trim() || '';
        const likeEl = document.querySelector('.like-wrapper .count, [class*=like] .count');
        const collectEl = document.querySelector('.collect-wrapper .count, [class*=collect] .count');
        const commentEl = document.querySelector('.chat-wrapper .count, [class*=chat] .count');
        // 发布日期：多选择器兜底（具体命中由 diagnose 脚本确认）
        const dateEl = document.querySelector('.date, .publish-time, [class*=date], .bottom-info .date, .author-info .date');
        const date = dateEl?.textContent?.trim() || '';
        return JSON.stringify({
            title, author, content,
            likes: parseInt(likeEl?.textContent || '0'),
            collects: parseInt(collectEl?.textContent || '0'),
            comments_count: parseInt(commentEl?.textContent || '0'),
            date,
        });
    })()
    """
```

- [ ] **Step 4: 改 `_search_xhs` 的 `_make_post`（约 875-882 行）增加 published_at**

```python
                        post = _make_post(
                            title=detail.get("title", n.get("title", "")),
                            content=detail.get("content", "") or n.get("title", ""),
                            author=detail.get("author", n.get("author", "")),
                            url=note_url, likes=detail.get("likes", n.get("likes", 0)),
                            comments_count=detail.get("comments_count", 0),
                            shares=0, platform="xhs",
                            published_at=detail.get("date", ""),
                        )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_cdp_collector.py::TestCdpCollectorXhs -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pipeline/collectors/cdp_collector.py tests/test_cdp_collector.py
git commit -m "feat(xhs): DETAIL_JS 提取发布日期，_make_post 传 published_at"
```

---

## Task 6: event_tracker 去掉 `now()` 兜底 NULL

**Files:**
- Modify: `pipeline/analysis/event_tracker.py:484`
- Test: `tests/test_event_tracker.py`

- [ ] **Step 1: 写失败测试（下游 None 容错回归）**

在 `tests/test_event_tracker.py` 的 `# ── Time split tests` 区块（142 行起），`test_split_by_time_empty`（169-172 行）之后加入：

```python
def test_split_by_time_handles_none_published_at():
    """Posts with None published_at must NOT be treated as 'today'.

    Regression for event_tracker using datetime.now() to fill NULL posts.
    After the fix, None flows to _get_post_date → date.min (earliest),
    keeping the today-pollution out of the event timeline.
    """
    from pipeline.analysis.event_tracker import split_community_by_time
    posts = [
        {"id": "p1", "published_at": datetime(2026, 5, 10)},
        {"id": "p2", "published_at": None},  # NULL 帖
        {"id": "p3", "published_at": datetime(2026, 5, 12)},
    ]
    groups = split_community_by_time(posts, max_gap_days=7)
    # 不 crash
    total = sum(len(g) for g in groups)
    assert total == 3
    # None 帖按 date.min 排到最前，应在第一组（不被当成今天）
    assert any(p["id"] == "p2" for p in groups[0])
```

- [ ] **Step 2: 跑测试确认通过（下游本就容错，此测试验证修复意图不破）**

Run: `python -m pytest tests/test_event_tracker.py::test_split_by_time_handles_none_published_at -v`
Expected: PASS（`split_community_by_time` 用 `_get_post_date(p) or date.min`，本就处理 None；此测试锁定该行为，防止未来回归）

> 说明：484 行的内联改动在 async `detect_events_for_vehicle` 内，依赖 session/LLM/DB，完整 async 测试过重。修复意图——"None 不被 now() 兜底，流到本就能容错的下游"——由本测试锁定下游行为，484 行改动本身靠 Step 3 代码审查 + Task 7 实采验证。

- [ ] **Step 3: 改 `event_tracker.py:484` 去掉 now() 兜底**

```python
# 旧
"published_at": (raw["published_at"] if raw else None) or datetime.now(),
# 新
"published_at": raw["published_at"] if raw else None,
```

- [ ] **Step 4: 复核 484 行之后无 published_at 非 None 假设**

Run: `grep -n "published_at" pipeline/analysis/event_tracker.py`

人工确认：484 行之后（490 行起的 topic 标注、关键词提取、Louvain、命名）均不直接读 `post["published_at"]`（时间消费只在 `split_community_by_time` → `_get_post_date`，已容错 None）。

- [ ] **Step 5: 跑事件全量测试确认无回归**

Run: `python -m pytest tests/test_event_tracker.py -v`
Expected: PASS（全绿）

- [ ] **Step 6: Commit**

```bash
git add pipeline/analysis/event_tracker.py tests/test_event_tracker.py
git commit -m "fix(event_tracker): 去掉 NULL published_at 的 datetime.now() 兜底，避免污染事件时间"
```

---

## Task 7: 实采验证（需 CDP 环境）

> 验证 spec §12 全维度：DB 新帖 published_at 非 NULL。

**前置:** Task 1-6 全完成并合并；CDP Proxy + Chrome 在线。

**Files:**
- Create: `scripts/verify_published_at.py`

- [ ] **Step 1: 创建验证脚本**

```python
"""实采验证：抖音/微博/小红书新帖 published_at 非 NULL。

前置：CDP Proxy (localhost:3456) + Chrome (9222) 在线。
用法：python scripts/verify_published_at.py [关键词]
"""
import asyncio
import sys

from pipeline.collectors.cdp_collector import CdpCollector


async def main():
    keyword = sys.argv[1] if len(sys.argv) > 1 else "MG 4X"
    collector = CdpCollector()
    if not await collector.is_available():
        print("ERROR: CDP Proxy 不可达")
        return

    for platform, label in [("douyin", "抖音"), ("weibo", "微博"), ("xiaohongshu", "小红书")]:
        print(f"\n=== {label} ({platform}) ===")
        try:
            posts, _ = await collector.search(keyword, platform)
        except Exception as e:
            print(f"  采集异常: {e}")
            continue
        total = len(posts)
        with_time = sum(1 for p in posts if p.get("published_at"))
        print(f"  帖数: {total}, 有 published_at: {with_time}, 覆盖率: {with_time}/{total}")
        for p in posts[:3]:
            print(f"    - {p.get('title','')[:30]} | published_at={p.get('published_at')!r}")
        # 断言：新帖应有时间（允许少量解析失败的边角）
        if total > 0:
            assert with_time > 0, f"{label} 采集到 {total} 帖但 published_at 全空！根治未生效"
            print(f"  ✅ 通过")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 运行实采验证**

Run: `python scripts/verify_published_at.py MG 4X`
Expected: 三平台均打印 `✅ 通过`（抖音/微博/小红书有帖时 published_at 覆盖率 > 0）

> 若某平台覆盖率低（如小红书选择器未命中），回到 Task 5 用 Task 3 侦察命中的选择器修正 DETAIL_JS。

- [ ] **Step 3: 验证 heat_calculator 受益（spec §12 热度维度）**

人工/SQL 检查：实采入库后，微博/抖音/小红书帖所在日期的 `discussion_volume` / `interaction_intensity` 不再因 NULL 被全部过滤（对比根治前）。

Run（示例 SQL，按实际车型/日期替换）：
```bash
python -c "import sqlite3; c=sqlite3.connect('data/sentiment.db'); print(c.execute(\"SELECT platform, COUNT(*), COUNT(published_at) FROM raw_posts WHERE source='cdp' GROUP BY platform\").fetchall())"
```
Expected: 各 CDP 平台的 `COUNT(published_at)` 占比显著提升（新数据接近 100%，历史 NULL 帖除外）。

- [ ] **Step 4: Commit**

```bash
git add scripts/verify_published_at.py
git commit -m "chore(scripts): published_at 实采验证脚本"
```

---

## 完成标准（spec §12）

- [ ] Task 1-6 单测全绿（`pytest tests/test_cdp_collector.py tests/test_event_tracker.py -v`）
- [ ] Task 7 实采：三平台新帖 published_at 覆盖率 > 0
- [ ] heat_calculator 统计：CDP 平台 `COUNT(published_at)` 显著提升
- [ ] event_tracker 不再用 now() 兜底（484 行已改 + 回归测试锁定）

## 全量回归（收尾）

- [ ] **跑全量测试套件**

Run: `python -m pytest -v`
Expected: GREEN（已知 pytest-asyncio 环境问题最多 1 error，非本次改动引入）

- [ ] **最终 Commit（如有遗留）**

确认所有改动已提交：`git status` 干净。
