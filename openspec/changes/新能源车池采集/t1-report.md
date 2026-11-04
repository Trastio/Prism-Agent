# T1 报告 · 名单生成器 + ID 绑定器

日期：2026-10-16 晚 · 施工：fork 子代理 · 运行环境：Anaconda 主 python（见偏差 1）
交付物：`prism-dashboards/scripts/gen_nev_pool.py`、`prism-dashboards/tests/test_gen_nev_pool.py`（27 用例）、`prism-dashboards/data/nev_pool.json`（+自动轮转的 `.prev`）、本报告。

## 1. 做了什么

- **生成器**：sales_trim → 动态窗口 → §3.1 过滤 → 车系聚合（中位价≤25 万）→ 双断言 → tier 分层 → ID 绑定（含缓存/共壳检测/价带守卫/壳提示）→ `data/nev_pool.json`。对 autohome.db **只读**（sqlite `mode=ro`），唯一写动作是 json 输出与 `.prev` 轮转。
- **窗口动态取**：最新 3 个**有零售**的月末批，无硬编码年月。本次取 2026 年 6/7/8 月末；**2026-9月末批（5000 行）零售全空被跳过**并记录在 `window.skipped_empty_retail`（与"月末批零售滞后"实况一致；CAM 补齐 9 月末零售后重跑即自动滚入）。若不跳过，窗口退化为 7-8 两个月零售，盘子 289→285、深采 3000 门槛失真。
- **双断言**（fail-closed 不出文件）：能源构成（纯电/插混/增程三类>0 且合计=盘子）+ 盘子环比（读旧件，>±10% 拦截，`--force` 豁免留痕；首轮无旧件 skip 注明）。
- **ID 绑定**（红线#6）：`build_series_index` 精确名（去空格+casefold，含品牌名+车系名形态）→ `search_series` 兜底（≥1s/次限速）→ 歧义/未命中进 `manual_review`，**零子串绑定**。新增**价带一致性守卫**：唯一命中还须 CAM 中位价 ∈ 之家指导价带，不过→`price_mismatch` 人工复核并列同族候选；缓存复用项同样过检。
- **共壳检测**：绑定后按 series_id 反查，一 id 多 sales 名 → 全员降级 manual_review 并列 peers。
- **`--skip-binding`** 离线模式（绑定字段留空、tier 不判定）；**缓存**：重跑对已 exact/search 项直接复用（索引仍拉取一次做价带复核，无逐项出网）。

## 2. 实测计数（终态 nev_pool.json，2026-10-16 20:4x）

| 项 | 值 |
|---|---|
| 窗口 | 2026 年 6月末/7月末/8月末（跳过 9月末零售空批） |
| 行漏斗 | 窗口 15,586 行 → 合格 4,354 行（非在产 3,076 / 无零售 2,828 / 车型 1,316 / 能源 4,012） |
| 盘子 universe | **289**（超价剔除 177，无价剔除 0） |
| 能源构成断言 | ✅ 纯电 141 + 插混 106 + 增程 42 = 289（与方案 §1.1 逐数一致） |
| 盘子环比断言 | ✅ 首轮 skip(no_prev)；带绑定轮 prev=289 Δ=0.0 |
| **tier** | **existing=12 / deep=31 / longtail=78**（bound 合计 121）+ manual_review=168 |
| 绑定 | exact 124（首跑）；终态：复用 121 + 价带拦 3 + not_found 165；**绑定率 121/289=41.9%**，例外 100% 在案 |

**绑定正确性实证**：12 个 existing 车系绑定后本地口碑数与方案 §1.1 逐系吻合（元PLUS 2268 / 银河E5 1187 / 零跑B10 1027 / B01 954 / MG 4X 271 / 风云A9 265 / 风云A9L 2000 / 元UP 483 / 小米SU7 472 / 海狮05 EV 643 / 银河M7 315 / 铂智3X 149·并行试跑新增）。

## 3. 共壳检测结果

