# published_at 采集层根治 — 设计文档

> 日期：2026-06-29
> 主题：根治 published_at NULL 问题——让抖音/微博/小红书新采集帖产出精确时间，并修复下游对 NULL 的错误处理

## 1. 背景

微博 / 抖音帖的 `published_at` 在 DB 里全是 NULL。**此前误判为"dashboard 窗口过滤"单一问题**，已在 API/前端层做了 4 次"去窗口绕过"。但代码审查发现：published_at NULL 在本项目里影响**至少 5 处**，其中两处是看板核心产出（**热度计算系统性低估**、**事件时间分布被 now() 污染**），远不止 dashboard 窗口。

本设计在**采集层**根治（让新帖带精确时间），并**顺带修一个独立 bug**（event_tracker 用 `now()` 兜底 NULL）。

## 2. 目标

1. 抖音 / 微博 / 小红书**新采集**的帖在 DB 中 `published_at` 非 NULL（精确到秒）。
2. 把分散且各自漏格式的时间解析逻辑，收口为一个可单测的函数 `_parse_datetime`。
3. 修复 `event_tracker.py:484` 用 `datetime.now()` 兜底 NULL 的独立 bug。
4. **根治的判据不是"DB 非 NULL"，而是"5 处下游依赖恢复正确行为"**（见 §5、§12）。

## 3. 非目标（YAGNI）

- **不回填历史 NULL 数据**：现有 NULL 帖维持现状，靠增量 / 重新采集自然带正确时间覆盖。
- **不动 dashboard / heat_calculator 等下游的窗口逻辑本身**：这些查询逻辑正确（带时间窗口过滤是对的），问题在数据缺时间。数据补齐后它们自然恢复，**不需要改查询**。
- **不做快手**：快手只有相对时间（"3天前"），解析需估算易不准，价值低，单独评估。
  - ⚠️ 副作用：快手帖 `published_at` 仍 NULL，在 §5 的窗口类下游（热度/dashboard）仍被过滤，事件层仍走 now() 兜底。属已知边界。

## 4. 根因分析

### 4.1 存储链路只认 ISO
`models/schemas.py`：`RawPost.published_at = Column(DateTime)`。
`pipeline/scheduler.py:_store_posts`（约 285-291 行）：

```python
published_at = None
raw_date = post.get("published_at", "")
if raw_date:
    try:
        published_at = datetime.fromisoformat(raw_date)   # 只认 ISO
    except (ValueError, TypeError):
        pass                                              # 失败 → None → NULL
```

### 4.2 各平台现状

| 平台 | 采集层是否提取时间 | `_make_post` 收到的值 | 能否 `fromisoformat` | DB 结果 |
|------|:--:|------|:--:|:--:|
| 抖音 | ❌ `SEARCH_FETCH_JS` 只取 id/title，未读 `create_time` | `""`（未传 published_at） | — | NULL |
| 微博 | ✅ 取了 `m.created_at` | `"Sun Jun 29 10:00:00 +0800 2025"` | ❌ 英文格式 | NULL |
| 小红书 | ❌ `DETAIL_JS` 未读 `.date` | `""`（未传 published_at） | — | NULL |
| 快手 | ❌ 卡片无时间；overlay 相对时间未启用 | `""`（未传 published_at） | — | NULL |

### 4.3 根因分类
- **类 A 没提取**：抖音 / 小红书 —— 采集 JS 根本没读时间字段。
- **类 B 格式不兼容**：微博 —— API 给的 `created_at` 是英文日期串，`_make_post` 内的 `_ts_to_iso`（只认数字）和 `_store_posts` 的 `fromisoformat`（只认 ISO）**双重失败**。

## 5. published_at NULL 的完整影响面（5 处）

> 这是本设计相对初版的关键补充。published_at NULL 不只是"窗口少了一些数据"，还主动污染了事件层。

| # | 文件:行 | 逻辑 | NULL 的后果 |
|---|---------|------|------|
| 1 | `dashboard.py`（~10 处） | `published_at >= start` 时间窗口 | wb/dy 帖被过滤（热帖/词云/趋势等 API 数据不全） |
| 2 | **`heat_calculator.py:62/73/88`** | 讨论声量、媒体声量、互动量均 `published_at >= start`；`SOCIAL_SOURCES=("cdp",)` 覆盖全部社媒帖 | **wb/dy/xhs NULL 帖的互动量不计入 → 看板"热度 KPI"系统性低估** |
| 3 | **`event_tracker.py:484`** | `(raw["published_at"] if raw else None) or datetime.now()` | **NULL 帖被当作"当前时间"，污染事件时间切分/时间线**（独立 bug，见 §8） |
| 4 | `relevance_filter.py:126` | `if pub is not None` 才查"早于上市" | NULL 帖**跳过**上市日期相关性检查，可能混入无关老帖 |
| 5 | `deduplicator.py:20` | `sorted(..., key=published_at or "")` | NULL 帖排序聚在头部，去重顺序略偏（影响轻） |

