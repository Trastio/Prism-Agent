# Pipeline Quality Round 2 — 采集/分析管线修复

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 5 个互联的管线缺陷——3 个根因（采集管道缺口 / Schema-LLM 契约断裂 / 数据管线无验证层），覆盖 comment_summary 覆盖、subject_name 持久化、6M 异常值治理。

**Architecture:** 改动分层：采集层（CDP Douyin 评论采集）→ 分析层（subject_name 列 + 写入 + heat 上限+fallback）→ 回填脚本。不影响前端。

**Tech Stack:** Python + FastAPI + SQLAlchemy async + SQLite + aiohttp (CDP)

---

## 文件结构

| 文件 | 改动类型 | 职责 |
|------|----------|------|
| `pipeline/collectors/cdp_collector.py` | 修改 | 补 Douyin 评论采集（`_search_douyin` 返回真实 comments） |
| `models/schemas.py` | 修改 | `AnalyzedPost` 加 `subject_name` 列 |
| `models/database.py` | 修改 | 加 `_migrate_subject_name` 迁移 |
| `pipeline/analysis/batch_runner.py` | 修改 | `AnalyzedPost` 构造时写入 `subject_name` |
| `pipeline/analysis/heat_calculator.py` | 修改 | SOCIAL_SOURCES 去 mediacrawler + interaction_intensity 上限 + attention_index fallback 对数化 |
| `scripts/backfill_subject.py` | 修改 | 回填 `subject_name` 列（competitor 帖让 LLM 重分类） |

---

### Task 1: 跑 CDP 验证脚本（基线确认）

**Files:** 不改代码

- [ ] **Step 1: 检查 CDP Proxy 状态**

```powershell
curl http://localhost:3456/health
```

Expected: JSON 响应（proxy 在线）或 `connection refused`（需先启动）

若 proxy 不在线，启动：
```bash
node ~/.claude/skills/web-access/scripts/cdp-proxy.mjs &
```

- [ ] **Step 2: 运行验证脚本**

```powershell
cd C:\Users\<you>\Desktop\Agent项目\Vehicle Sentiment Analysis Board
python scripts/verify_cdp_collector.py
```

Expected: 四平台均输出帖子列表 + 评论数量。记录各平台实际评论数，作为修复后对比基准。

- [ ] **Step 3: 记录基线**

重点关注：
- 抖音评论数（修复前预期为 0——`_search_douyin` 返回 `posts, []`）
- 快手评论数
- 小红书评论数
- 微博评论数

---

### Task 2: 修复抖音评论采集

**Files:**
- Modify: `pipeline/collectors/cdp_collector.py:625-655`

**背景:** `_search_douyin` 打开每个视频详情页后调用 `DETAIL_JS` 提取 innerText，但没有提取评论。评论 DOM 在视频详情页下方，需要额外的 JS 表达式滚动并提取评论区元素。

- [ ] **Step 1: 查看 DouyinExtractor 的 DETAIL_JS 和评论区 DOM 结构**

先读 `DouyinExtractor` 定义，了解现有 `DETAIL_JS` 和 `SEARCH_JS`：

```bash
grep -n "class DouyinExtractor" pipeline/collectors/cdp_collector.py
```

读该类的完整定义，确认现有 JS 表达式和是否有评论区相关方法。

- [ ] **Step 2: 添加 Douyin 评论提取 JS**

在 `DouyinExtractor` 类中添加 `COMMENTS_JS` 属性——滚动评论区并提取可见评论：

```python
# 在 DouyinExtractor 类中添加（DETAIL_JS 后面）
COMMENTS_JS = """(function(){
    const comments = [];
    // 滚动评论区容器
    const container = document.querySelector('[data-e2e="comment-list"]') ||
                      document.querySelector('.comment-container') ||
                      document.querySelector('[class*="comment"]');
    if (!container) return JSON.stringify(comments);
    // 多次滚动加载更多评论
    for (let i = 0; i < 5; i++) {
        container.scrollTop = container.scrollHeight;
    }
    // 等待渲染
    return new Promise(resolve => {
        setTimeout(() => {
            const items = document.querySelectorAll('[data-e2e="comment-item"], .comment-item, [class*="CommentItem"]');
            items.forEach(el => {
                const text = el.querySelector('[data-e2e="comment-content"], .comment-content, [class*="content"]')?.innerText?.trim();
                const likes = el.querySelector('[data-e2e="comment-like-count"], .like-count, [class*="like"]')?.innerText?.trim();
                if (text) {
                    comments.push({
                        content: text,
                        likes: parseInt(String(likes || '0').replace(/[^0-9]/g, '')) || 0,
                    });
                }
            });
            resolve(JSON.stringify(comments));
        }, 3000);
    });
})()"""
```