- **绑定项内**：0 共壳（精确名绑定不会把两个不同名 CAM 车系绑到同一 id）。
- **§3.3 已知共壳族全部现形**：秦PLUS DM-i/EV、银河星舰7 EM-i/EV、汉EV/汉DM-i、海豹06 DM-i/EV、宋Ultra EV/DM-I、海狮06 DM-i/EV 等——之家侧是**合并壳**（"秦PLUS" 5964、"银河星舰7" 7864、"汉" 5499 一壳多动力），CAM 按动力拆名 → 全部落 not_found + 壳提示（80/165 项带 `shell_hints`，去动力后缀后的精确名命中，**仅人审线索、绝不自动绑定**）。人工确认后这批将呈现为"一 id 两 sales 名"，共壳检测代码已就位。

## 4. manual_review 清单（168 项，明细在 nev_pool.json `.manual_review`）

| 模式 | 数量 | 例 |
|---|---|---|
| not_found·合并壳（动力后缀差） | 165 中 80 带壳提示 | 秦PLUS DM-i → hint 5964"秦PLUS"；星舰7 EM-i/EV → hint 7864 |
| not_found·品牌/字母转写 | 165 中 85 无提示 | ARCFOX αS5 vs 之家"极狐 阿尔法S5"(7327)；βS3 vs "极狐贝塔S3"(8190)；ID.与众06/08 索引与搜索均无（之家 grade 页缺失） |
| price_mismatch（价带守卫拦下） | 3 | **传祺E8 真错绑被拦**：CAM 插电 p50 23.28万 vs 之家同名燃油壳 7796（17.98万），真身=7329"传祺E8 PHEV"；银河A7 EV（p50 10.63万 < 价带 11.28-15.08万）、瑞风E4 同族待确认，候选 id 已列 |

**给主会话的下一步**：168 项人工确认（优先 deep 55 项，Tier by retail 暂定）；确认映射并入 nev_pool.json 缓存重跑生成器即可补齐绑定，无需改代码。

## 5. 与方案 §附A（77 快照）对账差异

- 盘子 289、能源构成 141/106/42、窗口 6-8月末：**完全一致**（§附A 复算通过）。
- 深采批口径：附A 77 = 月销>3000 且排除存量 22；我方 bound deep=31 + manual 暂定 deep=55（合计 86）差异来源：①not_found 项无法判 local 口碑数，`tier_by_retail` 是按零售的暂定分层（宋Ultra EV 等实为 existing）；②铂智3X 因并行 T3 试跑入库 149 条从 deep 转 existing；③deep 门槛（retail_3m>3000）两口径一致。
- 22 存量分析池全部在盘子内：12 绑定进 existing，10（零跑C11 增程/纯电、风云T11 CEM、海狮06 DM-i/EV、银河A7 EM-i、宋Ultra EV/DM-I、零跑D19 纯电/增程）因合并壳命名进 manual_review。

## 6. 偏差与说明

1. **`.venv` 不存在**：`prism-dashboards/.venv` 未建；改用 Anaconda 主 python（sqlalchemy 2.0.43 + pytest 8.4.2 齐全）。生成器库读取走 stdlib sqlite3（只读 URI），不依赖 sqlalchemy。
2. **窗口"零售空批跳过"规则**为本次实现补充（自检 Gap#1 收敛文案是"去重排序取 top3"字面口径，实测该字面口径遇 9月末零售未落会退化成 2 月零售窗口）；规则完全动态并在 `window.skipped_empty_retail` 留痕，如实报告。
3. **search 兜底 0 命中**：search_series 基于同一 grade 索引，凡精确名阶段未中者搜索亦无全等候选；兜底保留用于索引页部分失败场景。
4. **缓存复用时仍拉取一次索引**（价带守卫需要，否则传祺E8 式错绑会被缓存固化）；逐项零出网。
5. **铂智3X tier 漂移**（deep→existing）：并行 T3 试跑子代理 10 分钟内写入 149 条口碑，两次读数均属实，非缺陷。
6. 传祺E8 案例证明价带守卫必要：纯精确名匹配会静默把插电盘子绑到燃油壳。

## 7. 验证

- 单测 `tests/test_gen_nev_pool.py`：**27/27 绿**（过滤/窗口/断言/tier/绑定/共壳/缓存/价带守卫/壳提示/.prev 轮转，全不出网）；`tests/` 全量 **131/131 绿**。
- 实跑三连：`--skip-binding`（断言与计数验证）→ 带绑定（真实出网，限速 1s）→ 价带守卫版重生成（缓存复用 121 + 拦 3）。
- autohome.db 零写入（mode=ro 连接）；除两个新文件与 data/nev_pool.json/.prev 外零写入。
