# 前端审计 Gap 修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把已生成但前端未展现的分析数据（评论摘要、争议帖、单帖维度/标签）接上出口，让帖子详情、列表、争议预警都有完整展示。

**Architecture:** 后端先给两个列表 API（top-posts / posts）补齐分析字段（一次 JOIN AnalyzedPost），前端再升级帖子详情 modal、补列表卡片字段、新增争议帖预警卡片与 event-distribution 图。Task A 是 B/D 的基础；C/E/F 独立。

**Tech Stack:** FastAPI + SQLAlchemy async（后端），Vue 3 CDN + ECharts（前端，`frontend/static/js/app.js` 单文件 + `frontend/index.html` + `frontend/static/css/style.css`）。

**Verification note:** 本项目无前端单测框架。后端用 `curl` 验证返回字段；前端用代码审查 + 主 agent 浏览器/CDP 验证渲染。服务跑在 `http://localhost:9050`。

**字段格式（已确认）：**
- `dim_sentiment`: JSON 字符串 dict，如 `{"价格/性价比": 1}`（0~1 分，键是维度名）
- `event_tags` / `opinion_tags`: JSON 字符串数组，如 `["新车发布/上市", "智能驾驶事故"]`
- `comment_summary`: JSON 字符串，`{is_argumentative, argument_detail, genuine_themes[], genuine_sentiment, genuine_sentiment_score, summary}`
- `comment-sentiment-diff` API 已就绪，返回 `[{title, post_sentiment, comment_sentiment, is_argumentative, genuine_themes, summary}]`

---

## File Structure

- `api/routes/dashboard.py` — 改 `get_top_posts` / `get_posts` 返回字段（Task A）
- `frontend/static/js/app.js` — modal 数据解析/渲染、争议卡片加载、列表/热帖字段、event-dist 图（B/C/D/E/F）
- `frontend/index.html` — modal 模板、争议卡片 DOM、列表/热帖卡片模板、event-dist 容器（B/C/D/E/F）
- `frontend/static/css/style.css` — 新元素样式（标签芯片、维度条、争议卡片）

**依赖关系：** A → B、A → D。C / E / F 互相独立，可与 A 并行。

---

## Task A: 后端 top-posts / posts API 补齐分析字段

**Files:**
- Modify: `api/routes/dashboard.py` — `get_top_posts` (~line 294-357) 和 `get_posts` (~line 360-420)

**背景：** 两个列表 API 当前都不返回 `comment_summary / dim_sentiment / event_tags / opinion_tags`；`get_posts` 连 `sentiment / subject_name` 都没有。前端 B/D 任务依赖这些字段。

- [ ] **Step A1: 改 `get_top_posts`，把 AnalyzedPost 的全部分析字段加入 sentiment_map 预加载与返回**

在 `get_top_posts` 里，把 `select(AnalyzedPost.post_id, AnalyzedPost.sentiment, AnalyzedPost.subject_name)`（~line 338）扩成全字段，并把返回 dict 补齐字段。最终 `select` 与 `return` 改为：

```python
    # Get full analysis for each post
    post_ids = [p.id for p in posts]
    analysis_map: dict[str, dict] = {}
    if post_ids:
        ap_result = await session.execute(
            select(AnalyzedPost).where(AnalyzedPost.post_id.in_(post_ids))
        )
        for ap in ap_result.scalars().all():
            analysis_map[ap.post_id] = ap

    def _ap_fields(ap):
        if not ap:
            return {}
        return {
            "sentiment": ap.sentiment or "",
            "subject_name": ap.subject_name or "",
            "dim_sentiment": ap.dim_sentiment or "",
            "event_tags": ap.event_tags or "",
            "opinion_tags": ap.opinion_tags or "",
            "comment_summary": ap.comment_summary or "",
        }

    return [
        {
            "id": p.id, "title": p.title, "content": p.content,
            "platform": p.platform, "source": p.source,
            "author": p.author, "url": p.url,
            "likes": p.likes or 0, "comments": p.comments or 0, "shares": p.shares or 0,
            "engagement": (p.likes or 0) + (p.comments or 0) + (p.shares or 0),
            "published_at": p.published_at.isoformat() if p.published_at else None,
            **_ap_fields(analysis_map.get(p.id)),
        }
        for p in posts
    ]
```

