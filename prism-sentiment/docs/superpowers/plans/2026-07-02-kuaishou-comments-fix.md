# 快手评论采集修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复快手评论采集——从"只抓 card 0、30 评论、全挂 posts[0]"改为 per-post in-page REST API fetch，使评论正确归属到多个 post（`post_note_id` 分布 ≥5），comments/post ratio 从 0.1 → ≥0.5。

**Architecture:** 镜像 douyin 已验证模式：在搜索页 tab 内用 `eval_js` 执行 in-page `fetch('/rest/v/photo/comment/list')`（浏览器自动带 cookie），`pcursor` 分页到 `no_more`。新增纯 Python helper `_normalize_ks_comment` 做 V2 字段映射（单测可覆盖），JS 只负责 fetch+分页+返回原始 item。搜索仍用 DOM `CARDS_JS`（surgical，不动工作流）。

**Tech Stack:** Python 3 / asyncio / pytest-asyncio / CDP（`eval_js` in-page JS）/ kuaishou REST V2 API。CDP client 无网络拦截，但 `eval_js` 在页面上下文带 cookie。

**Spec:** `docs/superpowers/specs/2026-07-02-kuaishou-comments-fix-design.md`

**运行环境（全量 pytest，避开 GBK 坑）：**
`PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -m pytest -q`

---

## File Structure

| 文件 | 改动 | 责任 |
|---|---|---|
| `pipeline/collectors/cdp_collector.py` | 改 | 新增 `_normalize_ks_comment` helper、`_KS_COMMENT_POST_LIMIT` 常量、`KuaishouExtractor.COMMENTS_FETCH_JS` + `comments_fetch_js()`、重写 `_search_kuaishou` 评论分支 |
| `tests/test_cdp_collector.py` | 改 | 新增 `_normalize_ks_comment` 单测、`comments_fetch_js` 源码检查、多帖归属守卫；更新现有 kuaishou 解析用例到新 mock 序列 |
| `docs/superpowers/recon/2026-07-02-kuaishou-recon.md` | 建 | 实采后记录 API 响应真实字段名 + photo_id 有效性结论 |

**接口约定（实现时严格遵守）：**
- `_make_comment(content, author, likes, platform, post_url, post_note_id="", published_at="")` — 已存在（cdp_collector.py:220），不要改签名
- `_safe_int(x)` — 已存在，已测试可导入
- `KuaishouExtractor.comments_fetch_js(photo_id: str) -> str` — 新增，镜像 `DouyinExtractor.search_fetch_js(keyword)`（cdp_collector.py:472-476）的模板替换模式

---

## Task 1: `_normalize_ks_comment` Python helper（TDD）

**Files:**
- Modify: `pipeline/collectors/cdp_collector.py`（在 `_make_comment` 之后，约 line 239 处插入）
- Test: `tests/test_cdp_collector.py`

纯函数：把 kuaishou V2 `rootCommentsV2` 单条原始 item 映射为标准 comment dict。对字段名防御（snake/camel 都收），因为 V2 确切命名待 recon 确认。

- [ ] **Step 1: 写失败测试**

在 `tests/test_cdp_collector.py` 顶部导入区追加 `_normalize_ks_comment`（与已有的 `_safe_int` 同行 import），并在文件末尾追加：

```python
class TestNormalizeKsComment:
    def test_maps_snake_case_fields(self):
        item = {"content": "好车", "author_name": "网友A", "liked_count": 5, "timestamp": 1700000000}
        c = _normalize_ks_comment(item, photo_id="pidA", post_url="http://u")
        assert c["content"] == "好车"
        assert c["author"] == "网友A"
        assert c["likes"] == 5
        assert c["post_note_id"] == "pidA"
        assert c["platform"] == "kuaishou"
        assert c["post_url"] == "http://u"

    def test_falls_back_to_camel_case_keys(self):
        item = {"content": "好", "authorName": "A", "likedCount": 3, "createTime": 1700000001}
        c = _normalize_ks_comment(item, "pidB", "http://u")
        assert c["author"] == "A"
        assert c["likes"] == 3

    def test_missing_fields_default_safe(self):
        c = _normalize_ks_comment({}, "pidC", "http://u")
        assert c["content"] == ""
        assert c["author"] == ""
        assert c["likes"] == 0
        assert c["post_note_id"] == "pidC"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_cdp_collector.py::TestNormalizeKsComment -v`
