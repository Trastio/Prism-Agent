# 同品牌不同车型混入过滤 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 relevance_filter 让同品牌不同车型帖子（如海狮07→海狮06）被过滤，保留竞品对比帖，清理 310 条存量混入。

**Architecture:** Rule engine Rule 4 加"本车名必含"校验（不含本车名不 PASS）+ LLM prompt 加"同品牌不同车型"排除规则 + 别名表补充 + 存量软删除脚本。

**Tech Stack:** Python, SQLAlchemy 2.0 async, pytest, sqlite3

**Spec:** `docs/superpowers/specs/2026-10-05-cross-model-leak-filter-design.md`

---

## File Structure

| 文件 | 责任 | 改动类型 |
|---|---|---|
| `pipeline/analysis/relevance_filter.py` | Rule 4 + LLM prompt + 别名表 | Modify |
| `tests/test_relevance_filter.py` | 新增 4 测试 + 更新 2 现有测试 | Extend |
| `scripts/clean_cross_model_leak.py` | 存量软删除脚本 | Create |
| `tests/test_clean_cross_model_leak.py` | 脚本测试 | Create |

---

## Task 1: Rule engine 加"本车名必含"校验 + 更新现有测试

**Files:**
- Modify: `pipeline/analysis/relevance_filter.py:140-142`（Rule 4）
- Modify: `tests/test_relevance_filter.py:70-73`（更新 test_pass_charging_keyword）

- [x] **Step 1: 更新现有测试 `test_pass_charging_keyword` 反映新规则**

`tests/test_relevance_filter.py` line 70-73，现状帖子不含车名"海豚"只含"充电"就 PASS。新规则下不含车名应进 LIMBO。改为：

```python
def test_pass_charging_keyword(self):
    # Rule 4 新规则：含本车名 + 汽车语境词 → PASS
    post = {"title": "海豚充电体验", "content": "快充速度不错", "url": "",
            "published_at": date(2025, 5, 1), "platform": "wb"}
    assert self.filter.check(post, self.profile) == Relevance.PASS

def test_limbo_car_context_without_self_name(self):
    # Rule 4 新规则：不含本车名但有汽车语境词 → LIMBO（交 LLM 判断）
    post = {"title": "充电体验", "content": "快充速度不错", "url": "",
            "published_at": date(2025, 5, 1), "platform": "wb"}
    assert self.filter.check(post, self.profile) == Relevance.LIMBO
```

- [x] **Step 2: 运行测试验证 FAIL**

Run: `python -m pytest tests/test_relevance_filter.py::TestRuleEngine::test_limbo_car_context_without_self_name -v`
Expected: FAIL — 现状返回 PASS 而非 LIMBO。

- [x] **Step 3: 修改 Rule 4**

`pipeline/analysis/relevance_filter.py` line 140-142，现状：

```python
        # Rule 4: Contains car context keyword → PASS
        if _CAR_CONTEXT_RE.search(text):
            return Relevance.PASS
```

改为：

```python
        # Rule 4: 含本车名/别名 + 汽车语境词 → PASS（对比帖含本车名+其他车名也保留）
        # 不含本车名不直接 PASS，进 LLM 判断（防同品牌不同车型混入）
        has_self = profile.name in text or any(a in text for a in profile.aliases)
        if has_self and _CAR_CONTEXT_RE.search(text):
            return Relevance.PASS
```

- [x] **Step 4: 运行测试验证 PASS**

Run: `python -m pytest tests/test_relevance_filter.py::TestRuleEngine -v`
Expected: 全 PASS（含新增 test_limbo_car_context_without_self_name + 更新的 test_pass_charging_keyword）。

注意：`test_pass_car_context`（line 65-68）帖子标题含"海豚"→ 仍 PASS ✅。`test_pass_news_with_brand`/`test_pass_news_with_alias`（line 76-84）news 平台 Rule 5 兜底，不受 Rule 4 影响。

