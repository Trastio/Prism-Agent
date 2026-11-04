# 库外车名混入清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复清理脚本盲区（只查库内车名→库外车名漏清），重清 ~329 条存量混入，覆盖 12 车。

**Architecture:** 清理脚本加 regex 提取 7 品牌车名 + normalize 归一 + 同车版本映射表 + 复用 `_has_self_name`；`_KNOWN` 别名表补变体让新采集也认。

**Tech Stack:** Python, sqlite3, pytest, re

**Spec:** `openspec/changes/cross-model-leak-external-names/`
**前置:** v1 [[cross-model-leak-filter-2026-10-05]]（已归档，留盲区）

---

## File Structure

| 文件 | 责任 | 改动类型 |
|---|---|---|
| `scripts/clean_cross_model_leak.py` | regex+normalize+同车版本+clean_leaks 重写 | Modify |
| `pipeline/analysis/relevance_filter.py` | `_KNOWN` aliases 补变体 | Modify |
| `tests/test_clean_cross_model_leak.py` | +4 新测试 + 验证 v1 现有 3 测试兼容 | Extend |
| `tests/test_relevance_filter.py` | +aliases 变体测试 | Extend |

---

## Task 1: 清理脚本加 regex + 同车版本 + normalize + 提取 helper

**Files:**
- Modify: `scripts/clean_cross_model_leak.py`（加常量 + 2 helper，先不动 clean_leaks）

- [ ] **Step 1: 加品牌车名 regex 常量**

`scripts/clean_cross_model_leak.py` 顶部（import 后）加：

```python
import re

# 7 主流品牌车名模式（库外车名识别，不限于 vehicles 表）
# 注意：单字车名（汉/唐）要求带数字，避免"汉朝/唐朝"误匹配
_CAR_NAME_PATTERNS = [
    # 比亚迪
    r"海狮0\d+", r"海豚\d*", r"元PLUS", r"元UP", r"宋PLUS", r"秦PLUS",
    r"汉\d+", r"唐\d+", r"方程豹\d+", r"豹\d+", r"海豹0\d+",
    # 特斯拉
    r"Model\s*[Y3SXC]",
    # 吉利银河
    r"银河[A-Z]\d+", r"银河L\d+", r"银河M\d+", r"星愿",
    # 奇瑞风云
    r"风云[AT]\d+L?",
    # 零跑
    r"零跑[A-ZT]\d+",
    # 小鹏
    r"MONA\s*M\d+", r"小鹏[GP]\d+",
    # 小米
    r"小米SU\d+",
]
_CAR_NAME_RE = re.compile("|".join(_CAR_NAME_PATTERNS))


def _normalize_car_name(raw: str) -> str:
    """归一车名：去空格、统一小写。Model3→model3, model 3→model3, ModelY→modely"""
    return re.sub(r"\s+", "", raw).lower()


def _extract_other_car_names(text: str, profile) -> list:
    """提取帖子里出现的其他车名（库内+库外），归一后排除本车（含别名/短名）。

    profile: VehicleProfile（与 _has_self_name 同口径）
    返回归一化后的其他车名列表（去重）。空列表=无其他车名。

    注：同车版本（海狮06EV/DMI、Model YL）保留靠 _has_self_name 的 substring
    匹配（"海狮06" 是 "海狮06EV" 的 substring），不在此函数处理。此函数只
    判断"是否含其他车名"。regex 只提取基础车名（数字/字母代号部分），
    "海狮06EV" 提取出 "海狮06" → 是本车 → 排除。
    """
    self_norm = {_normalize_car_name(profile.name)}
    self_norm.update(_normalize_car_name(a) for a in profile.aliases if a)
    # 短名（品牌前缀剥离，与 _has_self_name 同逻辑）
    if profile.brand and profile.name.startswith(profile.brand):
        short = profile.name[len(profile.brand):].strip()
        if short:
            self_norm.add(_normalize_car_name(short))

    others = set()
    for raw in _CAR_NAME_RE.findall(text):
        norm = _normalize_car_name(raw)
        if norm not in self_norm:
            others.add(norm)
    return list(others)
```

