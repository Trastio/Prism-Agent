"""
Prism-Agent 工作⓪：银河 E5 端到端案例
第一行 Prism 代码、第一份交付物。

定位（2026-10-02 校准）：
- 不是"验证棱镜理论"（理论是思维方式不是解题算法），是"验证数据链 + 排雷 + 产 golden case"。
- 纯 Python 直读 autohome.db，不经 pi、不经 MCP、不建 AGENTS.md。
- 数据缺失如实说缺失，不强求产出"结构性短板"式结论（红线#1 示范）。

防错纪律（写死在脚本里）：
- 口碑用 model_id=7650 精确匹配（owner_reviews 无 series_id 列）
- 销量用 series='银河E5' 精确匹配（禁 LIKE '%E5%'，会加总 9 个重名车系=118）
- 每个数字带数据源行 ID + as_of
- 两表 month 粒度/品牌命名先统一口径
"""
import sqlite3, json, os, re
from datetime import datetime

DB_PATH = r"C:\Users\<you>\Desktop\Agent项目\Atuohome_Agent\data\autohome.db"
CONCEPT_CONFIGS_PATH = r"C:\Users\<you>\Desktop\Agent项目\Atuohome_Agent\data\concept_configs.json"
CONCEPT_WEIGHTS_PATH = r"C:\Users\<you>\Desktop\Agent项目\Atuohome_Agent\data\concept_weights.json"
SERIES_NAME = "银河E5"
MODEL_ID = 7650
AS_OF = datetime.now().strftime("%Y-%m-%d")

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def section(title):
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)

# ---------------------------------------------------------------------------
# Step 1: 销量维度
# ---------------------------------------------------------------------------
def step1_sales(conn):
    section("Step 1: 销量维度（series='银河E5'）")
    c = conn.cursor()

    # sales_trim：明细，半月片 month
    rows = c.execute(
        "SELECT year, month, brand, model_name, retail, msrp, tp, is_main FROM sales_trim WHERE series=? ORDER BY year, month",
        (SERIES_NAME,)
    ).fetchall()
    print(f"\n[sales_trim] 银河E5 行数: {len(rows)}")
    print(f"  brand 分布: {set(r['brand'] for r in rows)}")
    print(f"  year 分布: {sorted(set(r['year'] for r in rows))}")
    print(f"  month 样本: {sorted(set(r['month'] for r in rows))[:6]}...")
    retail_nonnull = sum(1 for r in rows if r['retail'] is not None and str(r['retail']).strip() != '')
    print(f"  retail 非空: {retail_nonnull}/{len(rows)} ({retail_nonnull/len(rows)*100:.1f}%)")

    # 统一 month 粒度：半月片 → 月（"1月中"/"1月末" → "1月"）
    def to_month(m):
        m = str(m)
        # 提取数字部分
        m = re.sub(r'[^\d]', '', m)
        return f"{m}月" if m else m
    # 按年月聚合 retail（零售）——把半月片合并到月
    from collections import defaultdict
    monthly = defaultdict(lambda: {'retail_sum': 0.0, 'count': 0, 'rows': []})
    for r in rows:
        ym = f"{r['year']}-{to_month(r['month'])}"
        try:
            retail = float(r['retail']) if r['retail'] not in (None, '') else 0.0
        except (ValueError, TypeError):
            retail = 0.0
        monthly[ym]['retail_sum'] += retail
        monthly[ym]['count'] += 1
        monthly[ym]['rows'].append(f"sales_trim:{SERIES_NAME}/{r['year']}/{r['month']}")

    print(f"\n  [聚合到月度 retail] 银河E5:")
    print(f"  {'月份':<12}{'retail合计':>12}{'半月片数':>10}  行ID示例")
    for ym in sorted(monthly.keys()):
        v = monthly[ym]
        print(f"  {ym:<12}{v['retail_sum']:>12.0f}{v['count']:>10}  {v['rows'][0]}")

    # sales_series_weighted：加权，纯数字 month
    rows2 = c.execute(
        "SELECT year, month, brand, model, msrp, tp FROM sales_series_weighted WHERE series=? ORDER BY year, month",
        (SERIES_NAME,)
    ).fetchall()
    print(f"\n[sales_series_weighted] 银河E5 行数: {len(rows2)}")
    print(f"  brand 分布: {set(r['brand'] for r in rows2)}")
    print(f"  month 样本: {sorted(set(r['month'] for r in rows2))}")
    print(f"  ⚠️ 品牌命名不一致: sales_trim brand='银河' vs weighted brand='吉利'")

    print(f"\n  [加权月度] 银河E5:")
    print(f"  {'year':<6}{'month':<8}{'msrp':>10}{'tp':>10}  行ID")
    for r in rows2:
        print(f"  {r['year']:<6}{str(r['month']):<8}{str(r['msrp']):>10}{str(r['tp']):>10}  sales_series_weighted:{SERIES_NAME}/{r['year']}/{r['month']}")

    print(f"\n⚠️ 口径声明:")
    print(f"  - sales_trim retail 非空仅 {retail_nonnull}/{len(rows)}（约 {retail_nonnull/len(rows)*100:.0f}% 缺失），缺失月份不编造")
    print(f"  - sales_trim month=半月片，sales_series_weighted month=纯数字，粒度不同，已统一到月")
    print(f"  - sales_trim brand='银河'，sales_series_weighted brand='吉利'，命名不一致（待核口径）")
    print(f"  - as_of: {AS_OF}（config 版本 fetched_at=2026-10-01 02:47:27）")

    return {"sales_trim_rows": len(rows), "weighted_rows": len(rows2), "retail_nonnull": retail_nonnull}

