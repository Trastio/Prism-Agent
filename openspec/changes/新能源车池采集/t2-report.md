# T2 报告 · 底座批：壳+配置缺口补齐（backfill_pool_base）

日期：2026-10-16 · 执行：T2 施工子代理 · 脚本：`prism-dashboards/scripts/backfill_pool_base.py`（新文件）· 单测：`prism-dashboards/tests/test_backfill_pool_base.py`（16/16 绿）

## 1. 执行方式

1. dry-run 先行（只读缺口计算，未写库）→ live 主跑（`PRISM_COLLECT_LIVE=1`）→ 2 轮断点续跑（只重试缺配置项）；
2. 名单真值 `data/nev_pool.json`：绑定 269 项 / **唯一 series_id 224 个**（共壳重复 45 项，同 id 对多 sales 名）；全部缺口按唯一 id 计；
3. 补壳逐系 `get_series_summary` → INSERT `series_summaries`，请求间隔 1s；补配置走 `collect_snapshots(series_ids=缺失名单, metadata_map, max_age_days=None)`，delay=1s / concurrency=3；
4. 写冲突防护按单执行：engine 挂 `PRAGMA busy_timeout=30000`，locked 等 60s 重试 ≤10 次（本轮全程零 locked，与打标批并行无冲突）。

## 2. 跑前 / 跑后行数对账

| 表 | 跑前 | 跑后 | Δ | 说明 |
|---|---|---|---|---|
| series_summaries | 221 | **335** | **+114** | =缺壳名单 114，逐条 INSERT |
| config_snapshots | 251 | **353** | **+102** | =缺配置 105 − 3 持久失败 |
| owner_reviews | 21,845 | 21,845 | **0** | 本脚本不触碰 ✓ |
| review_tags | 57,774* | 59,014 | +1,240* | *并行打标批（T5 子代理）写入；本脚本零触碰 |

（*review_tags 跑前值取 live 主跑起点；T0 备份基线 56,246 → 打标批在 T2 执行窗口内持续写入。）

## 3. 缺口解析清单

**缺壳名单（114 系，已全部补齐）**：

```
  8171  钛7 纯电 / 钛7
  7807  比亚迪 海狮05 DM-i
  8190  ARCFOX βS3
  8510  至境E7
  7356  钛3
  8545  哈弗猛龙 Plus
  7327  ARCFOX αS5
  8469  埃安 N60
  8468  五菱星光L PHEV
  7696  BJ40增程
  8485  比亚迪 海豹08 EV / 比亚迪 海豹08 DM-i
  8586  长城H10 Hi4
  6903  丰田 bZ3
  8187  五菱星光730 EV / 五菱星光730 PHEV
  7899  悦意03
  7724  铂智7
  8459  日产 NX8 增程 / 日产 NX8 纯电
  7728  岚图知音
  8598  传祺向往E8 PHEV
  7125  ARCFOX αT5 / ARCFOX αT5 增程
  8203  红旗HS6 PHEV
  8243  日产 N6
  7935  日产 N7
  8543  欧拉5
  7673  红旗HS3 PHEV
  7713  丰田 bZ5
  5275  红旗H5 PHEV
  6369  smart精灵#1
  7298  哈弗猛龙
  7323  风神L7 纯电 / 风神L7
  5924  岚图Free
  8149  风神L8
  7574  宝骏悦也PLUS
  8669  领克Z20
  8723  坦克300L Hi4-T
  7099  启辰VX6
  8457  风行星海T5
  8651  大众ID.ERA 5S
  7741  宝骏云海 EV / 宝骏云海 PHEV
  7851  比亚迪 夏
  7150  哈弗枭龙MAX
  7832  蓝电E5 Plus
  5785  ID.4 CROZZ
  8429  ID.与众08
  7717  马自达 EZ-60 增程 / 马自达 EZ-60 纯电
  7705  红旗天工05
  8216  五菱星光560 PHEV / 五菱星光560 EV
  8100  至境L7 / 至境L7 EV
  7223  宝马 iX1
  5062  迈腾 PHEV
  7797  考拉S
  7456  eπ008 EV / eπ008 REEV
  8609  奕派M8 EV / 奕派M8 REEV
  8710  探岳L PHEV
  4904  帕萨特ePro
  6900  哈弗大狗PLUS PHEV
  7684  smart精灵#5 EHD
  7400  风行星海V9
  8431  星途EX7 增程 / 星途EX7 纯电
  4746  途观L ePro
  8205  尚界H5 增程 / 尚界H5 纯电
  7628  ID.与众06
  7245  红旗EH7
  5511  ID.4 X
  8544  博越REV
  7044  smart精灵#3
  2504  五菱星光 PHEV / 五菱星光 EV
  7520  铂智4X
  6506  瑞风E3
  8017  羿驰05
  8026  纳米06
  7977  比亚迪 海狮07 DM-i
  6913  红旗天工08
  7407  灵悉L
  7043  别克 E5
  7221  瑞风RF8 PHEV
  6851  比亚迪 海狮07 EV
  7924  大通 G50 混动
  8213  智趣烈马 REEV
  8214  锐胜M8 纯电 / 锐胜M8 增程
  6188  创维EV6
  7352  起亚 EV5
  7978  悦意07
  8103  EO 羿欧
  8745  星海V6 PLUS
  7704  红旗天工06
  7215  星途瑶光C-DM
  8600  星海V6
  8218  羿驰05S
  7275  沃尔沃 EX30
  7127  雅阁 e:PHEV
  7211  大家7 / 大家7 DMH
  6936  宝骏悦也
  5994  皓影 e:PHEV
  6686  创维HT-i
  7217  江淮 QX PHEV
  6413  凯翼炫界Pro EV
  7332  IQ傲歌
  7244  e:NS2 猎光
  7930  瑞风M3 PLUS PHEV
  7743  领裕 PHEV
  8043  示界06
  7104  启辰大V DD-i超混动
  6488  风行S60 EV
  6124  欧拉闪电猫
  5764  远志M1
  7744  领睿 PHEV
  7680  探索06 C-DM
  7252  e:NP2 极湃2
  7589  江淮X8 E家
  5892  本田 CR-V e:PHEV
  6633  雷霆 / 雷霆 增程
  6264  长安 UNI-K iDD
  8717  风神L8 PLUS
```