Expected: FAIL — `ImportError: cannot import name '_normalize_ks_comment'`

- [ ] **Step 3: 写最小实现**

在 `pipeline/collectors/cdp_collector.py` 的 `_make_comment` 函数（line 220-238）之后插入：

```python
def _normalize_ks_comment(item: dict, photo_id: str, post_url: str) -> dict:
    """Map a kuaishou REST V2 ``rootCommentsV2`` item to a standard comment dict.

    Defensive about field-name variants: kuaishou V2 may use snake_case or
    camelCase (exact names confirmed by live recon — see
    docs/superpowers/recon/2026-07-02-kuaishou-recon.md). Vendor contract
    reference: vendor/MediaCrawler/media_platform/kuaishou/client.py.
    """
    content = item.get("content") or item.get("comment_content") or ""
    author = (
        item.get("author_name")
        or item.get("authorName")
        or item.get("user_name")
        or ""
    )
    likes = item.get("liked_count") or item.get("likedCount") or item.get("like_count") or 0
    timestamp = item.get("timestamp") or item.get("createTime") or ""
    return _make_comment(
        content=str(content),
        author=str(author),
        likes=likes,
        platform=platforms.KUAISHOU,
        post_url=post_url,
        post_note_id=str(photo_id),
        published_at=str(timestamp),
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_cdp_collector.py::TestNormalizeKsComment -v`
Expected: PASS（3 用例全绿）

- [ ] **Step 5: 提交**

```bash
git add pipeline/collectors/cdp_collector.py tests/test_cdp_collector.py
git commit -m "feat(cdp): _normalize_ks_comment helper for kuaishou V2 comment mapping"
```

---

## Task 2: `KuaishouExtractor.comments_fetch_js` JS 模板（TDD 源码检查）

**Files:**
- Modify: `pipeline/collectors/cdp_collector.py`（`KuaishouExtractor` 类，line 336-398 区间）
- Test: `tests/test_cdp_collector.py`

新增 `COMMENTS_FETCH_JS` 类属性（in-page fetch + pcursor 分页 + AbortController 超时）和 `comments_fetch_js(photo_id)` 静态方法（模板替换，镜像 `DouyinExtractor.search_fetch_js`）。JS 返回 `{ok, comments:[原始 item], count}`，**字段映射留给 Python `_normalize_ks_comment`**。

- [ ] **Step 1: 写失败测试**

在 `tests/test_cdp_collector.py` 末尾追加：

```python
class TestKuaishouCommentsFetchJs:
    def test_js_contains_api_contract(self):
        js = KuaishouExtractor.comments_fetch_js("pidA")
        # REST V2 endpoint + 分页契约
        assert "/rest/v/photo/comment/list" in js
        assert "photoId" in js
        assert "pcursor" in js
        assert "rootCommentsV2" in js
        assert "no_more" in js
        # 风控节流 + 超时保护（对标 douyin SEARCH_FETCH_JS）
        assert "setTimeout" in js
        assert "AbortController" in js
        # 上限保护
        assert "30" in js

    def test_js_substitutes_photo_id_safely(self):
        js = KuaishouExtractor.comments_fetch_js("3xf9abc")
        assert '"3xf9abc"' in js
        assert "__PHOTO_ID__" not in js
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_cdp_collector.py::TestKuaishouCommentsFetchJs -v`
Expected: FAIL — `AttributeError: ... has no attribute 'comments_fetch_js'`

- [ ] **Step 3: 写最小实现**

在 `KuaishouExtractor` 类中（`COMMENTS_JS` 属性之后，`class DouyinExtractor` 之前，即 line 398 之后）插入两个成员：