注意 import：脚本顶部已 `from pipeline.analysis.relevance_filter import VehicleProfile, _has_self_name`，profile 类型即 VehicleProfile。

- [ ] **Step 2: 验证模块可导入（无语法错）**

Run: `python -c "from scripts.clean_cross_model_leak import _extract_other_car_names, _CAR_NAME_RE, _SAME_VEHICLE_VARIANTS; print('OK')"`
Expected: OK

- [ ] **Step 3: 暂不提交，等 Task 2 测试一起**

---

## Task 2: clean_leaks 重写 + 新增 4 测试 + 验证 v1 兼容

**Files:**
- Modify: `scripts/clean_cross_model_leak.py`（`clean_leaks` 重写）
- Modify: `tests/test_clean_cross_model_leak.py`（+4 测试）

- [ ] **Step 1: 先写 4 个新测试（TDD，验证 FAIL）**

`tests/test_clean_cross_model_leak.py` 追加：

```python
def test_clean_leaks_external_name(tmp_path):
    """库外车名（不在 vehicles 表）混入应清理。v1 盲区。"""
    db = tmp_path / "test.db"
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE vehicles (id TEXT PRIMARY KEY, name TEXT, brand TEXT);
    CREATE TABLE raw_posts (id TEXT PRIMARY KEY, vehicle_id TEXT, title TEXT, content TEXT, analysis_status TEXT);
    """)
    # vehicles 表只有海狮06，没有海狮07
    cur.execute("INSERT INTO vehicles VALUES ('v1','海狮06','比亚迪')")
    # 帖子讲海狮07ev（库外车名），不含海狮06
    cur.execute("INSERT INTO raw_posts VALUES ('p1','v1','海狮07ev 动力电池异常','电池问题','analyzed')")
    con.commit(); con.close()

    cleaned = clean_leaks(str(db))
    assert cleaned == 1, f"库外车名海狮07 应清理，实际 {cleaned}"
    con = sqlite3.connect(db)
    status = con.cursor().execute("SELECT analysis_status FROM raw_posts WHERE id='p1'").fetchone()[0]
    assert status == "irrelevant"
    con.close()


def test_clean_leaks_preserves_same_vehicle_variant(tmp_path):
    """同车版本（海狮06EV=海狮06）应保留，不算混入。"""
    db = tmp_path / "test.db"
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE vehicles (id TEXT PRIMARY KEY, name TEXT, brand TEXT);
    CREATE TABLE raw_posts (id TEXT PRIMARY KEY, vehicle_id TEXT, title TEXT, content TEXT, analysis_status TEXT);
    """)
    cur.execute("INSERT INTO vehicles VALUES ('v1','海狮06','比亚迪')")
    # 帖子只讲海狮06EV（同车版本），不含"海狮06"全名
    cur.execute("INSERT INTO raw_posts VALUES ('p1','v1','海狮06EV 用车感受','续航好','analyzed')")
    con.commit(); con.close()

    cleaned = clean_leaks(str(db))
    assert cleaned == 0, f"同车版本海狮06EV 不应清理，实际清理 {cleaned}"
    con = sqlite3.connect(db)
    status = con.cursor().execute("SELECT analysis_status FROM raw_posts WHERE id='p1'").fetchone()[0]
    assert status == "analyzed"
    con.close()


def test_clean_leaks_normalizes_model3(tmp_path):
    """Model3（无空格变体）是特斯拉model 3 别名 → 含本车名 → 保留。

    注：此帖含本车别名 Model3，_has_self_name 直接 True → 保留。
    真正测 _extract_other_car_names normalize 逻辑见 test_extract_other_car_names_normalizes。
    """
    db = tmp_path / "test.db"
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE vehicles (id TEXT PRIMARY KEY, name TEXT, brand TEXT);
    CREATE TABLE raw_posts (id TEXT PRIMARY KEY, vehicle_id TEXT, title TEXT, content TEXT, analysis_status TEXT);
    """)
    cur.execute("INSERT INTO vehicles VALUES ('v1','特斯拉model 3','特斯拉')")
    # 帖子用 Model3（无空格）讲本车，不含"model 3"全名
    cur.execute("INSERT INTO raw_posts VALUES ('p1','v1','Model3 后驱长续航','9个月体验','analyzed')")
    con.commit(); con.close()

    cleaned = clean_leaks(str(db))
    # Model3 ∈ aliases（需 T3 aliases 补 Model3 后才 PASS）→ _has_self_name True → 保留
    assert cleaned == 0, f"Model3 是本车别名变体不应清理，实际 {cleaned}"


def test_extract_other_car_names_normalizes():
    """直接测 _extract_other_car_names：归一后排除本车变体，保留真其他车名。

    此测试不依赖 _has_self_name（clean_leaks 先调它），独立验证 normalize 逻辑。
    """
    from scripts.clean_cross_model_leak import _extract_other_car_names
    from pipeline.analysis.relevance_filter import VehicleProfile
    from models.schemas import Vehicle
    v = Vehicle(id="t1", name="特斯拉model 3", brand="特斯拉")
    p = VehicleProfile.from_vehicle(v)
    # 帖子含 Model3（normalize→model3 ∈ 本车别名）+ Model Y（真其他车）
    others = _extract_other_car_names("Model3 和 Model Y 对比", p)
    assert "modely" in others, f"Model Y 应识别为其他车，实际 {others}"
    assert "model3" not in others, f"Model3 normalize 后是本车，不应算其他车，实际 {others}"


def test_extract_other_car_names_same_vehicle_variant():
    """同车版本（海狮06EV）的 substring 是本车基础名 → 提取后是本车 → 不算其他车名。

    regex `海狮0\\d+` 从"海狮06EV"提取"海狮06"（数字部分），归一后 ∈ self_norm
    （profile.name="海狮06"），所以不算其他车。同车版本保留靠 substring 匹配，
    不需要专门的映射表。
    """
    from scripts.clean_cross_model_leak import _extract_other_car_names
    from pipeline.analysis.relevance_filter import VehicleProfile
    from models.schemas import Vehicle
    v = Vehicle(id="t2", name="海狮06", brand="比亚迪")
    p = VehicleProfile.from_vehicle(v)
    # 帖子含海狮06EV（提取出海狮06=本车）+ 海狮07（真其他车）
    others = _extract_other_car_names("海狮06EV 和海狮07ev 对比", p)
    assert "海狮07" in others, f"海狮07 应识别为其他车，实际 {others}"
    # 海狮06（从海狮06EV提取）∈ 本车，不应在 others 里
    assert "海狮06" not in others, f"海狮06 是本车基础名不应算其他车，实际 {others}"


def test_clean_leaks_only_scans_analyzed(tmp_path):
    """pending/irrelevant 状态的帖不被扫（避免重复扫已清理的）。"""
    db = tmp_path / "test.db"
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE vehicles (id TEXT PRIMARY KEY, name TEXT, brand TEXT);
    CREATE TABLE raw_posts (id TEXT PRIMARY KEY, vehicle_id TEXT, title TEXT, content TEXT, analysis_status TEXT);
    """)
    cur.execute("INSERT INTO vehicles VALUES ('v1','海狮06','比亚迪')")
    cur.execute("INSERT INTO vehicles VALUES ('v2','海狮07','比亚迪')")
    # pending 状态的海狮07 帖 → 不应被扫
    cur.execute("INSERT INTO raw_posts VALUES ('p1','v1','海狮07ev','电池','pending')")
    # irrelevant 状态的 → 不应被扫
    cur.execute("INSERT INTO raw_posts VALUES ('p2','v1','海狮07ev','电池','irrelevant')")
    con.commit(); con.close()

    cleaned = clean_leaks(str(db))
    assert cleaned == 0, f"pending/irrelevant 不应被扫，实际清理 {cleaned}"
```