**缺配置名单（105 系，补齐 102，3 系例外见 §4）**：

```
  8433  零跑 A10
  7712  铂智3X
  8283  宝骏华境S
  8190  ARCFOX βS3
  8510  至境E7
  8545  哈弗猛龙 Plus
  7327  ARCFOX αS5
  8469  埃安 N60
  8468  五菱星光L PHEV
  7696  BJ40增程
  8485  比亚迪 海豹08 EV / 比亚迪 海豹08 DM-i
  8586  长城H10 Hi4
  6903  丰田 bZ3
  7899  悦意03
  7724  铂智7
  8459  日产 NX8 增程 / 日产 NX8 纯电
  7728  岚图知音
  8598  传祺向往E8 PHEV
  7125  ARCFOX αT5 / ARCFOX αT5 增程
  8203  红旗HS6 PHEV
  8243  日产 N6
  7935  日产 N7
  8543  欧拉5
  7673  红旗HS3 PHEV
  7713  丰田 bZ5
  5275  红旗H5 PHEV
  6369  smart精灵#1
  7298  哈弗猛龙
  7323  风神L7 纯电 / 风神L7
  5924  岚图Free
  8149  风神L8
  8669  领克Z20
  8723  坦克300L Hi4-T
  7099  启辰VX6
  8457  风行星海T5
  8651  大众ID.ERA 5S
  7150  哈弗枭龙MAX
  7832  蓝电E5 Plus
  5785  ID.4 CROZZ
  8429  ID.与众08
  7717  马自达 EZ-60 增程 / 马自达 EZ-60 纯电
  7705  红旗天工05
  8100  至境L7 / 至境L7 EV
  7223  宝马 iX1
  5062  迈腾 PHEV
  7797  考拉S
  7456  eπ008 EV / eπ008 REEV
  8609  奕派M8 EV / 奕派M8 REEV
  8710  探岳L PHEV
  4904  帕萨特ePro
  6900  哈弗大狗PLUS PHEV
  7684  smart精灵#5 EHD
  7400  风行星海V9
  8431  星途EX7 增程 / 星途EX7 纯电
  4746  途观L ePro
  8205  尚界H5 增程 / 尚界H5 纯电
  7628  ID.与众06
  7245  红旗EH7
  5511  ID.4 X
  8544  博越REV
  7044  smart精灵#3
  2504  五菱星光 PHEV / 五菱星光 EV
  7520  铂智4X
  6506  瑞风E3
  8017  羿驰05
  8026  纳米06
  6913  红旗天工08
  7407  灵悉L
  7043  别克 E5
  7221  瑞风RF8 PHEV
  6851  比亚迪 海狮07 EV
  7924  大通 G50 混动
  8213  智趣烈马 REEV
  8214  锐胜M8 纯电 / 锐胜M8 增程
  6188  创维EV6
  7352  起亚 EV5
  7978  悦意07
  8103  EO 羿欧
  8745  星海V6 PLUS
  7704  红旗天工06
  8600  星海V6
  8218  羿驰05S
  7275  沃尔沃 EX30
  7127  雅阁 e:PHEV
  7211  大家7 / 大家7 DMH
  5994  皓影 e:PHEV
  6686  创维HT-i
  7217  江淮 QX PHEV
  7332  IQ傲歌
  7244  e:NS2 猎光
  7930  瑞风M3 PLUS PHEV
  7743  领裕 PHEV
  8043  示界06
  7104  启辰大V DD-i超混动
  6488  风行S60 EV
  6124  欧拉闪电猫
  5764  远志M1
  7744  领睿 PHEV
  7680  探索06 C-DM
  7252  e:NP2 极湃2
  7589  江淮X8 E家
  5892  本田 CR-V e:PHEV
  6633  雷霆 / 雷霆 增程
  6264  长安 UNI-K iDD
  8717  风神L8 PLUS
```