- [x] **Step 5: 提交**

```bash
git add pipeline/analysis/relevance_filter.py tests/test_relevance_filter.py
git commit -m "fix(filter): Rule4 加本车名必含校验防同品牌不同车型混入

含汽车语境词就 PASS 太宽（海狮07ev帖含'电池'就过）。改为 has_self + car_context
双条件。不含本车名进 LLM 判断。更新 test_pass_charging_keyword + 新增
test_limbo_car_context_without_self_name。"
```

---

## Task 2: LLM prompt 加"同品牌不同车型"排除规则

**Files:**
- Modify: `pipeline/analysis/relevance_filter.py:163-183`（_RELEVANCE_PROMPT）
- Test: `tests/test_relevance_filter.py`（新增 prompt 字符串测试）

- [x] **Step 1: 新增 prompt 字符串测试**

在 `tests/test_relevance_filter.py` 末尾追加：

```python
class TestLLMPromptCrossModel:
    def test_prompt_has_cross_model_rule(self):
        """LLM prompt 必须含'同品牌不同车型'排除规则。"""
        from pipeline.analysis.relevance_filter import _RELEVANCE_PROMPT
        assert "同品牌不同车型" in _RELEVANCE_PROMPT, "prompt 缺同品牌不同车型校验"
        assert "海狮07" in _RELEVANCE_PROMPT, "prompt 缺同品牌不同车型示例"

    def test_prompt_renders_vehicle_name(self):
        """prompt 渲染时 vehicle_name 应填入。"""
        from pipeline.analysis.relevance_filter import _RELEVANCE_PROMPT
        rendered = _RELEVANCE_PROMPT.format(
            vehicle_name="海狮06", brand="比亚迪", vehicle_type="纯电SUV",
            title="测试标题", content="测试内容",
        )
        assert "海狮06" in rendered
        assert "比亚迪" in rendered
```

- [x] **Step 2: 运行验证 FAIL**

Run: `python -m pytest tests/test_relevance_filter.py::TestLLMPromptCrossModel -v`
Expected: FAIL — prompt 不含"同品牌不同车型"。

- [x] **Step 3: 修改 _RELEVANCE_PROMPT**

`pipeline/analysis/relevance_filter.py` line 163-183，在撞名校验段后（"撞名误判示例"之后，"标题："之前）加：

```python
_RELEVANCE_PROMPT = """判断以下帖子是否与"{vehicle_name}"({brand}品牌{vehicle_type})相关。

相关：讨论该车型的性能、质量、购买、使用、售后、市场表现、竞品对比等
不相关：讨论其他同名事物、纯广告、配置参数页、图片集、无关短视频等

⚠ 撞名车特别校验（重要）：
车名若为通用词（如"星愿/银河/风云/元"等），帖文仅含车名字面是不够的——
必须检查是否有汽车语境词（提车/续航/充电/4S/经销商/试驾/油耗/保养/配置/
续航里程/购车/车主/落地价等）。无任何汽车语境词、却在讨论游戏/偶像/节目/
宝盒/超话/生日企划/大熊猫等的，判不相关。

撞名误判示例（这些含"星愿"但与车无关，应判 false）：
- "星宝！星愿节闪耀开启！趣味星图、免费礼物" → 游戏/活动，无汽车语境
- "idolish7超话 #偶像星愿# 【贺图】" → 偶像团体，无汽车语境
- "星愿宝盒 金纱礼宴动作套装预览" → 游戏道具，无汽车语境
- "为肖战守护星愿 十载风雨淬炼" → 粉丝生日企划，无汽车语境

⚠ 同品牌不同车型校验（重要）：
本车是"{vehicle_name}"({brand}品牌)。如果帖子单独讨论同品牌的其他车型
（如"{vehicle_name}"的兄弟车型/后续车型），而不涉及"{vehicle_name}"本身，
判不相关。例：本车="海狮06"，帖讲"海狮07ev 动力电池异常"→ 不相关。
但竞品对比帖（如"海狮06 vs Model Y"）判相关。

标题：{title}
内容摘要：{content}

只回复 JSON：{{"relevant": true/false, "confidence": 0.0-1.0}}"""
```