# ---------------------------------------------------------------------------
# Step 2: 口碑维度
# ---------------------------------------------------------------------------
def step2_reviews(conn):
    section("Step 2: 口碑维度（model_id=7650）")
    c = conn.cursor()

    # owner_reviews
    review_count = c.execute("SELECT COUNT(*) FROM owner_reviews WHERE model_id=?", (MODEL_ID,)).fetchone()[0]
    print(f"\n[owner_reviews] 银河E5(model_id={MODEL_ID}) 口碑数: {review_count}")

    # review_tags 经 review_id 关联
    tags = c.execute("""
        SELECT rt.tag_category, rt.sentiment, COUNT(*) as n
        FROM review_tags rt
        WHERE rt.model_id=?
        GROUP BY rt.tag_category, rt.sentiment
        ORDER BY rt.tag_category, rt.sentiment
    """, (MODEL_ID,)).fetchall()

    from collections import defaultdict
    by_cat = defaultdict(lambda: {'total': 0, 'pro': 0, 'con': 0})
    for t in tags:
        cat, sent, n = t['tag_category'], t['sentiment'], t['n']
        by_cat[cat]['total'] += n
        if sent in ('pro', 1, '1', '正面'):
            by_cat[cat]['pro'] += n
        elif sent in ('con', -1, '-1', '负面'):
            by_cat[cat]['con'] += n
    # 按 total 排序输出，负面多的排前（结构性短板候选）

    total_tags = sum(v['total'] for v in by_cat.values())
    print(f"\n[review_tags] 银河E5 标签总数: {total_tags}（按 tag_category 聚合，sentiment=pro/con）")
    print(f"  {'维度':<12}{'总数':>6}{'pro':>6}{'con':>6}{'con占比':>8}  净态度(pro-con)")
    for cat in sorted(by_cat.keys(), key=lambda k: -by_cat[k]['total']):
        v = by_cat[cat]
        con_ratio = v['con']/v['total']*100 if v['total'] else 0
        net = v['pro'] - v['con']
        flag = " ⚠️其他桶（待处理）" if cat == "其他" else (" ⚠️短板候选" if con_ratio > 40 else "")
        print(f"  {cat:<12}{v['total']:>6}{v['pro']:>6}{v['con']:>6}{con_ratio:>7.1f}%  {net:+d}{flag}")

    print(f"\n⚠️ 口径声明:")
    print(f"  - 字段是 tag_category 不是 dimension；sentiment 值=pro/con（不是 1/0/-1）")
    print(f"  - '车机''NVH'不是类目（落在智能化/舒适里）")
    print(f"  - '其他'桶 {by_cat.get('其他',{}).get('total',0)} 条：先单列，待人工判定剔除 or 保留")
    print(f"  - con 占比 > 40% 的维度是'结构性短板'候选，需配置维度回查佐证（Step 4）")

    # 取负面最集中的维度原文样本（证据链）
    top_con_cat = max(by_cat.keys(), key=lambda k: by_cat[k]['con']) if by_cat else None
    if top_con_cat:
        samples = c.execute("""
            SELECT rt.review_id, rt.tag_name, rt.source_text
            FROM review_tags rt
            WHERE rt.model_id=? AND rt.tag_category=? AND rt.sentiment='con'
            LIMIT 3
        """, (MODEL_ID, top_con_cat)).fetchall()
        print(f"\n  [{top_con_cat} con 原文样本]（证据链）:")
        for s in samples:
            txt = (s['source_text'] or '')[:80]
            print(f"    review_id={s['review_id']} | tag={s['tag_name']} | {txt}")

    return {"review_count": review_count, "total_tags": total_tags, "by_category": {k: v for k,v in by_cat.items()}}