```python
    COMMENTS_FETCH_JS = r"""
(async () => {
    const PHOTO_ID = __PHOTO_ID__;
    const MAX = 30;
    const out = [];
    let pcursor = "";
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), 15000);
    try {
        let guard = 0;
        while (pcursor !== "no_more" && out.length < MAX && guard < 10) {
            guard++;
            const resp = await fetch('/rest/v/photo/comment/list', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ photoId: PHOTO_ID, pcursor: pcursor }),
                credentials: 'include',
                signal: ctrl.signal,
            });
            const data = await resp.json();
            if (data.result !== 1) break;
            const items = data.rootCommentsV2 || data.rootComments || [];
            if (!items.length) break;
            out.push(...items);
            pcursor = data.pcursorV2 || data.pcursor || "no_more";
            if (pcursor === "no_more") break;
            await new Promise(r => setTimeout(r, 1200));
        }
        clearTimeout(tid);
        return JSON.stringify({ ok: true, comments: out.slice(0, MAX), count: out.length });
    } catch (e) {
        clearTimeout(tid);
        return JSON.stringify({ ok: false, error: String(e).slice(0, 200), comments: out, count: out.length });
    }
})()
"""

    @staticmethod
    def comments_fetch_js(photo_id: str) -> str:
        """Return the in-page comment-fetch JS for *photo_id*.

        Mirrors DouyinExtractor.search_fetch_js: __PHOTO_ID__ is substituted
        via json.dumps so the value is always a valid JS string literal.
        """
        return KuaishouExtractor.COMMENTS_FETCH_JS.replace(
            "__PHOTO_ID__", json.dumps(str(photo_id))
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_cdp_collector.py::TestKuaishouCommentsFetchJs -v`
Expected: PASS（2 用例绿）

- [ ] **Step 5: 提交**

```bash
git add pipeline/collectors/cdp_collector.py tests/test_cdp_collector.py
git commit -m "feat(cdp): KuaishouExtractor.comments_fetch_js — in-page REST V2 fetch template"
```

---

## Task 3: 重写 `_search_kuaishou` 评论分支 + 更新现有用例

**Files:**
- Modify: `pipeline/collectors/cdp_collector.py:739-805`（`_search_kuaishou`）+ 模块顶部新增常量 `_KS_COMMENT_POST_LIMIT`
- Test: `tests/test_cdp_collector.py`（`TestCdpCollectorKuaishou.test_search_kuaishou_parses_cards_and_comments`）

把"只对 card 0 打开浮层抓评论"改为"对 top-N 帖逐个 in-page fetch 评论 API"。eval_js 调用序从 `[cards, click, click, COMMENTS_JS]` 变为 `[cards, comments_fetch_js(post1), comments_fetch_js(post2), ...]`。

- [ ] **Step 1: 更新现有用例为新 mock 序列**

把 `tests/test_cdp_collector.py` 中 `test_search_kuaishou_parses_cards_and_comments`（约 line 241-261）整体替换为：

```python
    @pytest.mark.asyncio
    async def test_search_kuaishou_parses_cards_and_comments(self):
        client = CdpClient()
        card_data = json.dumps([
            {"title": "启源Q05试驾", "author": "老郑说车", "likes_text": "⭐ 340",
             "photo_id": "3xf9abc"},
        ])
        fetch_result = json.dumps({
            "ok": True,
            "count": 1,
            "comments": [{
                "content": "好车推荐", "author_name": "网友A",
                "liked_count": 5, "timestamp": 1700000000,
            }],
        })

        with patch.object(client, "new_tab", AsyncMock(return_value="tab-ks")):
            with patch.object(client, "eval_js", AsyncMock(side_effect=[card_data, fetch_result])):
                with patch.object(client, "close_tab", AsyncMock()):
                    c = CdpCollector(client=client)
                    posts, comments = await c.search("启源Q05", "kuaishou")

        assert len(posts) == 1
        assert posts[0]["title"] == "启源Q05试驾"
        assert posts[0]["likes"] == 340
        assert posts[0]["platform"] == "kuaishou"
        assert posts[0]["comments"] == 1  # backfilled from API count
        assert len(comments) == 1
        assert comments[0]["content"] == "好车推荐"
        assert comments[0]["post_note_id"] == "3xf9abc"  # 归属正确，非 "0"
        assert comments[0]["likes"] == 5
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_cdp_collector.py::TestCdpCollectorKuaishou::test_search_kuaishou_parses_cards_and_comments -v`
Expected: FAIL — 旧实现的 eval_js 序列是 4 次（click/click/COMMENTS_JS），新测试只给 2 次 side_effect → `StopIteration` 或 post_note_id 断言失败。

- [ ] **Step 3: 写实现**

3a. 在 `pipeline/collectors/cdp_collector.py` 模块顶部（其他模块常量附近，`_safe_int` 定义之前）加常量：

```python
# 快手评论采集：单次搜索最多对多少个帖抓评论（保守档，对齐 vendor 非商业许可）
_KS_COMMENT_POST_LIMIT = 10
```

3b. 把 `_search_kuaishou`（line 739-805）整体替换为：

