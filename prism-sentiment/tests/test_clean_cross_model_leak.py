"""Tests: 存量混入帖子清理脚本。"""
import sqlite3
from pathlib import Path
from scripts.clean_cross_model_leak import clean_leaks


def test_clean_leaks_marks_irrelevant(tmp_path):
    """混入帖子（不含本车名+含其他车名）应被标记 irrelevant。"""
    db = tmp_path / "test.db"
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE vehicles (id TEXT PRIMARY KEY, name TEXT, brand TEXT);
    CREATE TABLE raw_posts (id TEXT PRIMARY KEY, vehicle_id TEXT, title TEXT, content TEXT, analysis_status TEXT);
    """)
    cur.execute("INSERT INTO vehicles VALUES ('v1','海狮06','比亚迪')")
    cur.execute("INSERT INTO vehicles VALUES ('v2','海狮07','比亚迪')")
    cur.execute("INSERT INTO raw_posts VALUES ('p1','v1','海狮06测评','续航好','analyzed')")
    cur.execute("INSERT INTO raw_posts VALUES ('p2','v1','海狮07ev','电池异常','analyzed')")
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


def test_clean_leaks_preserves_alias_only_comparison(tmp_path):
    """用别名（非全名）提及本车 + 含其他车名 → 保留（与 Rule 4 _has_self_name 口径一致）。"""
    db = tmp_path / "test.db"
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE vehicles (id TEXT PRIMARY KEY, name TEXT, brand TEXT);
    CREATE TABLE raw_posts (id TEXT PRIMARY KEY, vehicle_id TEXT, title TEXT, content TEXT, analysis_status TEXT);
    """)
    # 特斯拉 model 3 别名含 "Model 3"
    cur.execute("INSERT INTO vehicles VALUES ('v1','特斯拉model 3','特斯拉')")
    cur.execute("INSERT INTO vehicles VALUES ('v2','海狮06','比亚迪')")
    # 帖子用别名 "Model 3" + 其他车名 "海狮06" → 应保留
    cur.execute("INSERT INTO raw_posts VALUES ('p1','v1','Model 3 vs 海狮06','对比测试','analyzed')")
    con.commit()
    con.close()

    cleaned = clean_leaks(str(db))
    assert cleaned == 0, "别名提及本车的对比帖不应被清理"

    con = sqlite3.connect(db)
    cur = con.cursor()
    status = cur.execute("SELECT analysis_status FROM raw_posts WHERE id='p1'").fetchone()[0]
    assert status == "analyzed"
    con.close()


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