- [ ] **Step A2: 改 `get_posts`，同样预加载 AnalyzedPost 并补字段（含 sentiment）**

`get_posts` 当前只 `select(RawPost)`。改为额外批量查 AnalyzedPost，返回 dict 补字段。把 `return {...}` 块（~line 407-420）改为：

```python
    # Batch-load analysis fields for these posts
    post_ids = [p.id for p in posts]
    analysis_map: dict[str, AnalyzedPost] = {}
    if post_ids:
        ap_res = await session.execute(
            select(AnalyzedPost).where(AnalyzedPost.post_id.in_(post_ids))
        )
        for ap in ap_res.scalars().all():
            analysis_map[ap.post_id] = ap

    def _ap_fields(ap):
        if not ap:
            return {}
        return {
            "sentiment": ap.sentiment or "",
            "subject_name": ap.subject_name or "",
            "dim_sentiment": ap.dim_sentiment or "",
            "event_tags": ap.event_tags or "",
            "opinion_tags": ap.opinion_tags or "",
            "comment_summary": ap.comment_summary or "",
        }

    return {
        "items": [
            {
                "id": p.id, "title": p.title, "content": p.content,
                "platform": p.platform, "source": p.source,
                "author": p.author, "url": p.url,
                "likes": p.likes, "comments": p.comments, "shares": p.shares,
                "published_at": p.published_at.isoformat() if p.published_at else None,
                "analysis_status": p.analysis_status,
                **_ap_fields(analysis_map.get(p.id)),
            }
            for p in posts
        ],
        "total": total, "page": page, "size": size,
    }
```

- [ ] **Step A3: 重启服务 + curl 验证两个 API 返回新字段**

```bash
# 重启（替换 PID）
PID=$(netstat -ano | grep ":9050 " | grep LISTEN | awk '{print $NF}' | head -1)
taskkill //PID $PID //F; sleep 3
PORT=9050 conda run -n base --no-capture-output python start.py > logs/server.log 2>&1 &
sleep 12
VID="b489f88f-184c-4bbc-9d2f-37383fb02756"
# top-posts 含 comment_summary/dim_sentiment/event_tags/opinion_tags?
curl -s "http://localhost:9050/api/dashboard/top-posts/$VID?limit=3" | python -c "import sys,json;d=json.load(sys.stdin);print('top-posts keys:', sorted(d[0].keys()) if d else 'empty')"
# posts 含 sentiment?
curl -s "http://localhost:9050/api/dashboard/posts/$VID?size=2" | python -c "import sys,json;d=json.load(sys.stdin);print('posts item keys:', sorted(d['items'][0].keys()) if d['items'] else 'empty')"
```
Expected: 两个 key 集合都含 `sentiment, subject_name, dim_sentiment, event_tags, opinion_tags, comment_summary`。

- [ ] **Step A4: Commit**

```bash
git add api/routes/dashboard.py
git commit -m "feat(api): top-posts and posts return full analysis fields (dim/tags/summary)"
```

---

## Task B: 帖子详情 modal 升级（依赖 A）

**Files:**
- Modify: `frontend/index.html` — `.post-detail-modal` 模板（~line 312-335）
- Modify: `frontend/static/js/app.js` — 加解析方法 + `openPostDetail`（~line 824）
- Modify: `frontend/static/css/style.css` — 新元素样式

**背景：** modal 当前只有 title/author/content/互动量/sentiment。补：dim_sentiment 维度条、event_tags/opinion_tags 芯片、subject_name、comment_summary（争议/主题/真实情感/总结）、查看原文链接。

- [ ] **Step B1: app.js 加 4 个解析 helper（放 methods 内，`sentimentLabel` 附近）**

```javascript
        parseJson(value, fallback) {
            if (!value) return fallback;
            if (typeof value === 'object') return value;
            try { return JSON.parse(value); } catch (e) { return fallback; }
        },
        parsedDimSentiment(raw) {
            const d = this.parseJson(raw, {});
            return Array.isArray(d) ? d : Object.entries(d || {}).map(([k, v]) => ({dim: k, score: v}));
        },
        parsedCommentSummary(raw) {
            return this.parseJson(raw, null);
        },
```