- [x] **Step 4: 运行验证 PASS**

Run: `python -m pytest tests/test_relevance_filter.py::TestLLMPromptCrossModel -v`
Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add pipeline/analysis/relevance_filter.py tests/test_relevance_filter.py
git commit -m "fix(filter): LLM prompt 加同品牌不同车型排除规则

prompt 只校验撞名（同名不同事物），没校验同品牌不同车型（海狮06 vs 海狮07）。
加'同品牌不同车型校验'段 + 海狮07 示例 + 竞品对比帖保留说明。"
```

---

## Task 3: 别名表精细化

**Files:**
- Modify: `pipeline/analysis/relevance_filter.py:55-59`（_KNOWN 别名表）
- Test: `tests/test_relevance_filter.py`（新增特斯拉 + 海狮06 测试）

- [x] **Step 1: 新增别名测试**

在 `tests/test_relevance_filter.py` 追加：

```python
class TestVehicleProfileAliases:
    def test_tesla_model_3_aliases(self):
        """特斯拉 model 3 别名含型号变体，'特斯拉'不是别名。"""
        from pipeline.analysis.relevance_filter import VehicleProfile
        from models.schemas import Vehicle
        v = Vehicle(id="t1", name="特斯拉model 3", brand="特斯拉")
        p = VehicleProfile.from_vehicle(v)
        assert "Model 3" in p.aliases
        assert "model 3" in p.aliases
        assert "特斯拉" not in p.aliases, "'特斯拉'不是 model 3 别名"

    def test_tesla_brand_only_not_pass(self):
        """只含'特斯拉'不含'model 3'→ 不 PASS（进 LIMBO）。"""
        from pipeline.analysis.relevance_filter import VehicleProfile, RuleBasedFilter, Relevance
        from models.schemas import Vehicle
        v = Vehicle(id="t1", name="特斯拉model 3", brand="特斯拉")
        p = VehicleProfile.from_vehicle(v)
        f = RuleBasedFilter()
        post = {"title": "特斯拉销量创新高", "content": "财报数据", "url": "",
                "published_at": date(2025, 5, 1), "platform": "xhs"}
        assert f.check(post, p) == Relevance.LIMBO

    def test_sea_lion_06_aliases(self):
        """海狮06 别名含型号变体。"""
        from pipeline.analysis.relevance_filter import VehicleProfile
        from models.schemas import Vehicle
        v = Vehicle(id="t2", name="海狮06", brand="比亚迪")
        p = VehicleProfile.from_vehicle(v)
        assert "海狮06" in p.aliases
```

- [x] **Step 2: 运行验证 FAIL**

Run: `python -m pytest tests/test_relevance_filter.py::TestVehicleProfileAliases -v`
Expected: FAIL — 特斯拉 model 3 不在 _KNOWN，走 fallback aliases=[name]（即 ["特斯拉model 3"]），不含 "Model 3"/"model 3"。

- [x] **Step 3: 扩展 _KNOWN 别名表**

`pipeline/analysis/relevance_filter.py` line 55-59，现状：

```python
        _KNOWN = {
            "比亚迪海豚": ("2021-08-01", "纯电两厢车", ["海豚EV", "Dolphin", "BYD Dolphin"]),
            "元PLUS":    ("2022-02-01", "纯电SUV",    ["元PLUS EV", "Yuan Plus", "BYD Yuan Plus"]),
            "银河E5":    ("2024-08-01", "纯电SUV",    ["吉利银河E5", "Galaxy E5"]),
        }