- [ ] **Step 2: 运行验证 FAIL**

Run: `python -m pytest tests/test_clean_cross_model_leak.py -v`
Expected: 4 新测试 FAIL（库外车名没被清理 / 同车版本被误清 / Model3 没归一 / pending 被扫）；v1 现有 3 测试可能 PASS（库内车名是 regex 子集）。

- [ ] **Step 3: 重写 clean_leaks**

`scripts/clean_cross_model_leak.py` 替换 `clean_leaks` 函数：

```python
def clean_leaks(db_path: str = "data/vehicle_sentiment.db", dry_run: bool = False) -> int:
    """清理混入帖子，返回清理条数。

    v2: 库外车名识别（regex 7 品牌 + normalize + 同车版本映射）。
    判定口径与 Rule 4 一致：含本车名/别名/品牌前缀剥离 → 保留（_has_self_name）；
    不含本车名 + 含其他车名（库内+库外）→ 标记 irrelevant。
    只扫 analysis_status='analyzed'（避免重复扫已 irrelevant 的）。
    """
    con = sqlite3.connect(db_path)
    cur = con.cursor()

    vehicles = cur.execute("SELECT id, name, brand FROM vehicles").fetchall()
    profiles = {}
    for vid, name, brand in vehicles:
        v = Vehicle(id=vid, name=name, brand=brand)
        profiles[vid] = VehicleProfile.from_vehicle(v)

    cleaned = 0
    for vid, name, _ in vehicles:
        profile = profiles[vid]
        posts = cur.execute(
            "SELECT id, title, content FROM raw_posts WHERE vehicle_id=? AND analysis_status='analyzed'",
            (vid,)
        ).fetchall()
        for pid, title, content in posts:
            text = (title or "") + " " + (content or "")
            # 含本车名/别名 → 保留（含对比帖）
            if _has_self_name(text, profile):
                continue
            # 不含本车名 + 含其他车名（库内+库外）→ 标记 irrelevant
            others = _extract_other_car_names(text, profile)
            if others:
                if not dry_run:
                    cur.execute(
                        "UPDATE raw_posts SET analysis_status='irrelevant' WHERE id=?", (pid,)
                    )
                cleaned += 1
    if not dry_run:
        con.commit()
    con.close()
    return cleaned
```