## 4. 失败清单（3 系持久例外，如实声明）

| series_id | pool sales 名 | 失败原因 | 重试 |
|---|---|---|---|
| 8598 | 传祺向往E8 PHEV | `no categories`（之家配置页无类目数据） | 主跑+续跑×2 共 3 次均败 → 持久 |
| 8669 | 领克Z20 | 同上 | 同上 → 持久 |
| 2504 | 五菱星光 PHEV / 五菱星光 EV（壳名=长安星光，见 §5-1） | 同上 | 同上 → 持久 |

另 3 系主跑失败、续跑即复活（首跑为瞬时空响应，非持久缺口）：8433 零跑A10 / 7712 / 8283。

## 5. 数据真实性披露（红线#1/#6）

1. **2504 绑定疑似错绑**：pool 绑定 sales 名「五菱星光 PHEV/EV」，API 实返壳名「长安星光」（长安凯程）。本脚本按 API 原文落库不修改；建议 T6/人审复核该绑定（nev_pool.json 由 T1 产出，本脚本不改名单）。
2. **8544 博越REV**：API 未返回壳名/品牌/价带 → 按「缺即 NULL」落库（review_count=0），不编造。
3. **共壳 energy 冲突 44 条**（全部为 energy 字段，maker/level 零冲突）：同壳 DM-i/EV 两个 sales 名 energy 必不同，单值列不可兼得 → **首见项落库，全名单如下**，供人审决定是否需要按壳改判：
```
  8171 钛7: {"energy": {"kept": "纯电", "dropped": "插混"}}
  8087 比亚迪 海狮06 DM-i: {"energy": {"kept": "纯电", "dropped": "插混"}}
  7588 比亚迪 海豹06 EV: {"energy": {"kept": "插混", "dropped": "纯电"}}
  5964 比亚迪 秦PLUS EV: {"energy": {"kept": "插混", "dropped": "纯电"}}
  8273 零跑 D19 纯电: {"energy": {"kept": "增程", "dropped": "纯电"}}
  7578 比亚迪 秦L EV: {"energy": {"kept": "插混", "dropped": "纯电"}}
  7864 银河星舰7 EV: {"energy": {"kept": "插混", "dropped": "纯电"}}
  8176 领克10 EM-P: {"energy": {"kept": "纯电", "dropped": "插混"}}
  8459 日产 NX8 纯电: {"energy": {"kept": "增程", "dropped": "纯电"}}
  7674 零跑 C16 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}
  7305 智己LS6 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}
  8187 五菱星光730 PHEV: {"energy": {"kept": "纯电", "dropped": "插混"}}
  5499 比亚迪 汉DM-i: {"energy": {"kept": "纯电", "dropped": "插混"}}
  6817 深蓝S07 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}
  7382 零跑 C10 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}
  8245 埃安 i60 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}
  5205 零跑 C11 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}
  7652 阿维塔07 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}
  8216 五菱星光560 EV: {"energy": {"kept": "插混", "dropped": "纯电"}}
  8485 比亚迪 海豹08 DM-i: {"energy": {"kept": "纯电", "dropped": "插混"}}
  8244 深蓝L06 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}
  8014 小鹏G7 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}
  7717 马自达 EZ-60 纯电: {"energy": {"kept": "增程", "dropped": "纯电"}}
  7456 eπ008 REEV: {"energy": {"kept": "纯电", "dropped": "增程"}}
  7740 深蓝S05 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}
  7125 ARCFOX αT5 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}
  8205 尚界H5 纯电: {"energy": {"kept": "增程", "dropped": "纯电"}}
  2504 五菱星光 EV: {"energy": {"kept": "插混", "dropped": "纯电"}}
  8609 奕派M8 REEV: {"energy": {"kept": "纯电", "dropped": "增程"}}
  7859 比亚迪 汉L EV: {"energy": {"kept": "插混", "dropped": "纯电"}}
  7752 阿维塔06 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}GET https://koubeiipv6.app.autohome.com.cn/pc/series/list?pm=3&seriesId=8171&pageIndex=1&pageSize=1&yearid=0&ge=0&seriesSummaryKey=0&order=0 失败: , 尝试 1/2
  8431 星途EX7 纯电: {"energy": {"kept": "增程", "dropped": "纯电"}}
  7671 五菱星光S PHEV: {"energy": {"kept": "纯电", "dropped": "插混"}}
  8100 至境L7 EV: {"energy": {"kept": "增程", "dropped": "纯电"}}
  6388 问界M5 EV: {"energy": {"kept": "增程", "dropped": "纯电"}}
  7162 小鹏G6 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}
  8214 锐胜M8 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}
  8563 MG 07 EV: {"energy": {"kept": "插混", "dropped": "纯电"}}
  8305 小鹏MONA L03 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}
  7741 宝骏云海 PHEV: {"energy": {"kept": "纯电", "dropped": "插混"}}
  7301 荣威 D7 EV: {"energy": {"kept": "插混", "dropped": "纯电"}}
  7323 风神L7: {"energy": {"kept": "纯电", "dropped": "插混"}}
  7211 大家7 DMH: {"energy": {"kept": "纯电", "dropped": "插混"}}
  6633 雷霆 增程: {"energy": {"kept": "纯电", "dropped": "增程"}}
```
4. **metadata 词表口径**：maker=sales_trim manufacturer 原文（self-check Gap6 拍板：直取优于别名猜测，如「零跑汽车」而非旧表「零跑」，选择器展示列无聚合影响）；energy 归一到表内既有词表（纯电动→纯电/插电式混合→插混/增程式混合→增程，未知值原样）；level=CAM 车级字母（A/B/C/A0/D，与旧行之家式词表「中型SUV」混排——get_full_config 不返回 level，metadata 是唯一来源，无覆盖冲突）。
5. **不刷新已有**：缺口名单只含表外 id；upsert 的 update 分支仅兜幂等续跑，本轮 0 次触发（补壳 insert=114 / update=0）。
6. 新配置行 `fetched_at` 已落（如 8433=2026-10-16 21:58:34），version=1，decode_hit_rate 1.0，categories 抽查 38KB 非空。