```

改为：

```python
        _KNOWN = {
            "比亚迪海豚": ("2021-08-01", "纯电两厢车", ["海豚EV", "Dolphin", "BYD Dolphin"]),
            "元PLUS":    ("2022-02-01", "纯电SUV",    ["元PLUS EV", "Yuan Plus", "BYD Yuan Plus"]),
            "银河E5":    ("2024-08-01", "纯电SUV",    ["吉利银河E5", "Galaxy E5"]),
            "特斯拉model 3": ("2019-06-01", "纯电轿车", ["Model 3", "model 3", "model3", "Tesla Model 3"]),
            "海狮06":    ("2024-09-01", "纯电SUV",    ["海狮06", "BYD Sea Lion 06", "Seal 06"]),
        }
```

注意："特斯拉"不在 model 3 别名里——必须含型号字样。

- [x] **Step 4: 运行验证 PASS**

Run: `python -m pytest tests/test_relevance_filter.py::TestVehicleProfileAliases -v`
Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add pipeline/analysis/relevance_filter.py tests/test_relevance_filter.py
git commit -m "fix(filter): 别名表补特斯拉model 3+海狮06（'特斯拉'不是别名）

_KNOWN 加 model 3（别名 Model 3/model 3/model3）+ 海狮06。'特斯拉'品牌词
不是 model 3 别名，只含品牌词不含型号 → 不 PASS。"
```

---

## Task 4: 存量清理脚本

**Files:**
- Create: `scripts/clean_cross_model_leak.py`
- Create: `tests/test_clean_cross_model_leak.py`

- [x] **Step 1: 写脚本测试**

`tests/test_clean_cross_model_leak.py`：

```python
"""Tests: 存量混入帖子清理脚本。"""
import sqlite3
from pathlib import Path
from scripts.clean_cross_model_leak import clean_leaks


def test_clean_leaks_marks_irrelevant(tmp_path):
    """混入帖子（不含本车名+含其他车名）应被标记 irrelevant。"""
    db = tmp_path / "test.db"
    con = sqlite3.connect(db)
    cur = con.cursor()
    # 建最小表
    cur.executescript("""
    CREATE TABLE vehicles (id TEXT PRIMARY KEY, name TEXT, brand TEXT);
    CREATE TABLE raw_posts (id TEXT PRIMARY KEY, vehicle_id TEXT, title TEXT, content TEXT, analysis_status TEXT);
    """)
    # 海狮06 + 海狮07 帖子混入
    cur.execute("INSERT INTO vehicles VALUES ('v1','海狮06','比亚迪')")
    cur.execute("INSERT INTO vehicles VALUES ('v2','海狮07','比亚迪')")
    # 帖1: 含本车名 → 保留
    cur.execute("INSERT INTO raw_posts VALUES ('p1','v1','海狮06测评','续航好','analyzed')")
    # 帖2: 不含本车名+含其他车名 → 标记 irrelevant
    cur.execute("INSERT INTO raw_posts VALUES ('p2','v1','海狮07ev','电池异常','analyzed')")
    # 帖3: 不含任何车名 → 保留（不处理）
    cur.execute("INSERT INTO raw_posts VALUES ('p3','v1','新能源汽车','市场分析','analyzed')")
    con.commit()
    con.close()

    cleaned = clean_leaks(str(db))
    assert cleaned == 1, f"应清理 1 条，实际 {cleaned}"

    con = sqlite3.connect(db)
    cur = con.cursor()
    status_p2 = cur.execute("SELECT analysis_status FROM raw_posts WHERE id='p2'").fetchone()[0]
    assert status_p2 == "irrelevant", f"p2 应标记 irrelevant，实际 {status_p2}"
    status_p1 = cur.execute("SELECT analysis_status FROM raw_posts WHERE id='p1'").fetchone()[0]
    assert status_p1 == "analyzed", "p1 含本车名不应被标记"
    con.close()


def test_clean_leaks_preserves_comparison_post(tmp_path):
    """对比帖（含本车名+其他车名）应保留。"""
    db = tmp_path / "test.db"
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE vehicles (id TEXT PRIMARY KEY, name TEXT, brand TEXT);
    CREATE TABLE raw_posts (id TEXT PRIMARY KEY, vehicle_id TEXT, title TEXT, content TEXT, analysis_status TEXT);
    """)
    cur.execute("INSERT INTO vehicles VALUES ('v1','海狮06','比亚迪')")
    cur.execute("INSERT INTO vehicles VALUES ('v2','Model Y','特斯拉')")
    # 对比帖：含本车名 + 其他车名 → 保留
    cur.execute("INSERT INTO raw_posts VALUES ('p1','v1','海狮06 vs Model Y','对比测试','analyzed')")
    con.commit()
    con.close()

    cleaned = clean_leaks(str(db))
    assert cleaned == 0, "对比帖不应被清理"

    con = sqlite3.connect(db)
    cur = con.cursor()
    status = cur.execute("SELECT analysis_status FROM raw_posts WHERE id='p1'").fetchone()[0]
    assert status == "analyzed"
    con.close()
```