- [ ] **Step B2: index.html 升级 `.post-detail-modal` 模板**

把 `<div class="post-detail-modal">` 内部（从 header 之后到闭合）整体替换为：

```html
            <div class="post-detail-header">
                <h3>{{ postDetail.title || (postDetail.content && postDetail.content.substring(0, 60)) }}</h3>
                <button @click="postDetailOpen = false" class="dialog-close">&times;</button>
            </div>
            <div class="post-detail-meta">
                <span class="post-card-platform" :class="postDetail.platform">{{ platformLabel(postDetail.platform) }}</span>
                <span v-if="postDetail.author">{{ postDetail.author }}</span>
                <span v-if="postDetail.published_at">{{ postDetail.published_at?.substring(0, 10) }}</span>
                <span v-if="postDetail.subject_name" class="post-detail-subject">{{ postDetail.subject_name }}</span>
                <a v-if="postDetail.url" :href="postDetail.url" target="_blank" rel="noopener" class="post-detail-origin">查看原文 ↗</a>
            </div>
            <div class="post-detail-body" v-if="postDetail.content">{{ postDetail.content }}</div>
            <div class="post-detail-stats">
                <span>▲ {{ postDetail.likes || 0 }}</span>
                <span>💬 {{ postDetail.comments || 0 }}</span>
                <span>→ {{ postDetail.shares || 0 }}</span>
                <span v-if="postDetail.engagement">热度 {{ postDetail.engagement }}</span>
            </div>
            <div v-if="postDetail.sentiment" class="post-detail-sentiment">
                <span :class="'sentiment-badge sentiment-' + postDetail.sentiment">帖子情感: {{ sentimentLabel(postDetail.sentiment) }}</span>
            </div>
            <!-- 标签芯片 -->
            <div v-if="parseJson(postDetail.event_tags, []).length || parseJson(postDetail.opinion_tags, []).length" class="post-detail-tags">
                <span v-for="t in parseJson(postDetail.event_tags, [])" :key="'e'+t" class="tag-chip tag-event">{{ t }}</span>
                <span v-for="t in parseJson(postDetail.opinion_tags, [])" :key="'o'+t" class="tag-chip tag-opinion">{{ t }}</span>
            </div>
            <!-- 维度情感小条 -->
            <div v-if="parsedDimSentiment(postDetail.dim_sentiment).length" class="post-detail-dims">
                <div class="post-detail-section-title">维度情感</div>
                <div v-for="d in parsedDimSentiment(postDetail.dim_sentiment)" :key="d.dim" class="dim-bar-row">
                    <span class="dim-bar-label">{{ d.dim }}</span>
                    <div class="dim-bar-track"><div class="dim-bar-fill" :style="{width: (Math.max(0, Math.min(1, d.score)) * 100) + '%'}"></div></div>
                    <span class="dim-bar-score">{{ Number(d.score).toFixed(2) }}</span>
                </div>
            </div>
            <!-- 评论摘要 -->
            <div v-if="parsedCommentSummary(postDetail.comment_summary)" class="post-detail-summary">
                <div class="post-detail-section-title">
                    评论摘要
                    <span v-if="parsedCommentSummary(postDetail.comment_summary).is_argumentative" class="argue-flag">⚠ 争议</span>
                </div>
                <div class="summary-themes" v-if="parsedCommentSummary(postDetail.comment_summary).genuine_themes?.length">
                    <span v-for="t in parsedCommentSummary(postDetail.comment_summary).genuine_themes" :key="t" class="tag-chip tag-theme">{{ t }}</span>
                </div>
                <div class="summary-sentiment" v-if="parsedCommentSummary(postDetail.comment_summary).genuine_sentiment">
                    评论区真实情感: <b>{{ sentimentLabel(parsedCommentSummary(postDetail.comment_summary).genuine_sentiment) }}</b>
                </div>
                <div class="summary-text" v-if="parsedCommentSummary(postDetail.comment_summary).summary">{{ parsedCommentSummary(postDetail.comment_summary).summary }}</div>
            </div>
```

- [ ] **Step B3: style.css 加样式（追加到文件末尾）**