```python
    async def _search_kuaishou(self, keyword: str) -> tuple[list[dict], list[dict]]:
        """Kuaishou: DOM card 搜索 + per-post in-page REST fetch 评论。

        评论走 REST V2 (/rest/v/photo/comment/list)，浏览器在页面上下文带
        cookie，镜像 douyin 的 in-page fetch 模式。替换旧的"只抓 card 0 浮层"
        （306 帖 / 30 评论 / 全挂 posts[0]）。
        设计：docs/superpowers/specs/2026-07-02-kuaishou-comments-fix-design.md
        """
        ext = KuaishouExtractor()
        tab = await self._client.new_tab(ext.search_url(keyword))
        posts: list[dict] = []
        comments: list[dict] = []
        posts_and_ids: list[tuple[dict, str]] = []

        try:
            await asyncio.sleep(8)
            raw = await self._client.eval_js(tab, ext.CARDS_JS)
            cards = _parse_json_result(raw)

            for i, card in enumerate(cards[:10]):
                likes = _safe_int(card.get("likes_text", "").replace("⭐ ", ""))
                photo_id = str(card.get("photo_id") or f"card-{i}")
                post = _make_post(
                    title=card.get("title", ""),
                    content=card.get("title", ""),
                    author=card.get("author", ""),
                    url=(f"https://www.kuaishou.com/search/video?searchKey="
                         f"{urllib.parse.quote(keyword)}&card={i}"),
                    likes=likes,
                    comments_count=0,
                    shares=0,
                    platform=platforms.KUAISHOU,
                )
                posts_and_ids.append((post, photo_id))
                posts.append(post)

            # 按 likes 排序取 top-N，逐帖 in-page fetch 评论
            ranked = sorted(
                posts_and_ids,
                key=lambda x: x[0].get("likes", 0),
                reverse=True,
            )[:_KS_COMMENT_POST_LIMIT]
            for post, photo_id in ranked:
                # photo_id 为 'card-N' 兜底时说明 CARDS_JS 没抽出真实 id，
                # API 调用无意义——跳过（recon 风险点，见 spec 回退方案）
                if not photo_id or photo_id.startswith("card-"):
                    continue
                try:
                    raw_c = await self._client.eval_js(tab, ext.comments_fetch_js(photo_id))
                    result = _parse_json_result(raw_c, default={}) or {}
                    for item in (result.get("comments") or []):
                        comments.append(_normalize_ks_comment(item, photo_id, post["url"]))
                    if result.get("count"):
                        post["comments"] = _safe_int(result["count"])
                except Exception as e:
                    logger.debug("kuaishou comments failed for %s: %s", photo_id, e)

        finally:
            await self._client.close_tab(tab)

        return posts, comments
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_cdp_collector.py::TestCdpCollectorKuaishou -v`
Expected: PASS（`test_search_kuaishou_parses_cards_and_comments` + `test_search_kuaishou_no_cards` 均绿）

- [ ] **Step 5: 跑全量回归确认无破坏**

Run: `PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_cdp_collector.py -q`
Expected: 全绿（其他平台用例不受影响）

- [ ] **Step 6: 提交**

```bash
git add pipeline/collectors/cdp_collector.py tests/test_cdp_collector.py
git commit -m "fix(cdp): rewrite _search_kuaishou comment branch — per-post REST fetch"
```

---

## Task 4: 多帖归属回归守卫

**Files:**
- Test: `tests/test_cdp_collector.py`（`TestCdpCollectorKuaishou` 类内新增用例）

防止"评论全挂 card 0 / 单一 post_note_id"的回归。多 card 场景下断言 `post_note_id` 分布在多个值。

- [ ] **Step 1: 写失败测试**

在 `TestCdpCollectorKuaishou` 类（`test_search_kuaishou_no_cards` 之后）追加：

```python
    @pytest.mark.asyncio
    async def test_search_kuaishou_comments_spread_across_posts(self):
        """Regression guard: 评论必须分散到多个 photo_id，不能全挂单一 post。

        防的是旧 bug：所有评论 post_note_id='0'。
        """
        client = CdpClient()
        card_data = json.dumps([
            {"title": "视频A", "author": "u1", "likes_text": "100", "photo_id": "pidA"},
            {"title": "视频B", "author": "u2", "likes_text": "50", "photo_id": "pidB"},
        ])
        fetch_a = json.dumps({"ok": True, "count": 1, "comments": [
            {"content": "评A", "author_name": "a", "liked_count": 1, "timestamp": 0}]})
        fetch_b = json.dumps({"ok": True, "count": 1, "comments": [
            {"content": "评B", "author_name": "b", "liked_count": 1, "timestamp": 0}]})

        with patch.object(client, "new_tab", AsyncMock(return_value="tab-ks")):
            with patch.object(client, "eval_js",
                              AsyncMock(side_effect=[card_data, fetch_a, fetch_b])):
                with patch.object(client, "close_tab", AsyncMock()):
                    c = CdpCollector(client=client)
                    _posts, comments = await c.search("启源Q05", "kuaishou")

        assert len(comments) == 2
        note_ids = {c["post_note_id"] for c in comments}
        assert note_ids == {"pidA", "pidB"}, f"评论应分散到两个帖，实际 {note_ids}"
```