**根治后**：1/2/4/5 随新数据带正确时间而自然恢复（查询逻辑无需改）；3 需独立修复（§8）。

## 6. 设计：`_parse_datetime(raw)` 统一收口

在 `pipeline/collectors/cdp_collector.py` 紧邻 `_ts_to_iso` 新增 `_parse_datetime(raw) -> str`，输出干净 ISO 字符串（如 `"2025-06-29T10:00:00"`），**永不抛异常**：

```
_parse_datetime(raw):
  1. 空 / None                     → ""
  2. 纯数字                         → 当 Unix 时间戳（秒/毫秒自适应，复用 _ts_to_iso）
  3. 尝试 datetime.fromisoformat   → ISO（覆盖新闻源 / 已规范格式）
  4. 尝试 strptime 微博格式          → ISO（"%a %b %d %H:%M:%S %z %Y"）
  5. 全部失败                       → ""（best-effort，不丢帖）
```

> 已知 edge case：微博近期帖（几分钟内）`created_at` 可能是相对时间（"3分钟前" / "just now"），无法解析 → 返回 `""`。属可接受边界，标准英文格式的帖正常解析。

`_make_post`（约 188 行）标准化调用替换：

```python
# 旧
"published_at": _ts_to_iso(published_at) or published_at,
# 新
"published_at": _parse_datetime(published_at),
```

> 收口后，`_make_post` 输出的 `published_at` 永远是干净 ISO 或空串；`_store_posts` 的 `fromisoformat` 收到干净 ISO 自然成功。存储层不改。

## 7. 各平台改动（采集 JS 只加"传原值"）

### 7.1 抖音 — `DouyinExtractor`
- `SEARCH_FETCH_JS` 的 `vids.push` 增加：`create_time: a.create_time`（`aweme_info` 自带，Unix 秒）。
- `_search_douyin` 两处 `_make_post`（正常分支约 809 行 + detail 失败兜底约 839 行）均增加 `published_at=v.get("create_time", "")`。
- 时间来自 search API，**无需开 detail 页**，不增加采集耗时。

### 7.2 微博 — `WeiboExtractor`
- **JS 不动**（`SEARCH_JS` 已返回 `created_at`，`_search_weibo` 已传 `published_at=c.get("created_at","")`）。
- 靠新的 `_parse_datetime` 解析英文串。

### 7.3 小红书 — `XiaohongshuExtractor`
- `DETAIL_JS` 增加日期提取，尝试多个选择器（`.date` / `.publish-time` / `[class*=date]` / `.bottom-info .date` 等），取首个非空，返回 `date` 字段。
- `_search_xhs` 的 `_make_post` 增加 `published_at=detail.get("date", "")`。
- ⚠️ **具体选择器待实采确认**（方案未知数，由 §11.2 实采坐实）。

## 8. 独立 bug 修复：`event_tracker.py:484` 的 now() 兜底

**现状**（约 484 行，构造事件检测用的 post_dicts）：
```python
"published_at": (raw["published_at"] if raw else None) or datetime.now(),
```
NULL 帖 → `datetime.now()` → 被当成"今天发布"，污染事件时间切分。

**修复方向**：去掉 `or datetime.now()`，让 `None` 透传。下游 `_get_post_date`（237-246）**本就能正确处理 None → 返回 None**；`split_community_by_time`（261 行）用 `_get_post_date(p) or date.min`，None 帖排到 `date.min`（时间最前）聚成一组，**不再污染"今天"**。

```python
# 新
"published_at": raw["published_at"] if raw else None,
```

> ⚠️ 实施前需确认 484 行之后无其他代码假设 `post["published_at"]` 非 None（topic 标注 / 关键词 / 命名阶段均不依赖时间，预期安全，writing-plans 阶段复核）。

## 9. 数据流

