# 主题 B：平台命名一致性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** 建立 `pipeline/platforms.py` 单一真理源（全名规范 + `normalize_platform()`），采集/查询/调度/前端全部引用；一次性迁移历史缩写数据 → 全名；删除所有散落的别名兼容代码。

**Architecture:** 新建真理源模块 → CdpCollector 12 处写入改全名常量（顺带修 dy/douyin 混用）→ 查询层 dashboard/dialog 用 `normalize_platform()` 替换别名 → 迁移脚本统一 raw_posts + post_comments → 调度/分析/strategy 引用常量 → 前端 alias 简化。

**Tech Stack:** Python + SQLAlchemy async + SQLite（后端）；pytest 测试基建；Vue 前端。

**Spec:** `docs/superpowers/specs/2026-06-29-platform-naming-design.md`

> **侦察修正**：spec §1 表格端名对调——实测 **top-posts 单向别名(`dashboard.py:306`)、posts 双向别名(`:379`)**。单向的 top-posts 传全名 `douyin` 会漏旧 `dy` 数据。本 plan 统一用 normalize 替换两者。

---

## File Structure

| 文件 | 职责 |
|------|------|
| `pipeline/platforms.py`（新） | 单一真理源：全名常量 + 映射 + normalize/label 函数 |
| `scripts/migrate_platform_names.py`（新） | 幂等迁移 raw_posts + post_comments 缩写→全名 |
| `pipeline/collectors/cdp_collector.py` | 12 处写入改全名常量 |
| `api/routes/dashboard.py` | 删 2 处 `_PLATFORM_ALIASES`，用 normalize_platform |
| `api/routes/dialog.py` | 3 处 `==platform` 改 normalize |
| `pipeline/collectors/platform_strategy.py` | 引用常量 |
| `pipeline/scheduler.py` | 472/575/594 引用常量 |
| `pipeline/analysis/batch_runner.py` | 20-23 引用常量 |
| `frontend/static/js/app.js` | filteredHotTags/platformLabel alias 简化 |
| `tests/test_platforms.py`（新） | normalize/label 单测 |

## Task 依赖

- Task 1（真理源）→ Task 2/3/4/5（都依赖常量与 normalize）
- Task 6（前端）依赖 Task 4 执行后（数据全名）
- Task 7（迁移执行 + 验证）依赖 1-6 + 服务在线

---

## Task 1: platforms.py 单一真理源 + 单测

**Files:** `pipeline/platforms.py`（新）、`tests/test_platforms.py`（新）

- [ ] **Step 1: 新建 `pipeline/platforms.py`**（按 spec §3.1）
  - 全名常量 `XIAOHONGSHU/WEIBO/DOUYIN/KUAISHOU/NEWS`
  - `ALL_PLATFORMS`、`SOCIAL_PLATFORMS` 元组
  - `_SHORT_TO_FULL`、`_FULL_TO_SHORT`、`_LABELS` 映射
  - `normalize_platform(p)`：缩写/全名/大小写 → 规范全名；None→None；未知→原样小写
  - `platform_label(p)`：→ 中文标签

- [ ] **Step 2: 单测 `tests/test_platforms.py`**
  - `normalize_platform("dy")` == "douyin"；`"DOUYIN"` == "douyin"；`"douyin"` == "douyin"
  - `normalize_platform(None)` is None；`"unknown_x"` == "unknown_x"
  - `platform_label("xhs")` == "小红书"；`platform_label("news")` == "新闻源"
  - `SOCIAL_PLATFORMS` 含 4 社媒、不含 news

- [ ] **Step 3: 跑测试**
  ```bash
  pytest tests/test_platforms.py -v
  ```

- [ ] **Step 4: Commit**
  ```bash
  git add pipeline/platforms.py tests/test_platforms.py
  git commit -m "feat(platforms): 单一 platform 真理源模块 + normalize/label 函数 (主题B Task1)"
  ```

---

## Task 2: CdpCollector 统一写全名（修 dy/douyin 混用）

**Files:** `pipeline/collectors/cdp_collector.py`