- [x] **Step 2: 运行验证 FAIL**

Run: `python -m pytest tests/test_clean_cross_model_leak.py -v`
Expected: FAIL — `scripts.clean_cross_model_leak` 模块不存在。

- [x] **Step 3: 写清理脚本**

`scripts/clean_cross_model_leak.py`：

```python
"""清理同品牌不同车型混入帖子（存量软删除）。

扫描全库，将"不含本车名 + 含其他车名"的帖子 analysis_status 改为 "irrelevant"。
看板查询已带 RELEVANT_ONLY 过滤会自动排除。备份后执行。

用法：
    python scripts/clean_cross_model_leak.py [--dry-run] [--db PATH]
"""
import argparse
import os
import shutil
import sqlite3
from datetime import datetime


def clean_leaks(db_path: str = "data/vehicle_sentiment.db", dry_run: bool = False) -> int:
    """清理混入帖子，返回清理条数。"""
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # 取所有车型名
    vehicles = cur.execute("SELECT id, name FROM vehicles").fetchall()
    all_names = [name for _, name in vehicles]
    name_to_id = {name: vid for vid, name in vehicles}

    cleaned = 0
    for vid, name in vehicles:
        # 该车的所有帖子
        posts = cur.execute(
            "SELECT id, title, content FROM raw_posts WHERE vehicle_id=?", (vid,)
        ).fetchall()
        for pid, title, content in posts:
            text = (title or "") + " " + (content or "")
            # 含本车名 → 保留
            if name in text:
                continue
            # 不含本车名 + 含其他车名 → 标记 irrelevant
            has_other = any(m in text for m in all_names if m != name)
            if has_other:
                if not dry_run:
                    cur.execute(
                        "UPDATE raw_posts SET analysis_status='irrelevant' WHERE id=?", (pid,)
                    )
                cleaned += 1
    if not dry_run:
        con.commit()
    con.close()
    return cleaned


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计不执行")
    parser.add_argument("--db", default="data/vehicle_sentiment.db")
    args = parser.parse_args()

    # 备份
    if not args.dry_run:
        bak = f"{args.db}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        shutil.copy(args.db, bak)
        print(f"备份: {bak}")

    cleaned = clean_leaks(args.db, args.dry_run)
    print(f"{'[DRY-RUN] ' if args.dry_run else ''}清理混入帖子: {cleaned} 条")


if __name__ == "__main__":
    main()
```

- [x] **Step 4: 运行验证 PASS**

Run: `python -m pytest tests/test_clean_cross_model_leak.py -v`
Expected: PASS（2 测试）。

- [x] **Step 5: 提交**