```css
/* Post detail modal — analysis fields */
.post-detail-subject { color: var(--muted, #888); font-size: 13px; }
.post-detail-origin { margin-left: auto; color: var(--accent, #2348b8); text-decoration: none; font-size: 13px; }
.post-detail-tags, .summary-themes { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0; }
.tag-chip { padding: 3px 10px; border-radius: 12px; font-size: 12px; background: #f0f1f4; color: #444; }
.tag-event { background: #e8efff; color: #2348b8; }
.tag-opinion { background: #fff1e8; color: #c96442; }
.tag-theme { background: #f3e8ff; color: #8B5CF6; }
.post-detail-dims, .post-detail-summary { margin-top: 12px; padding-top: 10px; border-top: 1px solid #eee; }
.post-detail-section-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; color: #333; }
.dim-bar-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 12px; }
.dim-bar-label { width: 110px; color: #555; flex-shrink: 0; }
.dim-bar-track { flex: 1; height: 8px; background: #f0f1f4; border-radius: 4px; overflow: hidden; }
.dim-bar-fill { height: 100%; background: linear-gradient(90deg, #c96442, #2348b8); }
.dim-bar-score { width: 32px; text-align: right; color: #888; }
.argue-flag { color: #c96442; font-weight: 700; margin-left: 6px; font-size: 12px; }
.summary-sentiment { font-size: 13px; color: #444; margin: 6px 0; }
.summary-text { font-size: 13px; color: #555; line-height: 1.5; margin-top: 6px; }
```

- [ ] **Step B4: bump app.js 缓存版本号**

`frontend/index.html`：`app.js?v=10` → `app.js?v=11`，`dialog.js?v=9` → `dialog.js?v=10`（确保新 JS 生效）。

- [ ] **Step B5: 浏览器验证（主 agent 做）**

打开 `http://localhost:9050/` → 选 MONA M03 → 点热帖 → modal 应显示：标签芯片、维度条、评论摘要（含争议标记）、查看原文链接。

- [ ] **Step B6: Commit**

```bash
git add frontend/index.html frontend/static/js/app.js frontend/static/css/style.css
git commit -m "feat(frontend): post detail modal shows dim/tags/comment-summary/origin link"
```

---

## Task C: 争议帖预警卡片（独立）

**Files:**
- Modify: `frontend/index.html` — 在 04 事件脉搏区域加争议卡片容器
- Modify: `frontend/static/js/app.js` — 加 data 字段 + `loadControversialPosts` + 调用
- Modify: `frontend/static/css/style.css` — 争议卡片样式

**背景：** `GET /api/dashboard/comment-sentiment-diff/{vid}` 已就绪，返回帖子情感 vs 评论情感不一致的争议帖。前端零调用。这是舆情最高价值信号（翻车预警）。

- [ ] **Step C1: app.js data 加字段（在 `reports: []` 附近）**

```javascript
            controversialPosts: [],
```

- [ ] **Step C2: app.js 加 `loadControversialPosts` 方法（在 `loadReports` 附近）**

```javascript
        async loadControversialPosts() {
            try {
                const resp = await fetch(`/api/dashboard/comment-sentiment-diff/${this.currentVehicleId}?start=${this.rangeStart}&end=${this.rangeEnd}`);
                this.controversialPosts = resp.ok ? await resp.json() : [];
            } catch (e) { this.controversialPosts = []; }
        },
```

- [ ] **Step C3: app.js 在 `onVehicleChange` 的加载队列里调用**

找到 `onVehicleChange`（调用 loadOverview/loadTrend… 的地方，通常是 `Promise.all([...])` 或顺序 await 列表），加入 `this.loadControversialPosts()`。

- [ ] **Step C4: index.html 在 04 事件脉搏 section 内、`观点标签 TOP10` 卡片后，加争议卡片**

在 04 section 的 `.bottom-dual`（含事件时间线 + 观点标签）之后插入：