- [ ] **Step 1: 顶部 import** `from pipeline.platforms import WEIBO, DOUYIN, KUAISHOU, XIAOHONGSHU`（或 `from pipeline import platforms`）

- [ ] **Step 2: 12 处写入改常量**（行号为当前 grep 结果）
  - 微博 `"wb"` → `WEIBO`：702, 726, 962
  - 快手 `"ks"` → `KUAISHOU`：764, 793
  - 抖音 `"dy"`/`"douyin"` → `DOUYIN`（统一，修混用）：847, 861, 876, 982
  - 小红书 `"xhs"` → `XIAOHONGSHU`：915, 928, 1001
  - 输入侧 `if platform in ("weibo","wb")`（668-674, 944-987）**保留**（仍接受两种输入），仅写入侧统一

- [ ] **Step 3: 跑现有采集器测试**
  ```bash
  pytest tests/test_cdp_collector.py -v
  ```

- [ ] **Step 4: Commit**
  ```bash
  git commit -m "fix(cdp): 采集写入统一全名，修抖音 dy/douyin 混用 (主题B Task2)"
  ```

---

## Task 3: 查询层 normalize 收口

**Files:** `api/routes/dashboard.py`、`api/routes/dialog.py`

- [ ] **Step 1: dashboard.py /top-posts（306-316）**
  - 删 `_PLATFORM_ALIASES` + `effective_platform`
  - `from pipeline.platforms import normalize_platform`
  - 改为：`if platform: query = query.where(RawPost.platform == normalize_platform(platform))`
  - 删函数内 `from sqlalchemy import or_`（不再需要）

- [ ] **Step 2: dashboard.py /posts（379-386）**
  - 删双向 `_PLATFORM_ALIASES` + alias OR 逻辑
  - 同样 `RawPost.platform == normalize_platform(platform)`

- [ ] **Step 3: dashboard.py /platform-distribution（248-264）**
  - 返回前 normalize 分组键：`{"platform": normalize_platform(row[0]) or "unknown", ...}`（防御：迁移前 dy/douyin 仍会分两组，normalize 合并；迁移后自然单一）

- [ ] **Step 4: dialog.py（75/82/89）**
  - 3 处 `RawPost.platform == platform` → `== normalize_platform(platform)`

- [ ] **Step 5: 跑 API 测试**
  ```bash
  pytest tests/test_dashboard_api.py tests/test_dialog_api.py -v
  ```

- [ ] **Step 6: Commit**
  ```bash
  git commit -m "refactor(api): 查询层 platform 用 normalize_platform 收口，删散落别名 (主题B Task3)"
  ```

---

## Task 4: 数据迁移脚本（raw_posts + post_comments）

**Files:** `scripts/migrate_platform_names.py`（新）、`tests/`（迁移测试）

- [ ] **Step 1: 新建迁移脚本**（幂等）
  ```python
  # 遍历 _SHORT_TO_FULL，UPDATE raw_posts / post_comments SET platform=full WHERE platform=short
  # 跑前打印 SELECT DISTINCT platform 核对，跑后再次核对
  ```
  - 复用项目 DB session 工厂（参考 models/database.py 或现有脚本风格）
  - 覆盖 `RawPost.platform` + `PostComment.platform` 两个表
  - 事务提交 + 幂等（无缩写时 no-op）

- [ ] **Step 2: 迁移测试**（建含 dy/douyin/xhs 混合的 fixture → 跑迁移 → 断言全名）
  - 可放入 `tests/test_platform_migration.py` 或 test_platforms.py

- [ ] **Step 3: 跑测试**
  ```bash
  pytest tests/test_platform_migration.py -v
  ```

- [ ] **Step 4: Commit**
  ```bash
  git commit -m "feat(scripts): platform 命名迁移脚本 raw_posts+post_comments 缩写→全名 (主题B Task4)"
  ```

> **执行迁移本身在 Task 7**（需服务在线 + 用户知情），Task 4 只交付脚本+测试。

---

## Task 5: 调度/分析/strategy 引用常量

**Files:** `pipeline/scheduler.py`、`pipeline/analysis/batch_runner.py`、`pipeline/collectors/platform_strategy.py`