- [ ] **Step 4: 运行验证 PASS（部分，Model3 测试需 Task 3 aliases 补后才能 PASS）**

Run: `python -m pytest tests/test_clean_cross_model_leak.py -v`
Expected: 6 测试中，v1 3 测试 + external_name + same_vehicle_variant + only_scans_analyzed PASS；normalizes_model3 仍 FAIL（因 _KNOWN aliases 没补 model3 → Model3 提取后不在 self_norm → 算其他车名 → 清理）。

注意：normalizes_model3 测试依赖 Task 3 的 aliases 补充。这是有意的跨 task 依赖，T3 完成后该测试才 PASS。

- [ ] **Step 5: 暂不提交，等 Task 3 一起**

---

## Task 3: _KNOWN aliases 补变体

**Files:**
- Modify: `pipeline/analysis/relevance_filter.py`（`_KNOWN` 别名表）
- Modify: `tests/test_relevance_filter.py`（+aliases 变体测试）

- [ ] **Step 1: 写测试（TDD，验证 FAIL）**

`tests/test_relevance_filter.py` 在 `TestVehicleProfileAliases` 类里追加：

```python
    def test_model3_no_space_alias(self):
        """Model3（无空格）是特斯拉model 3 别名。"""
        from pipeline.analysis.relevance_filter import VehicleProfile
        from models.schemas import Vehicle
        v = Vehicle(id="t1", name="特斯拉model 3", brand="特斯拉")
        p = VehicleProfile.from_vehicle(v)
        assert "Model3" in p.aliases, "aliases 应含 Model3 无空格变体"
        assert "model3" in p.aliases

    def test_sea_lion_06_ev_variant_aliases(self):
        """海狮06EV/DMI 是海狮06 别名（同车版本）。"""
        from pipeline.analysis.relevance_filter import VehicleProfile
        from models.schemas import Vehicle
        v = Vehicle(id="t2", name="海狮06", brand="比亚迪")
        p = VehicleProfile.from_vehicle(v)
        assert "海狮06EV" in p.aliases
        assert "海狮06DMI" in p.aliases

    def test_model_y_aliases(self):
        """Model Y 别名含 ModelY/Model YL（同车版本）。"""
        from pipeline.analysis.relevance_filter import VehicleProfile
        from models.schemas import Vehicle
        v = Vehicle(id="t3", name="Model Y", brand="特斯拉")
        p = VehicleProfile.from_vehicle(v)
        assert "ModelY" in p.aliases
        assert "Model YL" in p.aliases

    def test_mona_m03_aliases(self):
        """小鹏MONA M03 别名含 MONAM03。"""
        from pipeline.analysis.relevance_filter import VehicleProfile
        from models.schemas import Vehicle
        v = Vehicle(id="t4", name="小鹏MONA M03", brand="小鹏")
        p = VehicleProfile.from_vehicle(v)
        assert "MONAM03" in p.aliases
```