```bash
git add scripts/clean_cross_model_leak.py tests/test_clean_cross_model_leak.py
git commit -m "feat: 存量混入帖子清理脚本（软删除 irrelevant）

扫描全库，不含本车名+含其他车名 → analysis_status='irrelevant'。
对比帖（含本车名+其他车名）保留。备份后执行，dry-run 模式支持。"
```

---

## Task 5: 回归 + 存量清理执行 + 验证

**Files:** 无代码改动

- [x] **Step 1: 运行 relevance_filter 全套测试**

Run: `python -m pytest tests/test_relevance_filter.py -v`
Expected: 全 PASS（原有 + 新增 8 测试）。

- [x] **Step 2: 运行全量测试套件**

Run: `python -m pytest tests/ -q`
Expected: 722 passed（717 基线 + 5 新增）。

- [x] **Step 3: dry-run 看清理数量**

Run: `python scripts/clean_cross_model_leak.py --dry-run`
Expected: 清理 ~310 条（与之前扫描一致）。

- [x] **Step 4: 执行存量清理**

Run: `python scripts/clean_cross_model_leak.py`
Expected: 备份 DB + 清理 ~310 条。

- [x] **Step 5: 重扫验证混入清零**

Run:
```bash
python -c "
import sqlite3
con=sqlite3.connect('data/vehicle_sentiment.db'); cur=con.cursor()
rows=cur.execute('SELECT id, name FROM vehicles').fetchall()
all_names=[r[1] for r in rows]
leak=0
for vid,name in rows:
    for pid,title,content in cur.execute('SELECT id,title,content FROM raw_posts WHERE vehicle_id=? AND analysis_status=\"analyzed\"', (vid,)):
        text=(title or '')+' '+(content or '')
        if name in text: continue
        if any(m in text for m in all_names if m!=name):
            leak+=1
print(f'剩余混入: {leak}')
assert leak==0, f'仍有 {leak} 条混入'
print('✅ 混入清零')
"
```
Expected: 剩余混入 0。

- [x] **Step 6: 海狮06 看板验证**

Run:
```bash
python -c "
import json, urllib.request
vid='fe475b85-bd6a-42ce-8b18-7ea5acd3436d'
r=json.load(urllib.request.urlopen(f'http://127.0.0.1:8000/api/dashboard/top-posts/{vid}?limit=10'))
titles=[p.get('title','') for p in r]
has_07=any('海狮07' in t for t in titles)
print('海狮06 热帖含海狮07:', has_07)
assert not has_07, '仍有海狮07 混入'
print('✅ 海狮06 看板无混入')
"
```
Expected: 海狮06 热帖无"海狮07"。

---

## Self-Review

**1. Spec coverage:**
- ✅ Rule engine 加本车名必含 → Task 1
- ✅ LLM prompt 加同品牌不同车型排除 → Task 2
- ✅ 别名表精细化（特斯拉 model 3）→ Task 3
- ✅ 存量软删除脚本 → Task 4
- ✅ 测试覆盖（5 新测试）→ Task 1-4 各自
- ✅ 回归 + 存量清理 + 验证 → Task 5

**2. Placeholder scan:** 无 TBD/TODO。所有测试代码完整。

**3. Type consistency:**
- `Relevance.PASS/LIMBO/REJECT` 枚举一致 ✓
- `VehicleProfile.from_vehicle` 返回类型一致 ✓
- `clean_leaks(db_path, dry_run) -> int` 签名一致 ✓
- 别名表 key 与 DB vehicle.name 一致（"特斯拉model 3"、"海狮06"）✓

**4. 现有测试影响分析：**
- `test_pass_car_context`（line 65-68）：标题"海豚测评"含"海豚"→ 仍 PASS ✅
- `test_pass_charging_keyword`（line 70-73）：原内容不含车名 → 改为含车名 ✅
- `test_pass_news_with_brand`/`test_pass_news_with_alias`（line 76-84）：news 平台走 Rule 5 兜底，不受 Rule 4 影响 ✅
- 其他测试：Rule 1/2/3 不受影响 ✅