```html
        <div class="card controversial-area" v-if="controversialPosts.length" style="margin-top:16px">
            <div class="card-title">争议帖预警<span class="card-sub">帖子情感 vs 评论区真实情感不一致</span></div>
            <div class="controversial-list">
                <div v-for="p in controversialPosts.slice(0, 5)" :key="p.post_id" class="controversial-item">
                    <div class="controversial-title">{{ p.title }}</div>
                    <div class="controversial-meta">
                        <span class="sentiment-badge sentiment-{{ p.post_sentiment }}">帖 {{ sentimentLabel(p.post_sentiment) }}</span>
                        <span>→</span>
                        <span class="sentiment-badge sentiment-{{ p.comment_sentiment }}">评 {{ sentimentLabel(p.comment_sentiment) }}</span>
                        <span v-if="p.is_argumentative" class="argue-flag">⚠ 争议</span>
                    </div>
                    <div class="controversial-themes" v-if="p.genuine_themes?.length">
                        <span v-for="t in p.genuine_themes" :key="t" class="tag-chip tag-theme">{{ t }}</span>
                    </div>
                    <div class="controversial-summary" v-if="p.summary">{{ p.summary }}</div>
                </div>
            </div>
        </div>
```

- [ ] **Step C5: style.css 追加样式**

```css
/* Controversial posts warning card */
.controversial-list { display: flex; flex-direction: column; gap: 10px; }
.controversial-item { padding: 10px; border-left: 3px solid #c96442; background: #fafafa; border-radius: 4px; }
.controversial-title { font-size: 13px; font-weight: 600; margin-bottom: 6px; line-height: 1.4; }
.controversial-meta { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #666; }
.controversial-themes { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.controversial-summary { font-size: 12px; color: #666; margin-top: 6px; line-height: 1.4; }
```

- [ ] **Step C6: 浏览器验证（主 agent）**

选 MONA M03 → 04 区域底部出现「争议帖预警」卡片，列出 positive→mixed 等不一致帖。

- [ ] **Step C7: Commit**

```bash
git add frontend/index.html frontend/static/js/app.js frontend/static/css/style.css
git commit -m "feat(frontend): controversial-post warning card (comment-sentiment-diff)"
```

---

## Task D: 全部帖子列表卡片补情感标签 + 分析字段（依赖 A）

**Files:**
- Modify: `frontend/index.html` — `.post-card` 模板（~line 255-270）

**背景：** posts API 现在（Task A 后）返回 sentiment/event_tags/opinion_tags。卡片当前无情感标签，与「全部情感」筛选器割裂。

- [ ] **Step D1: index.html 升级 `.post-card` 模板，加情感徽章 + 观点标签芯片**

把 `.post-card`（含 header/title/content/footer）整体替换为：

```html
                <div v-for="p in posts.items" :key="p.id" class="post-card" @click="openPostDetail(p)">
                    <div class="post-card-header">
                        <span class="post-card-platform" :class="p.platform">{{ platformLabel(p.platform) }}</span>
                        <span v-if="p.sentiment" class="sentiment-badge" :class="'sentiment-' + p.sentiment">{{ sentimentLabel(p.sentiment) }}</span>
                        <span class="post-card-date">{{ p.published_at?.substring(0, 10) }}</span>
                    </div>
                    <div class="post-card-title">{{ p.title || p.content?.substring(0, 80) }}</div>
                    <div class="post-card-content" v-if="p.title && p.content">{{ p.content.substring(0, 100) }}...</div>
                    <div class="post-card-tags" v-if="parseJson(p.opinion_tags, []).length">
                        <span v-for="t in parseJson(p.opinion_tags, []).slice(0,3)" :key="t" class="tag-chip tag-opinion">{{ t }}</span>
                    </div>
                    <div class="post-card-footer">
                        <span class="post-card-author">{{ p.author }}</span>
                        <span class="post-card-engagement">
                            <span v-if="p.likes">▲ {{ p.likes }}</span>
                            <span v-if="p.comments">💬 {{ p.comments }}</span>
                            <span v-if="p.shares">→ {{ p.shares }}</span>
                        </span>
                    </div>
                </div>
```

- [ ] **Step D2: style.css 给 `.post-card-tags` 加 margin（如不存在）**

```css
.post-card-tags { display: flex; flex-wrap: wrap; gap: 4px; margin: 6px 0; }
```

- [ ] **Step D3: 浏览器验证（主 agent）**

⋮ 菜单 → 全部帖子 → 卡片显示情感徽章 + 观点标签芯片。

- [ ] **Step D4: Commit**

```bash
git add frontend/index.html frontend/static/css/style.css
git commit -m "feat(frontend): posts list cards show sentiment + opinion tags"
```

---