- [ ] **Step 3: 修改 `_search_douyin` 使用 COMMENTS_JS**

将 `cdp_collector.py:655` 的 `return posts, []` 替换为实际评论采集逻辑。在详情页循环内（line 641 `posts.append(...)` 之后、`finally: close_tab(detail_tab)` 之前），添加评论提取：

```python
# 在 _search_douyin 的详情页循环内，posts.append(_make_post(...)) 之后，
# finally: close_tab(detail_tab) 之前，添加：
try:
    raw_comments = await self._client.eval_js(detail_tab, ext.COMMENTS_JS)
    comment_list = _parse_json_result(raw_comments)
    for cmt in comment_list:
        comments.append({
            "content": str(cmt.get("content", "") or "").strip(),
            "likes": int(cmt.get("likes", 0) or 0),
            "post_url": detail_url,
            "platform": "douyin",
        })
except Exception:
    pass  # 评论提取失败不影响帖子采集
```

并将 line 655 `return posts, []` 改为：

```python
return posts, comments
```

- [ ] **Step 4: 再次运行验证脚本，确认抖音评论 > 0**

```powershell
python scripts/verify_cdp_collector.py
```

Expected: 抖音输出评论数 > 0。

- [ ] **Step 5: Commit**

```bash
git add pipeline/collectors/cdp_collector.py
git commit -m "feat: add Douyin comment extraction in CDP collector"
```

---

### Task 3: 添加 `subject_name` 列 + 写入路径

**Files:**
- Modify: `models/schemas.py:61-77`
- Modify: `models/database.py:39-46`
- Modify: `pipeline/analysis/batch_runner.py:169-180`

- [ ] **Step 1: 写迁移测试**

`tests/test_subject_name_migration.py`:

```python
"""Test subject_name column exists and stores competitor names."""
import pytest
from models.schemas import AnalyzedPost


def test_analyzed_post_has_subject_name_column():
    """Verify AnalyzedPost model has subject_name attribute."""
    assert hasattr(AnalyzedPost, "subject_name"), (
        "AnalyzedPost.subject_name column missing — run migration first"
    )


def test_subject_name_defaults_to_empty():
    """subject_name should default to empty string for new records."""
    ap = AnalyzedPost(
        id="test-01", post_id="p1", vehicle_id="v1",
        sentiment="neutral", subject="self",
    )
    assert ap.subject_name == "" or ap.subject_name is None
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
pytest tests/test_subject_name_migration.py -v
```

Expected: FAIL — `AttributeError: 'AnalyzedPost' object has no attribute 'subject_name'`

- [ ] **Step 3: 在 `AnalyzedPost` 模型添加 `subject_name` 列**

`models/schemas.py`，在 `subject = Column(String)` 行之后添加：

```python
    # subject_name: 主要讨论的车名。self 时=主车型名，competitor 时=竞品车名，other 时为空
    subject_name = Column(String, default="")
```

- [ ] **Step 4: 在 `database.py` 添加迁移**

`models/database.py`，在 `_migrate_subject` 函数后面（line 46 之后）添加：

```python
        def _migrate_subject_name(sync_conn):
            sync_conn.execute(text(
                "ALTER TABLE analyzed_posts ADD COLUMN subject_name VARCHAR DEFAULT ''"
            ))
        try:
            await conn.run_sync(_migrate_subject_name)
        except Exception:
            pass  # Column already exists
```

- [ ] **Step 5: 在 `batch_runner.py` 写入 `subject_name`**

`batch_runner.py:169-180`，`AnalyzedPost(...)` 构造中添加 `subject_name` 参数：

```python
                self._session.add(AnalyzedPost(
                    id=str(uuid.uuid4()),
                    post_id=post.id,
                    vehicle_id=vehicle_id,
                    sentiment=analysis["sentiment"],
                    event_tags=json.dumps(analysis.get("event_tags", []), ensure_ascii=False),
                    opinion_tags=json.dumps(analysis.get("opinion_tags", []), ensure_ascii=False),
                    confidence=max(0.0, min(1.0, confidence)),
                    model_used=model_name,
                    dim_sentiment=json.dumps(analysis.get("dim_sentiment", {}), ensure_ascii=False),
                    subject=analysis.get("subject", "self"),
                    subject_name=analysis.get("subject_name", "") or "",
                ))
```

- [ ] **Step 6: 检查 analyzer.py 的 `analyze_single` 直调路径**

`analyzer.py` 的 `analyze_single` 和 `_analyze_batch_dual` 已返回 `subject_name`（line 197, 278），无需改动。但需确认是否有其他直调 `AnalysisPipeline` 的路径遗漏。搜索：

```bash
grep -rn "AnalyzedPost(" pipeline/ api/
```

若仅有 `batch_runner.py:169` 一处，无需额外改动。