## 6. dry-run 与 live 量对账

| 项 | dry-run 预估 | live 实际 |
|---|---|---|
| 缺壳 | 114 系 → 114 请求 | 114/114 insert，0 失败（148s） |
| 缺配置 | 105 系 → 105-315 请求 | 102/105 成功（主跑 99 + 续跑 +3），3 持久失败 |
| 总耗时 | 预估 ≈5-11 分钟 | 主跑 148s+39s，续跑 2s×2 ≈ **3.2 分钟** |
| 表行数 Δ | +114 / +102 预期 | 实测 +114 / +102 精确命中 ✓ |

## 7. 验收对照（tasks.md T2）

- [x] 缺失项补齐：壳 114/114（100%）；配置 102/105（97.1%），缺项=§4 例外清单在案
- [x] PRISM_COLLECT_LIVE 门控 + dry-run 默认（打印名单/逐项计划/预估）——dry-run 实测输出 114+105 条 PLAN
- [x] 逐车系 progress + 断点续跑（续跑实测只补缺，复活 3 系）
- [x] 失败进例外清单不中断（主跑 6 失败不中断批）
- [x] config_snapshots fetched_at 更新（新行全部带 fetched_at）
- 例外遗留：3 系配置缺口（来源页无数据，需源站可解析后重跑 `python scripts/backfill_pool_base.py` 即自动只补这 3 系）