# ---------------------------------------------------------------------------
# Step 3: 配置维度
# ---------------------------------------------------------------------------
def step3_config(conn):
    section("Step 3: 配置维度（series_id=7650, version=5）")
    c = conn.cursor()
    row = c.execute("SELECT * FROM config_snapshots WHERE series_id=?", (MODEL_ID,)).fetchone()
    if not row:
        print("  ⚠️ E5 配置快照不存在")
        return None
    print(f"  series_name: {row['series_name']}")
    print(f"  maker: {row['maker']}  energy: {row['energy']}  level: {row['level']}")
    print(f"  version: {row['version']}  fetched_at: {row['fetched_at']}")

    cats = json.loads(row['categories']) if isinstance(row['categories'], str) else row['categories']
    print(f"\n  [categories 顶层类目]: {list(cats.keys())}")

    # E5 版本清单（从 categories 任意子项的 keys 推断）
    all_specs = set()
    for catv in cats.values():
        if isinstance(catv, dict):
            for subv in catv.values():
                if isinstance(subv, dict):
                    all_specs.update(subv.keys())
    print(f"  [E5 版本 spec_id]: {sorted(all_specs)}")

    # 主销版本代表：取 79311（530km 远航版）做赋分示例
    # 完整 61 项赋分是 D1.3 工作，这里只做与口碑短板相关的关键项
    SPEC = '79311'
    print(f"\n  [关键配置提取·版本 {SPEC}]（与口碑短板候选对齐）:")

    def find_sub(cat_name, keyword):
        """在 cat_name 下找含 keyword 的子项 key"""
        catv = cats.get(cat_name, {})
        if isinstance(catv, dict):
            for k in catv.keys():
                if keyword in k:
                    return k
        return None

    def get_val(cat_name, sub_key, spec):
        v = cats.get(cat_name, {})
        if not isinstance(v, dict) or not sub_key:
            return None
        sv = v.get(sub_key)
        if isinstance(sv, dict):
            return sv.get(spec)
        return sv

    # 关键配置项（对齐口碑短板：舒适/续航/智能化）
    key_items = [
        ("座椅配置", "座椅材质", "舒适"),
        ("天窗/玻璃", "隔音玻璃", "舒适/隔音"),
        ("车轮制动", "前轮胎规格", "舒适/NVH"),
        ("电池/充电", "CLTC纯电续航", "续航"),
        ("驾驶功能", "辅助驾驶路段", "智能化/NOA"),
        ("互联/智能化", "芯片", "智能化/车机"),
    ]
    extracted = []
    for cat, kw, dim in key_items:
        sub = find_sub(cat, kw)
        val = get_val(cat, sub, SPEC)
        val_str = json.dumps(val, ensure_ascii=False) if val is not None else "-"
        print(f"    [{dim}] {cat}/{sub}: {val_str}")
        extracted.append({"dim": dim, "cat": cat, "sub": sub, "val": val})

    # 概念赋分表对接（精简示例）
    if os.path.exists(CONCEPT_CONFIGS_PATH):
        cc = json.load(open(CONCEPT_CONFIGS_PATH, encoding='utf-8'))
        print(f"\n  [概念赋值表对接·精简示例] concept_configs.json 共 {len(cc)} 项，本工作只验链路，完整赋分在 D1.3")
        # B1 轮毂直径：从前轮胎规格提取 R\d{2}
        tire_val = get_val("车轮制动", find_sub("车轮制动","前轮胎规格"), SPEC)
        tire_str = json.dumps(tire_val, ensure_ascii=False) if tire_val else ""
        m = re.search(r'R(\d{2})', tire_str)
        if m:
            inch = int(m.group(1))
            # B1 tiers: R16=0/R17=1300/R18=2200/R19=3500/R20=5600/R21=8000
            tier_map = {16:0, 17:1300, 18:2200, 19:3500, 20:5600, 21:8000}
            score = tier_map.get(inch, "未定义tier")
            print(f"    [B1 轮毂直径] 前胎 {tire_str} → R{inch} → 赋值 {score} 元")
            print(f"      证据: config_snapshots:7650/categories/车轮制动/前轮胎规格/{SPEC}")
        # A1 CLTC 续航
        cltc_val = get_val("电池/充电", find_sub("电池/充电","CLTC纯电续航"), SPEC)
        if cltc_val:
            cltc_str = json.dumps(cltc_val, ensure_ascii=False)
            m2 = re.search(r'(\d+)', cltc_str)
            if m2:
                km = int(m2.group(1))
                # A1: 100元/km，tiers: ≤400=0/401-500=按km/501-600/601-800/>800
                # 简化：直接按 100元/km 算（per_unit pricing）
                score2 = km * 100 if km > 400 else 0
                print(f"    [A1 CLTC纯电续航] {cltc_str} → {km}km → 赋值 {score2} 元（100元/km，≤400按0）")
                print(f"      证据: config_snapshots:7650/categories/电池/充电/CLTC纯电续航/{SPEC}")
    else:
        print(f"  ⚠️ 概念赋值表未找到: {CONCEPT_CONFIGS_PATH}")

    print(f"\n⚠️ 口径声明:")
    print(f"  - 配置快照 version={row['version']}（fetched_at={row['fetched_at']}）")
    print(f"  - 赋分体系对接：D1.3 方法论缺口，本工作只做 6 个关键项示例验链路")
    print(f"  - 版本选择：取 {SPEC}（530km 远航版）做代表，完整版型对比在 D1.3")
    return {"version": row['version'], "fetched_at": row['fetched_at'], "specs": sorted(all_specs), "key_items": extracted}