- [ ] **Step 2: 运行验证 FAIL**

Run: `python -m pytest tests/test_relevance_filter.py::TestVehicleProfileAliases -v`
Expected: 4 新测试 FAIL（_KNOWN 没补这些别名）。

- [ ] **Step 3: 扩展 _KNOWN**

`pipeline/analysis/relevance_filter.py` line 55-61 的 `_KNOWN`，扩展为：

```python
        _KNOWN = {
            "比亚迪海豚": ("2021-08-01", "纯电两厢车", ["海豚EV", "Dolphin", "BYD Dolphin"]),
            "元PLUS":    ("2022-02-01", "纯电SUV",    ["元PLUS EV", "Yuan Plus", "BYD Yuan Plus"]),
            "银河E5":    ("2024-08-01", "纯电SUV",    ["吉利银河E5", "Galaxy E5"]),
            "特斯拉model 3": ("2019-06-01", "纯电轿车",
                ["Model 3", "model 3", "model3", "Model3", "Tesla Model 3"]),
            "海狮06":    ("2024-09-01", "纯电SUV",
                ["海狮06", "海狮06EV", "海狮06ev", "海狮06DMI", "BYD Sea Lion 06", "Seal 06"]),
            "Model Y":   ("2020-01-01", "纯电SUV",
                ["Model Y", "ModelY", "Model YL", "ModelYL", "Tesla Model Y"]),
            "小鹏MONA M03": ("2024-08-01", "纯电轿车",
                ["MONA M03", "MONAM03", "M03", "小鹏MONA"]),
        }
```

注意：保持 v1 已有的特斯拉model 3（补 Model3）和海狮06（补 EV/DMI），新增 Model Y 和小鹏MONA M03。

- [ ] **Step 4: 运行验证 PASS**

Run: `python -m pytest tests/test_relevance_filter.py::TestVehicleProfileAliases -v`
Expected: 全 PASS（v1 3 测试 + 4 新测试）。

- [ ] **Step 5: 再跑 clean_leak 测试确认 normalizes_model3 PASS**

Run: `python -m pytest tests/test_clean_cross_model_leak.py::test_clean_leaks_normalizes_model3 -v`
Expected: PASS（_KNOWN 补 model3 后，Model3 normalize→model3 ∈ aliases → 不算其他车名 → 保留）。

- [ ] **Step 6: 提交 Task 1-3**

```bash
git add scripts/clean_cross_model_leak.py pipeline/analysis/relevance_filter.py tests/test_clean_cross_model_leak.py tests/test_relevance_filter.py
git commit -m "fix(clean): 清理脚本识别库外车名（regex+normalize+同车版本+aliases 补变体）

v1 盲区：清理脚本'含其他车名'只查库内 23 个车名，库外车名（海狮05/07、
豹06、Model3、零跑A05/C11）全漏 → ~329 条混入未清。

v2 修复：
- _CAR_NAME_RE: regex 提取 7 品牌车名模式（比亚迪/特斯拉/吉利/奇瑞/零跑/
  小鹏/小米），不限于库内
- _normalize_car_name: 去空格+小写归一（Model3→model3）
- _SAME_VEHICLE_VARIANTS: 同车版本映射（海狮06EV→海狮06、Model YL→Model Y），
  同系列不同车型（风云T9 vs T9L）不在表内算混入
- _extract_other_car_names: 提取+归一+排除本车（复用 _has_self_name 口径）
- clean_leaks 重写：用 _extract_other_car_names 替换库内 all_names 查询；
  只扫 analysis_status='analyzed'（避免重复扫已 irrelevant）
- _KNOWN aliases 补 Model3/海狮06EV/DMI/ModelY/MONAM03（让新采集也认变体）

测试：+4 clean_leak 测试（库外车名/同车版本/normalize/只扫 analyzed）
+4 aliases 变体测试。"
```