```
JS 提取时间原值（create_time / created_at / date 文本）
  → _make_post 调 _parse_datetime → 干净 ISO（或 ""）
  → post dict → scheduler._store_posts 的 fromisoformat（成功）→ DB 精确 DateTime
  → 下游 5 处依赖自然恢复正确行为（窗口类无需改查询；event_tracker 配合 §8 修复）
```

## 10. 错误处理

全链路 best-effort、不丢帖：任何环节取不到 / 解析失败 → `""` → NULL。失败面从"四平台全部"缩小到"真正取不到时间的少数帖 + 快手"。

## 11. 顺带一致性改进（默认包含）

`_make_comment`（约 209 行）的 `published_at` 也改用 `_parse_datetime(published_at)`。评论时间当前未被窗口用到，价值低，但函数已存在，零成本统一格式。**如需排除可否决。**

## 12. 验证标准（"根治成功"定义 — 已升级）

不再只看"DB 非 NULL"，而是确认下游 5 处行为恢复：

| 维度 | 验证方式 |
|------|------|
| 数据层 | 实采后 DB 中抖音/微博/小红书**新帖** `published_at` 非 NULL |
| 热度（§5-#2） | 实采后 `heat_calculator` 对 wb/dy/xhs 帖所在日期的 `discussion_volume` / `interaction_intensity` 非零（不再全被窗口过滤） |
| 事件（§5-#3） | 单测 + 代码确认 event_tracker 不再用 now() 兜底 NULL；None 帖走 date.min |
| 相关性（§5-#4） | 预期：根治后部分早于上市的 wb/dy 老帖被 relevance_filter 正确 REJECT（见 §13） |
| 单元测试 | `_parse_datetime` / `_make_post` / event_tracker `_get_post_date` 全绿 |

## 13. 预期行为变化（需预期，非 bug）

- **wb/dy/xhs 相关帖数量可能下降**：根治后这些帖有真实 `published_at`，`relevance_filter` 的"早于上市"规则（§5-#4）对它们生效，会正确 REJECT 掉一批此前因 NULL 跳过检查而混入的**无关老帖**。结果是数据更干净，但相关帖总数可能减少——属正确行为，需提前预期。
- 热度 KPI / 事件时间分布随新数据累积逐渐恢复准确（历史 NULL 帖靠重新采集替换，渐进）。

## 14. 风险与未知数

| 风险 | 应对 |
|------|------|
| 抖音 `create_time` 字段名 / 微博 `created_at` 格式 / 小红书选择器均基于经验假设 | **实采前先侦察**（见 §15）：先确认真实字段/格式/选择器，再据此写解析，避免基于错误假设写代码 |
| event_tracker 去掉 now() 后下游异常 | writing-plans 阶段复核 484 行之后无 `published_at` 非 None 假设 + 单测 |
| `_ts_to_iso` 调用方 | **已确认**（self-review grep）：仅 `_make_post` 一处生产调用 + 测试 3 例。`_parse_datetime` 复用 `_ts_to_iso`，旧函数保留，现有测试不受影响 |
| 小红书 DOM 无可靠日期元素 | 实采确认；若无，则小红书回退 NULL（与现状一致，不恶化） |

## 15. 实施顺序（侦察前置）

> 避免基于假设写代码：先侦察三平台真实响应，再实现解析与提取。

1. **侦察**：跑探测脚本确认抖音 search API 真实返回（`create_time` 字段名/类型）、微博 `created_at` 真实格式、小红书详情页 DOM 日期元素。项目已有 `scripts/diagnose_douyin.py` 先例可复用模式。
2. **实现 `_parse_datetime`** + `_make_post`/`_make_comment` 切换。
3. **三平台 JS 提取**（按侦察结果填字段/选择器）。
4. **event_tracker:484 修复**。
5. **单元测试**。
6. **实采验证**（§12 全维度）。

## 16. 涉及文件

- `pipeline/collectors/cdp_collector.py` — 新增 `_parse_datetime`；改 `_make_post` / `_make_comment`；抖音 `SEARCH_FETCH_JS` + `_search_douyin`；小红书 `DETAIL_JS` + `_search_xhs`
- `pipeline/analysis/event_tracker.py` — 484 行去掉 `or datetime.now()`
- `tests/test_cdp_collector.py` — 新增 `_parse_datetime` / `_make_post` 单测
- `tests/test_event_tracker.py` — 新增 None published_at 不被 now() 兜底的回归测试
- 新增侦察脚本 + 实采验证脚本（如 `scripts/diagnose_published_at.py` / `scripts/verify_published_at.py`）