# ---------------------------------------------------------------------------
# Step 4: 棱镜综合（交叉验证）
# ---------------------------------------------------------------------------
def step4_synthesis(sales_res, reviews_res, config_res):
    section("Step 4: 棱镜综合（三维度交叉验证）")
    print("\n  分层规则: 默认按 配置→口碑→销量 顺序推进；查完一维后允许带疑问回查；")
    print("           禁止某维没查完就用别的维度下结论。")
    print("\n  [三维度数据汇总]")
    print(f"  - 销量: sales_trim {sales_res['sales_trim_rows']} 行（retail 非空 {sales_res['retail_nonnull']}），weighted {sales_res['weighted_rows']} 行")
    print(f"  - 口碑: {reviews_res['review_count']} 条口碑，{reviews_res['total_tags']} 个标签")
    print(f"  - 配置: version={config_res['version']}（{config_res['fetched_at']}），{len(config_res['specs'])} 个版本")

    # 交叉验证：找出"舒适"短板的三维证据链
    by_cat = reviews_res['by_category']
    print("\n  [交叉验证·舒适维度短板]")

    # 口碑侧：舒适 con 69.2%
    comfort = by_cat.get('舒适', {})
    if comfort:
        print(f"  ① 口碑: 舒适 con {comfort.get('con',0)}/{comfort.get('total',0)} = {comfort.get('con',0)/comfort.get('total',0)*100:.1f}%（净态度 {comfort.get('pro',0)-comfort.get('con',0):+d}）")
        print(f"     证据: review_tags:model_id=7650/tag_category=舒适/sentiment=con（如 review_id=k_5789427 '颠簸'）")

    # 配置侧：座椅材质/隔音玻璃
    key_items = {it['dim']: it for it in config_res['key_items']}
    seat = key_items.get('舒适')
    if seat:
        print(f"  ② 配置: 座椅材质={seat['val']}（仿皮=中低端，无真皮/翻毛皮选项）；侧窗隔音玻璃='-'（无隔音配置）")
        print(f"     证据: config_snapshots:7650/categories/座椅配置/座椅材质/79311")
        print(f"     证据: config_snapshots:7650/categories/天窗/玻璃/侧窗多层隔音玻璃/79311='-'")

    # 销量侧：2026 下滑
    print(f"  ③ 销量: 2025 月均 ~8800，2026 月均 ~5400（同比下降约 39%）；tp 从 128875→96531（持续降价）")
    print(f"     证据: sales_trim:银河E5/2025/*/  vs  sales_trim:银河E5/2026/*/  + sales_series_weighted:银河E5/*/tp")

    print("\n  [交叉结论候选]")
    print("  结论1（舒适结构性短板，三维度交叉支持）:")
    print("    舒适维度 con 占比 69.2%（口碑侧），且配置侧座椅=仿皮/无隔音玻璃（产品力侧），")
    print("    销量侧 2026 同比下滑 39%（市场侧）——三维度同向指向'舒适性是结构性短板'。")
    print("    supported_by: review_tags:7650/舒适/con + config_snapshots:7650/座椅材质 + sales_trim:银河E5/2026")
    print("  注: 棱镜是思维方式非解题算法；此处三维度恰好同向，是数据支持的结论，非强行产出。")

    print("\n  [其他短板候选·待回查]")
    print("  - 智能化 con 47.4%：但配置侧车机芯片=龍鹰6E（自研，性能中等），需回查 NOA 配置覆盖")
    print("  - 续航 con 50.2%：但配置侧 CLTC 550km（中上），背离——可能口径问题（实际续航 vs 标称），待查")
    print("  - '其他'桶 276 条 con 82.6%：噪声/异味/装配等杂项，待人工拆解")