- [ ] **Step 1: scheduler.py**
  - 472 `social_platforms = [...]` → `list(SOCIAL_PLATFORMS)`
  - 575 `plat_full = {...}.get(plat, plat)` → `normalize_platform(plat)`
  - 594-597 中文标签字典 → 用 `platform_label()` 或保留但引用常量 key

- [ ] **Step 2: batch_runner.py:20-23** 平台配置字典 key 引用常量

- [ ] **Step 3: platform_strategy.py** 13-16 `_FULL_TO_SHORT`/映射引用 platforms 模块（避免重复定义）

- [ ] **Step 4: 跑测试**
  ```bash
  pytest tests/test_platform_strategy.py tests/test_scheduler.py tests/test_batch_runner.py -v
  ```

- [ ] **Step 5: Commit**
  ```bash
  git commit -m "refactor(pipeline): 调度/分析/strategy 引用 platforms 单一真理源 (主题B Task5)"
  ```

---

## Task 6: 前端 alias 简化

**Files:** `frontend/static/js/app.js`

> 依赖 Task 7 迁移执行后（数据全名）。迁移前数据仍有缩写，故此 task 在 Task 7 之后或保留 alias 作防御。

- [ ] **Step 1: filteredHotPosts（143-146）** 删 alias map（数据已是全名，tab 全名直接匹配）

- [ ] **Step 2: platformLabel（814-816）** 简化为全名→中文（缩写分支可删或保留防御）

- [ ] **Step 3: 手动核对** index.html posts select（272-278 全名 value）与后端一致

- [ ] **Step 4: Commit**
  ```bash
  git commit -m "refactor(frontend): 简化 platform alias，数据统一全名后无需兼容 (主题B Task6)"
  ```

---

## Task 7: 执行迁移 + 端到端验证

**前置:** FastAPI 服务可连 DB + 用户知情确认（改历史数据）。

- [ ] **Step 1: 迁移前核对**
  ```bash
  python scripts/migrate_platform_names.py --dry-run   # 打印 SELECT DISTINCT platform
  ```
  Expected：看到 xhs/wb/dy/ks 与全名并存（抖音可能 dy+douyin）。

- [ ] **Step 2: 执行迁移**
  ```bash
  python scripts/migrate_platform_names.py
  ```
  Expected：迁移后 DISTINCT 仅剩 xiaohongshu/weibo/douyin/kuaishou/news。

- [ ] **Step 3: 验证查询层**
  - `/posts?platform=douyin` 与 `/posts?platform=dy` 返回一致（normalize 生效）
  - `/platform-distribution` 无重复"抖音"

- [ ] **Step 4: 实采验证**（CDP/服务在线）：触发一次抖音采集 → 新数据 platform 全为 `douyin`（无 dy）

- [ ] **Step 5: 跑全量后端测试**
  ```bash
  pytest -x
  ```

- [ ] **Step 6: 记录验证结果**；无代码改动则无需 commit。

---

## 完成标准（spec §2）

- [ ] `pipeline/platforms.py` 为唯一 platform 真理源；新增平台只改此一处
- [ ] CdpCollector 写入全为规范全名；抖音 dy/douyin 混用消除
- [ ] DB 内 platform 仅存全名（迁移后）
- [ ] dashboard/dialog 查询用 normalize，无散落 `_PLATFORM_ALIASES`
- [ ] grep `xhs|dy|wb|ks`（缩写）在 pipeline/ 和 api/ 仅剩输入兼容分支（`in ("weibo","wb")`）或迁移脚本
- [ ] 全量 pytest GREEN

## Self-Review

（spec 覆盖：真理源§3.1 / 采集§3.2 / 迁移§3.3 / 查询§3.4 / 前端§3.5 全部落到 Task 1-6。迁移覆盖范围经 schemas.py 核实=raw_posts+post_comments 两表（AnalyzedPost 无 platform 列）。修正了 spec §1 端名对调笔误（top-posts 单向/posts 双向）。Task 7 迁移执行设 dry-run + 用户确认关卡。前端 Task 6 明确依赖迁移后。无 placeholder。）