## Task E: 热帖卡片补 shares / engagement（独立，小）

**Files:**
- Modify: `frontend/index.html` — `.hot-post-meta`（~line 154-160）

- [ ] **Step E1: 在 `.hot-post-meta` 内，likes/comments 后加 shares**

把 `<span>💬 {{ p.comments || 0 }}</span>` 后追加：

```html
                                <span v-if="p.shares">→ {{ p.shares }}</span>
```

- [ ] **Step E2: 浏览器验证（主 agent）**

热帖卡片显示 shares。

- [ ] **Step E3: Commit**

```bash
git add frontend/index.html
git commit -m "feat(frontend): hot post cards show shares count"
```

---

## Task F: event-distribution API 接入（独立，可选）

**Files:**
- Modify: `frontend/index.html` — 加容器（04 或 05 区域）
- Modify: `frontend/static/js/app.js` — data + load + render

**背景：** `GET /api/dashboard/event-distribution/{vid}` 返回按 `post.event_tags` 聚合的 TOP15 标签 `[[tag, count], ...]`。和 EventGroup 时间线不同维度（这是帖级标签频次）。可作为水平柱状图放在 04 区域。

- [ ] **Step F1: app.js data 加 `eventTagsDist: []` 和 `eventTagsChart: null`**

- [ ] **Step F2: app.js 加 `loadEventTagsDist` + `renderEventTagsChart`（水平柱状，参考现有 dim-chart 渲染风格）**

```javascript
        async loadEventTagsDist() {
            try {
                const resp = await fetch(`/api/dashboard/event-distribution/${this.currentVehicleId}?start=${this.rangeStart}&end=${this.rangeEnd}`);
                this.eventTagsDist = resp.ok ? await resp.json() : [];
                this.$nextTick(() => this.renderEventTagsChart());
            } catch (e) { this.eventTagsDist = []; }
        },
        renderEventTagsChart() {
            const el = document.getElementById('event-tags-chart');
            if (!el || !this.eventTagsDist.length) return;
            if (!this.eventTagsChart) this.eventTagsChart = echarts.init(el);
            const data = this.eventTagsDist.map(([tag, count]) => ({name: tag, value: count}))
                .sort((a, b) => a.value - b.value);
            this.eventTagsChart.setOption({
                grid: {left: 100, right: 30, top: 10, bottom: 10},
                tooltip: {},
                xAxis: {type: 'value'},
                yAxis: {type: 'category', data: data.map(d => d.name)},
                series: [{type: 'bar', data: data.map(d => d.value), itemStyle: {color: '#2348b8'}}],
            }, true);
        },
```

- [ ] **Step F3: app.js 在 `onVehicleChange` 加载队列加 `this.loadEventTagsDist()`；resize 监听里加 `this.eventTagsChart?.resize()`**

- [ ] **Step F4: index.html 在 04 section 的 `.bottom-dual` 后（争议卡片前或后）加**

```html
        <div class="card" v-if="eventTagsDist.length" style="margin-top:16px">
            <div class="card-title">事件标签分布<span class="card-sub">帖级标签频次 TOP15</span></div>
            <div id="event-tags-chart" style="height:300px"></div>
        </div>
```

- [ ] **Step F5: 浏览器验证（主 agent）**

04 区域出现水平柱状图（事件标签频次）。

- [ ] **Step F6: Commit**

```bash
git add frontend/index.html frontend/static/js/app.js
git commit -m "feat(frontend): event-tags distribution chart (event-distribution API)"
```

---

## Verification（主 agent 收尾）

- [ ] 浏览器硬刷新 `http://localhost:9050/`，选 MONA M03，逐项确认：
  - 帖子详情 modal：标签芯片 + 维度条 + 评论摘要 + 原文链接（Task B）
  - 争议帖预警卡片（Task C）
  - 全部帖子卡片情感/标签（Task D）
  - 热帖 shares（Task E）
  - 事件标签分布图（Task F）
- [ ] bump 未生效时 Ctrl+F5；index.html 已加 `Cache-Control: no-store`，普通刷新应足够。

## 执行顺序建议

Task A 先（B/D 依赖）。然后 B/D 可并行；C/E/F 独立可并行。建议分两批：批1 = A；批2 = B/C/D/E/F（subagent 并行）。