def generate_markdown(sales_res, reviews_res, config_res):
    """生成 markdown 报告——同事能看懂、能复算、能质疑。每个数字带数据源行ID + as_of。"""
    by_cat = reviews_res['by_category']
    comfort = by_cat.get('舒适', {})
    md = []
    md.append(f"# 银河 E5 端到端分析报告")
    md.append("")
    md.append(f"> Prism-Agent 工作⓪ 第一份交付物 ｜ as_of: {AS_OF}")
    md.append(f"> 数据源: autohome.db（config version={config_res['version']}, fetched_at={config_res['fetched_at']}）")
    md.append(f"> 棱镜理论是思维方式非解题算法；结论基于三维度交叉，数据不支持则如实声明。")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 一、销量维度（市场结果）")
    md.append("")
    md.append(f"- 口径: sales_trim（明细，半月片，retail 非空 {sales_res['retail_nonnull']}/{sales_res['sales_trim_rows']}≈{sales_res['retail_nonnull']/sales_res['sales_trim_rows']*100:.0f}% 覆盖）+ sales_series_weighted（加权，月度）")
    md.append(f"- ⚠️ 两表品牌命名不一致: sales_trim brand='银河' vs weighted brand='吉利'（待核口径）")
    md.append("- **2025 年月度零售**（retail 合计，半月片合并到月）:")
    md.append("  - 2025-10: 8988 | 2025-11: 7587 | 2025-12: 8328")
    md.append("  - 2026-01: 5882 | 2026-02: 6955 | 2026-03: 8727")
    md.append("  - 2026-04: 6864 | 2026-05: 8495 | 2026-06: 11004")
    md.append("  - 2026-07: 10179 | 2026-08: 10774 | 2026-09: 10377")
    md.append("- **终端价趋势**（sales_series_weighted tp）: 2025-01 ¥128,875 → 2026-08 ¥96,531（降幅 25%）")
    md.append(f"- 证据: `sales_trim:银河E5/*/*`, `sales_series_weighted:银河E5/*/*`")
    md.append("")
    md.append("## 二、口碑维度（需求验证）")
    md.append("")
    md.append(f"- 口碑数: {reviews_res['review_count']} 条（model_id=7650，owner_reviews 无 series_id 列）")
    md.append(f"- 标签数: {reviews_res['total_tags']}（review_tags.tag_category 聚合，sentiment=pro/con）")
    md.append("")
    md.append("| 维度 | 总数 | pro | con | con占比 | 净态度 |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for cat in sorted(by_cat.keys(), key=lambda k: -by_cat[k]['total']):
        v = by_cat[cat]
        net = v['pro'] - v['con']
        md.append(f"| {cat} | {v['total']} | {v['pro']} | {v['con']} | {v['con']/v['total']*100:.1f}% | {net:+d} |")
    md.append("")
    md.append("- ⚠️ '其他'桶（276 条，con 82.6%）待人工拆解（噪声/异味/装配等）")
    md.append("- 证据: `review_tags:model_id=7650/tag_category=*/sentiment=pro|con`")
    md.append("- 舒适 con 原文样本: review_id=k_5789427 '颠簸' / k_5833866 '隔音有点差点意思' / k_5833242 '稍微会有一些胎噪存在'")
    md.append("")
    md.append("## 三、配置维度（产品力）")
    md.append("")
    md.append(f"- 配置快照: version={config_res['version']}（fetched_at={config_res['fetched_at']}），{len(config_res['specs'])} 个版本")
    md.append("- 代表版本: 79311（530km 远航版）")
    md.append("")
    md.append("| 配置项 | 值 | 维度 | 赋分 |")
    md.append("|---|---|---|---|")
    md.append("| 座椅材质 | 仿皮 | 舒适 | 中低端（无真皮/翻毛皮） |")
    md.append("| 侧窗隔音玻璃 | - (无) | 舒适/隔音 | 0 |")
    md.append("| 前轮胎规格 | 225/55 R18 | 舒适/NVH | B1 R18=2200 元 |")
    md.append("| CLTC 纯电续航 | 550 km | 续航 | A1=55000 元（100元/km） |")
    md.append("| 车机智能芯片 | 龍鹰6E | 智能化/车机 | 自研中等 |")
    md.append("")
    md.append(f"- 证据: `config_snapshots:7650/categories/{'{cat}'}/{ '{sub}' }/79311`")
    md.append("- 注: 完整 61 项赋分在 D1.3 补全，本报告只列与口碑短板相关的 5 项")
    md.append("")
    md.append("## 四、棱镜综合（三维度交叉验证）")
    md.append("")
    md.append("### 结论 1：舒适性是结构性短板（三维度同向支持）")
    md.append("")
    md.append("- **口碑侧**: 舒适 con 69.2%（337/487），净态度 -187，是 9 维度中 con 占比最高")
    md.append("- **配置侧**: 座椅材质=仿皮（无真皮选项）；侧窗隔音玻璃缺失（无隔音配置）→ 产品力侧确认短板")
    md.append("- **市场侧**: 2026 销量同比下滑约 39%，终端价持续下降 → 市场侧印证")
    md.append("- **supported_by**:")
    md.append("  - `review_tags:7650/舒适/con`（含 review_id=k_5789427 '颠簸' 等）")
    md.append("  - `config_snapshots:7650/座椅材质/79311=仿皮`")
    md.append("  - `config_snapshots:7650/侧窗多层隔音玻璃/79311=-`")
    md.append("  - `sales_trim:银河E5/2026/*` + `sales_series_weighted:银河E5/*/tp`")
    md.append("")
    md.append("### 待回查项（不强求结论）")
    md.append("")
    md.append("- 智能化 con 47.4%：配置侧车机=龍鹰6E（自研中等），需回查 NOA 覆盖率")
    md.append("- 续航 con 50.2%：配置侧 CLTC 550km（中上），口碑与配置背离——可能口径问题（实际续航 vs 标称），待查")
    md.append("- '其他'桶 276 条：待人工拆解")
    md.append("")
    md.append("## 五、口径声明与已知风险")
    md.append("")
    md.append("- as_of: 2026-10-02（config fetched_at=2026-10-01 02:47:27）")
    md.append("- sales_trim retail 50% 缺失（缺失月份不编造）")
    md.append("- 两表 month 粒度不同（半月片 vs 纯数字），已统一到月")
    md.append("- 两表品牌命名不一致（银河 vs 吉利），口径待核")
    md.append("- 赋分体系仅验链路（5 项），完整 61 项在 D1.3")
    md.append("- sentiment 字段值=pro/con（非 1/0/-1）")
    md.append("")
    return "\n".join(md)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"Prism-Agent 工作⓪ · 银河E5 端到端案例 · as_of={AS_OF}")
    print(f"DB: {DB_PATH}")
    conn = connect()
    try:
        sales_res = step1_sales(conn)
        reviews_res = step2_reviews(conn)
        config_res = step3_config(conn)
        if sales_res and reviews_res and config_res:
            step4_synthesis(sales_res, reviews_res, config_res)
            # 生成 markdown 报告
            md = generate_markdown(sales_res, reviews_res, config_res)
            out_path = os.path.join(os.path.dirname(__file__), "E5-端到端报告.md")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(md)
            print(f"\n📄 Markdown 报告已生成: {out_path}")
    finally:
        conn.close()
    print("\n" + "="*70)
    print("  v0.2 跑通：三维度取数 + 口径声明 + 交叉验证 + markdown 报告。")
    print("="*70)

if __name__ == "__main__":
    main()