- [ ] **Step 2: 跑测试确认通过**（Task 3 实现已满足；此为守卫）

Run: `PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_cdp_collector.py::TestCdpCollectorKuaishou::test_search_kuaishou_comments_spread_across_posts -v`
Expected: PASS。若 FAIL，说明 Task 3 实现把评论归到了错误的 post——回 Task 3 检查 `ranked` 循环里 `_normalize_ks_comment(item, photo_id, ...)` 的 `photo_id` 是否用了循环变量而非固定值。

- [ ] **Step 3: 提交**

```bash
git add tests/test_cdp_collector.py
git commit -m "test(cdp): kuaishou 多帖评论归属守卫（防 card-0 回归）"
```

---

## Task 5: 实采集成验证 + recon 记录（需运行环境）

**Files:**
- Create: `docs/superpowers/recon/2026-07-02-kuaishou-recon.md`

此任务是**集成验证**——纯单测覆盖不到 live 站点。对标 douyin 修复时的"实跑 8帖/250评论"验证。同时完成 spec 的"侦察前置"：第一次实跑即确认 photo_id 有效性 + V2 真实字段名。

**前置条件：** 项目服务可启动、CDP 浏览器有快手登录态（cookie_manager 已维护）。

- [ ] **Step 1: 采集前快照**

Run:
```bash
cd "C:/Users/<you>/Desktop/Agent项目/Vehicle Sentiment Analysis Board"
PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -c "
import sqlite3
c = sqlite3.connect('data/vehicle_sentiment.db').cursor()
r = c.execute(\"SELECT COUNT(*), COUNT(DISTINCT post_note_id) FROM post_comments WHERE platform IN ('kuaishou','ks')\").fetchone()
print('BEFORE: comments=%d, distinct_post_note_id=%d' % (r[0], r[1]))
"
```
Expected: `BEFORE: comments=30, distinct_post_note_id=1`（或类似低值，确认修复前基线）

- [ ] **Step 2: 触发一次快手采集**

对任一车型触发采集（UI 点「采集」按钮，或调用 collection API，或 `scripts/verify_cdp_collector.py` 走快手分支）。等快手平台完成。

- [ ] **Step 3: 采集后核验**

Run:
```bash
PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -c "
import sqlite3
c = sqlite3.connect('data/vehicle_sentiment.db').cursor()
r = c.execute(\"SELECT COUNT(*), COUNT(DISTINCT post_note_id) FROM post_comments WHERE platform IN ('kuaishou','ks')\").fetchone()
print('AFTER: comments=%d, distinct_post_note_id=%d' % (r[0], r[1]))
ratio = c.execute(\"SELECT 1.0*COUNT(c.id)/NULLIF(COUNT(DISTINCT p.id),0) FROM raw_posts p LEFT JOIN post_comments c ON c.post_id=p.id WHERE p.platform IN ('kuaishou','ks')\").fetchone()[0]
print('ratio=%.2f' % (ratio or 0))
# 抽样一条看字段
row = c.execute(\"SELECT content, author, likes, post_note_id FROM post_comments WHERE platform IN ('kuaishou','ks') ORDER BY id DESC LIMIT 1\").fetchone()
print('sample:', row)
"
```

- [ ] **Step 4: 判定 + 记录**

判定标准（spec 验证定义）：
- `AFTER comments ≥ 150` 且 `distinct_post_note_id ≥ 5` → **PASS**，转 Step 5
- `AFTER comments == 0 或 ~30`（与 BEFORE 持平）→ **photo_id 不被 API 认**，触发回退（见 Step 6）