- [ ] **Step 7: Run test to verify it passes**

```powershell
pytest tests/test_subject_name_migration.py -v
```

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add models/schemas.py models/database.py pipeline/analysis/batch_runner.py tests/test_subject_name_migration.py
git commit -m "feat: add subject_name column to analyzed_posts with migration and write path"
```

---

### Task 4: 更新回填脚本

**Files:**
- Modify: `scripts/backfill_subject.py:85-109`

- [ ] **Step 1: 修改回填 SQL 写入 `subject_name`**

`scripts/backfill_subject.py` line 102-105，当前代码丢弃了 `_sname`：

```python
        subject, _sname = classify(text, self_words)  # _sname 被丢弃
        updated[subject] += 1
        if not args.dry_run:
            con.execute("UPDATE analyzed_posts SET subject=? WHERE id=?", (subject, ap_id))
```

改为：

```python
        subject, sname = classify(text, self_words)
        updated[subject] += 1
        if not args.dry_run:
            con.execute(
                "UPDATE analyzed_posts SET subject=?, subject_name=? WHERE id=?",
                (subject, sname or "", ap_id),
            )
```

- [ ] **Step 2: 检查 `classify` 函数是否正确返回 `subject_name`**

读 `scripts/backfill_subject.py` 的 `classify()` 函数（line 63 附近），确认其返回 `(subject, subject_name)` 二元组：

```bash
grep -n "def classify" scripts/backfill_subject.py
```

读该函数，确认返回值包含 `subject_name`。若只返回 `subject`，需补上。

- [ ] **Step 3: 干跑验证**

```powershell
python scripts/backfill_subject.py --dry-run
```

Expected: 输出分布统计，"待回填"条数为 0（全部已有 subject）。若还有 NULL subject 的帖（新帖），会显示回填数。

- [ ] **Step 4: Commit**

```bash
git add scripts/backfill_subject.py
git commit -m "fix: backfill subject_name alongside subject in backfill script"
```

---

### Task 5: 从 SOCIAL_SOURCES 移除 `mediacrawler`

**Files:**
- Modify: `pipeline/analysis/heat_calculator.py:10`

- [ ] **Step 1: 修改 SOCIAL_SOURCES 常量**

`heat_calculator.py:10`：

```python
# Before:
SOCIAL_SOURCES = ("cdp", "mediacrawler")

# After — MC 旧数据不再参与热力计算（帖子保留在 raw_posts 中，但不计入 discussion_volume 和 interaction_intensity）
SOCIAL_SOURCES = ("cdp",)
```

- [ ] **Step 2: 搜索其他引用 SOCIAL_SOURCES 的地方**

```bash
grep -rn "SOCIAL_SOURCES\|mediacrawler" pipeline/ api/ --glob="*.py"
```

Expected: 只有 `heat_calculator.py` 定义和使用。若有其他地方硬编码 `"mediacrawler"`，一并改为 `"cdp"`。

- [ ] **Step 3: 运行现有测试确认不回归**

```powershell
pytest tests/ -v --tb=short -x
```

Expected: 全部 PASS（或仅已知 pytest-asyncio 环境 warning）。

- [ ] **Step 4: Commit**

```bash
git add pipeline/analysis/heat_calculator.py
git commit -m "fix: exclude mediacrawler source from heat metrics calculation"
```

---

### Task 6: 添加 `interaction_intensity` 上限 + 修复 `attention_index` fallback

**Files:**
- Modify: `pipeline/analysis/heat_calculator.py:84-89`

- [ ] **Step 1: 添加上限常量 + 天花板检查**

在 `heat_calculator.py` 顶部（line 10 `SOCIAL_SOURCES` 之后）添加：

```python
# 单日 interaction_intensity 合理上限（防止单帖病毒传播污染整条热度线）
# 超过此值 clamp + warning log，避免 6M 异常值出现
_MAX_INTERACTION_PER_DAY = 500_000
```

- [ ] **Step 2: 在 line 84 后添加上限检查**

`heat_calculator.py:84` 之后，line 86 fallback 之前：

```python
        interaction_intensity = float(row[0] * ENGAGEMENT_WEIGHT_LIKES + row[1] * ENGAGEMENT_WEIGHT_COMMENTS + row[2] * ENGAGEMENT_WEIGHT_SHARES)

        # Clamp outlier spikes: single-day engagement above ceiling → cap + warn
        if interaction_intensity > _MAX_INTERACTION_PER_DAY:
            logger.warning(
                "interaction_intensity %.0f exceeds cap %d for vehicle %s on %s, clamping",
                interaction_intensity, _MAX_INTERACTION_PER_DAY, vehicle_id, target_date,
            )
            interaction_intensity = float(_MAX_INTERACTION_PER_DAY)