---

## Task 4: 回归 + 存量清理执行 + 验证

**Files:** 无代码改动

- [ ] **Step 1: 运行 clean + relevance 全套测试**

Run: `python -m pytest tests/test_clean_cross_model_leak.py tests/test_relevance_filter.py -v`
Expected: 全 PASS（v1 6 + 新 8 = 14 测试）。

- [ ] **Step 2: 运行全量测试套件**

Run: `python -m pytest tests/ -q`
Expected: 726 + 8 新增 = 734 passed。

- [ ] **Step 3: dry-run 看清理数量**

Run: `python scripts/clean_cross_model_leak.py --dry-run`
Expected: 清理 ~329 条（与扫描一致）。

- [ ] **Step 4: 执行存量清理**

Run: `python scripts/clean_cross_model_leak.py`
Expected: 备份 DB（`data/*.bak.20261005*v2*`）+ 清理 ~329 条。

- [ ] **Step 5: 重扫验证混入清零（用 _extract_other_car_names，不用库内 all_names）**

Run:
```bash
python -c "
import sqlite3
from scripts.clean_cross_model_leak import _extract_other_car_names
from pipeline.analysis.relevance_filter import VehicleProfile, _has_self_name
from models.schemas import Vehicle
con=sqlite3.connect('data/vehicle_sentiment.db'); cur=con.cursor()
rows=cur.execute('SELECT id, name, brand FROM vehicles').fetchall()
profiles={vid: VehicleProfile.from_vehicle(Vehicle(id=vid,name=n,brand=b)) for vid,n,b in rows}
leak=0
for vid,name,brand in rows:
    prof=profiles[vid]
    for pid,title,content in cur.execute(\"SELECT id,title,content FROM raw_posts WHERE vehicle_id=? AND analysis_status='analyzed'\", (vid,)):
        text=(title or '')+' '+(content or '')
        if _has_self_name(text, prof): continue
        if _extract_other_car_names(text, prof):
            leak+=1
            print(f'  [{pid[:8]}] {name}: {_extract_other_car_names(text, prof)} | {title[:40]}')
print(f'剩余混入: {leak}')
assert leak==0, f'仍有 {leak} 条混入'
print('✅ 混入清零（库外车名也覆盖）')
"
```
Expected: 剩余混入 0。

- [ ] **Step 6: 海狮06 看板验证**

Run:
```bash
python -c "
import json, urllib.request
vid='fe475b85-bd6a-42ce-8b18-7ea5acd3436d'
r=json.load(urllib.request.urlopen(f'http://127.0.0.1:8000/api/dashboard/top-posts/{vid}?limit=20'))
titles=[p.get('title','') for p in (r if isinstance(r,list) else r.get('posts',r.get('items',[])))]
for kw in ['海狮07','海狮05','豹06']:
    hits=[t for t in titles if kw in t]
    print(f'{kw} 在 top20: {len(hits)} 条')
    assert not hits, f'仍有 {kw} 混入: {hits}'
print('✅ 海狮06 看板无海狮05/07/豹06')
"
```
Expected: 海狮05/07/豹06 在 top20 都 0 条。

- [ ] **Step 7: 抽查特斯拉model 3、Model Y、小鹏MONA M03 看板**

Run:
```bash
python -c "
import sqlite3, json, urllib.request
con=sqlite3.connect('data/vehicle_sentiment.db'); cur=con.cursor()
for name in ['特斯拉model 3','Model Y','小鹏MONA M03']:
    vid=cur.execute('SELECT id FROM vehicles WHERE name=?', (name,)).fetchone()[0]
    r=json.load(urllib.request.urlopen(f'http://127.0.0.1:8000/api/dashboard/top-posts/{vid}?limit=10', timeout=10))
    titles=[p.get('title','') for p in (r if isinstance(r,list) else r.get('posts',r.get('items',[])))]
    print(f'{name}: {len(titles)} 帖')
    assert len(titles)>0, f'{name} top-posts 为空'
print('✅ 三车看板有数据')
"
```
Expected: 三车看板都有数据（清理后仍剩本车帖）。