无论结果，建 `docs/superpowers/recon/2026-07-02-kuaishou-recon.md` 记录：
```markdown
# 快手评论修复 Recon（2026-07-02）

## 实采结果
- BEFORE: comments=X, distinct_post_note_id=Y
- AFTER: comments=X', distinct_post_note_id=Y', ratio=Z
- 判定: PASS / FAIL(原因)

## V2 真实字段名（从 sample 行 + 实际响应确认）
- content: <确认是 content / comment_content / 其他>
- author: <author_name / authorName / 其他>
- likes: <liked_count / likedCount / 其他>
- timestamp: <格式：unix秒 / 毫秒 / 字符串>

## photo_id 有效性
- DOM CARDS_JS 抽出的 photo_id（regex upic/...）<能/不能>被 REST API 认
- 结论: <保留 DOM 搜索 / 需回退 GraphQL 搜索>
```

- [ ] **Step 5: PASS 收尾——全量 pytest + 其他平台 smoke 回归**

Run: `PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -m pytest -q`
Expected: 全绿（含 2 个已知 pre-existing trafilatura cert fail，与本次无关）。提交 recon 记录：

```bash
git add docs/superpowers/recon/2026-07-02-kuaishou-recon.md
git commit -m "docs(recon): 快手评论修复实采验证记录"
```
→ 任务完成，进 simplify（步骤 5）。

- [ ] **Step 6: FAIL 回退分支（仅 photo_id 不被认时执行）**

DOM 抽的 photo_id 与 REST API 期望的不符。**不要硬调 regex 猜**——改为搜索也走 GraphQL 取 canonical photoId（vendor client.py:145-165 `visionSearchPhoto`）。

回退动作（此时新开 spec/plan，不在本 plan 内硬编）：
1. 读 `vendor/MediaCrawler/media_platform/kuaishou/graphql/search_query.graphql`（或 client.py 的 search 逻辑）拿 `visionSearchPhoto` 的 query 串
2. 仿 `DouyinExtractor.SEARCH_FETCH_JS`，给 `KuaishouExtractor` 加 `SEARCH_FETCH_JS`（in-page POST `/graphql`，body `{operationName:"visionSearchPhoto", variables:{keyword,pcursor,page:"search"}, query}`）
3. `_search_kuaishou` 用 GraphQL 搜索结果（含 canonical `photo.id`）替换 DOM cards，评论分支不变
4. 走一轮新 TDD：源码检查 + 更新测试 mock 序列
5. 回 Step 2 重采验证

判定回退必要性：Step 3 sample 行的 `post_note_id` 若全是 `card-N` 兜底值或 `AFTER comments` 无增长，即 photo_id 失效。

---

## Self-Review（plan 写完后自查，已完成）

**1. Spec coverage：** 逐条对 spec ——
- "评论分支只处理 card 0" → Task 3 重写为 per-post 循环 ✓
- "全挂 posts[0]/post_note_id='0'" → Task 4 守卫 + Task 3 `_normalize_ks_comment(item, photo_id, post["url"])` 用循环变量 ✓
- "comments_count 硬编码 0" → Task 3 `post["comments"] = _safe_int(result["count"])` 回填 ✓
- "except: pass 静默吞错" → Task 3 改 `logger.debug` ✓
- "in-page REST fetch 镜像 douyin" → Task 2 `COMMENTS_FETCH_JS` ✓
- "保守档 top-10×30×1.2s" → Task 3 `_KS_COMMENT_POST_LIMIT=10` + Task 2 JS 内 `MAX=30` + `setTimeout 1200` ✓
- "TDD 分层 + 守卫" → Task 1/2/4 单测 + Task 5 集成 ✓
- "侦察前置 + 回退" → Task 5 Step 4 recon 记录 + Step 6 回退分支 ✓
- "验证 ratio ≥0.5、post_note_id ≥5" → Task 5 Step 3/4 ✓

**2. Placeholder scan：** 无 TBD/TODO；所有 code step 含完整代码；Task 5 Step 6 是条件回退（明确触发条件 + 具体动作），非占位 ✓

**3. Type consistency：** `_normalize_ks_comment(item, photo_id, post_url)` 签名在 Task 1 定义、Task 3 调用一致 ✓；`comments_fetch_js(photo_id)` Task 2 定义、Task 3 调用一致 ✓；`_KS_COMMENT_POST_LIMIT` Task 3 定义并使用 ✓；测试 mock 序列（`[card_data, fetch_result]`）与实现 eval_js 调用序（CARDS_JS 后逐帖 comments_fetch_js）一致 ✓