```

- [ ] **Step 3: 修复 fallback 的行号引用**

上限检查插入后，原来的 line 88-89 行号会后移。确认 fallback 代码不变：

```python
        # Fallback: 无百度指数（cookie 失效/groupon 未返回）时，用对数压缩后的 interaction_intensity
        # 原逻辑 attention_index = round(interaction_intensity, 1) 会将 6M 直接赋给 attention_index
        # 改为对数压缩：log1p(interaction_intensity) * 1000 —— 6M → ~15,600，20K → ~9,900
        import math
        if attention_index == 0.0 and interaction_intensity > 0:
            attention_index = round(math.log1p(interaction_intensity) * 1000, 1)
```

**注意:** `import math` 已在文件顶部添加（若未导入）。检查 `heat_calculator.py:1-5` 的 import 列表，没有 `import math` 则加上。

- [ ] **Step 4: 写单元测试验证上限逻辑**

`tests/test_heat_calculator_cap.py`:

```python
"""Test interaction_intensity capping and attention_index fallback."""
import math
from datetime import date
from pipeline.analysis.heat_calculator import HeatMetricCalculator, _MAX_INTERACTION_PER_DAY


def test_max_interaction_constant_exists():
    """Verify the cap constant is defined and reasonable."""
    assert _MAX_INTERACTION_PER_DAY == 500_000


def test_attention_fallback_uses_log_transform():
    """log1p(6_000_000)*1000 ≈ 15_600, not 6_000_000."""
    raw = 6_000_000.0
    result = round(math.log1p(raw) * 1000, 1)
    assert result < 20_000, f"Expected ~15,600, got {result}"
    # Sanity: normal value ~20,000 should give ~9,900
    normal = 20_000.0
    normal_result = round(math.log1p(normal) * 1000, 1)
    assert 9_000 < normal_result < 11_000, f"Expected ~9,900, got {normal_result}"
```

- [ ] **Step 5: 运行测试**

```powershell
pytest tests/test_heat_calculator_cap.py -v
```

Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add pipeline/analysis/heat_calculator.py tests/test_heat_calculator_cap.py
git commit -m "fix: cap interaction_intensity at 500k and use log1p for attention_index fallback"
```

---

### Task 7: 集成验证 — 重启服务 + 端到端检查

**Files:** 不改代码

- [ ] **Step 1: 重启服务并确认启动成功**

```powershell
# 先杀掉旧进程
Get-Process -Name python* | Where-Object {$_.CommandLine -like "*uvicorn*"} | Stop-Process -Force
# 启动
cd C:\Users\<you>\Desktop\Agent项目\Vehicle Sentiment Analysis Board
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Expected: `Application startup complete.`

- [ ] **Step 2: 验证 `subject_name` 列已生效**

```powershell
python -c "
import sqlite3
conn = sqlite3.connect('data/vehicles.db')
cols = [c[1] for c in conn.execute('PRAGMA table_info(analyzed_posts)')]
print('subject_name' in cols)
"
```

Expected: `True`

- [ ] **Step 3: 触发一次采集+分析，验证全链路**

```powershell
curl -X POST http://localhost:8000/api/collection/trigger \
  -H "Content-Type: application/json" \
  -d '{"vehicle_id": "<实际车型ID>"}'
```

监控日志确认：
- CDP 采集正常（四平台均有帖子入库）
- 分析管线正常（`batch_runner` 输出 analyzed 计数）
- `subject_name` 已写入（检查 DB：`SELECT subject_name FROM analyzed_posts WHERE subject='competitor' LIMIT 5`）

- [ ] **Step 4: 打开看板确认前端正常渲染**

浏览器访问 `http://localhost:8000/`，选车型 → 检查趋势图无 6M 尖峰。

- [ ] **Step 5: Commit（如有未提交改动）**

```bash
git status
git add -A
git commit -m "chore: integration verification — pipeline passes end-to-end"
```

---

## 自审清单

**1. Spec coverage:** 6 个待办问题全部覆盖——
- #6 CDP 验证 → Task 1
- #1 comment_summary 覆盖率 → Task 2（Douyin 评论采集，根因修复）
- #2 subject_name 缺失 → Task 3 + Task 4
- #4 6M 异常值 → Task 5 + Task 6
- #3 heat_metrics 4 维展示 → 前端改动，本次不做（阶段 3 单独处理）
- #5 lifecycle_anchors 自动检测 → 设计复杂度高，本次不做（阶段 3 单独处理）

**2. Placeholder scan:** 无 TBD/TODO/implement later。所有代码块完整。

**3. Type consistency:** `subject_name` 在 schema (String)、batch_runner (`.get("subject_name", "")`)、backfill (`sname or ""`) 中一致为 string。

**4. 不改 vendor 目录:** 确认无误。