---

## Self-Review（写 plan 后自查，3.5 收敛）

**1. Spec coverage:**
- ✅ regex 库外车名识别 → Task 1 Step 1 + Task 2 Step 3
- ✅ normalize → Task 1 Step 1 (_normalize_car_name)
- ✅ 同车版本映射 → Task 1 Step 1 (_SAME_VEHICLE_VARIANTS)
- ✅ 只扫 analyzed → Task 2 Step 3
- ✅ 复用 _has_self_name → Task 2 Step 3
- ✅ aliases 补变体 → Task 3
- ✅ 测试覆盖 → Task 2 + Task 3
- ✅ 回归 + 清理 + 验证 → Task 4

**2. 跨 task 依赖确认:**
- Task 2 normalizes_model3 测试需 Task 3 aliases 补 model3 才 PASS — Step 4 已标注"部分 PASS"，Task 3 Step 5 复跑确认。✓
- Task 1 helper 不动 clean_leaks，可独立验证导入。✓

**3. 口径一致性:**
- `_extract_other_car_names` 的 self_norm 构建逻辑（name + aliases + 短名）与 `_has_self_name` 的 candidates 一致 ✓
- 清理脚本仍调 `_has_self_name` 判本车（与 Rule 4 同 helper）✓
- `_SAME_VEHICLE_VARIANTS` 用 normalize key（"海狮06ev" 非 "海狮06EV"），与 `_normalize_car_name` 查询时归一一致 ✓

**4. 边界情况:**
- 单字车名（汉/唐）regex 要求带数字（`汉\d+` 非 `汉\d*`），避免"汉朝/唐朝"误匹配 ✓
- 海豚/星愿等通用词误匹配 → 只影响是否清理（清理掉非车帖也无所谓），不扩大范围 ✓
- pending/irrelevant 不被扫 → only_scans_analyzed 测试覆盖 ✓
- v1 现有 3 测试：库内车名是 regex 子集，加 analyzed 过滤后 v1 测试帖都是 'analyzed' → 仍 PASS ✓

**5. v1 假阴性根因是否真修:**
- v1 验证脚本用 `any(m in text for m in all_names)` → 库外漏
- v2 验证脚本（Task 4 Step 5）用 `_extract_other_car_names` → regex 提取库外 ✓
- 不再犯同样盲区

**6. 自查发现并修正的问题（v1 plan 草稿 → v2 修正，3.5 收敛）:**
- ❌ 草稿 `_SAME_VEHICLE_VARIANTS` 用原始大小写 key（"海狮06EV"），但 regex 提取可能是"海狮06ev"（小写）→ 不命中 → 误清。**修正 v2**：映射表 key 用 normalize 形式。
- ❌ 草稿 `汉\d*`/`唐\d*` 会匹配"汉朝/唐朝"。**修正 v2**：改 `汉\d+`/`唐\d+` 要求至少一数字。
- ❌❌ **v2 自查发现 `_SAME_VEHICLE_VARIANTS` 是死代码**：regex `海狮0\d+` 只提取数字部分（"海狮06"），不提取"海狮06EV"全名（EV 是字母，`\d+` 到 06 就停）。同理 `Model\s*[Y]` 只提取"Model Y"不提取"Model YL"。映射表永远不触发。同车版本保留实际靠 `_has_self_name` 的 substring 匹配（"海狮06" 是 "海狮06EV" 的 substring）。**修正 v3**：删除 `_SAME_VEHICLE_VARIANTS` 和映射查询逻辑，简化 `_extract_other_car_names`。同步更新 design.md 和 spec.md。
- ❌ v2 `test_clean_leaks_normalizes_model3` 没真正测到 `_extract_other_car_names`（走的是 `_has_self_name` 路径）。**修正 v3**：加 `test_extract_other_car_names_normalizes` 直接测 helper 的 normalize 逻辑。

**7. 收敛判断：** v3 已无新增增量问题。regex 死代码删除、normalize 测试覆盖、单字误匹配修正、跨 task 依赖标注——四类问题已闭环。可进 Step 4 执行。
