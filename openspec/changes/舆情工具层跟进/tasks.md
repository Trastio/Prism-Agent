# 舆情工具层跟进 · tasks（2026-10-20）

轻量十步：Step1 explore ✅ / Step2 proposal ✅（设计并入 proposal T1-T4）/ Step5 施工 ✅ / Step7 隔离审查（进行中）/ Step8 处置 / Step9 验证 ✅（主体）/ Step10 归档。

## Step5 施工实录（全 9+2 处改动）

| # | 文件 | 改动 | 状态 |
|---|---|---|---|
| 1 | extension index.ts | resolveVehicleId 两级解析（fleet-overview active 快路径 → fallback 全量含 paused/inactive；归一匹配去空格+小写；export 供测试） | ✅ |
| 2 | extension index.ts | makeSentimentTool execute：status 三态（active 照查/paused 照查+对象顶层注入 _prism_frozen_note/inactive unavailable 新文案/未收录原文案） | ✅ |
| 3 | extension index.ts | 注册 sentiment_defects（/defect-themes/{id}，通用路径零特例——端点 start/end 已退役）；trend 描述补 30 天保留线注记 | ✅ |
| 4 | extension index.ts | KNOWN_BUSINESS_TOOLS 22→23 + TRUNCATABLE_TOOLS +1（注释同步） | ✅ |
| 5 | extension index.ts | submit_conclusion 描述与拒绝提示补 sentiment_defects 引用格式（2 处） | ✅ |
| 6 | main.py | _SENTIMENT_TABLES +sentiment_defects | ✅ |
| 7 | main.py | 新端点 GET /sentiment/vehicles-all（只读直查舆情库全量车含 status；设计变更见下） | ✅ |
| 8 | tests | verify_claim_api.test.ts +3 case（defects 真车过/假车拒/paused 车引用过）；新 sentiment_tools.test.ts（4 case，动态 import+env 注入）；tool_call.test.ts 断言 22→23 | ✅ |
| 9 | package.json | smoke:verify 挂载 sentiment_tools.test.ts | ✅ |
| +1 | e2e_check.py | E2E 验收脚本（两问+verdict 竞态兜底） | ✅ |
| +2 | tests/sentiment_tools.test.ts | env 注入（PRISM_SERVICE_TOKEN 从 .pi/service_token 读；缺文件降级直连 8000） | ✅ |

## 施工中的两个设计变更（相对 proposal v2）

1. **fallback 数据源改道**：舆情 /api/vehicles 也筛 active（explore v2 漏核，施工测试抓出）→ 舆情侧无任何全量名单端点。裁决走 Prism 侧新端点 /sentiment/vehicles-all 直读舆情库（身份映射是 Prism 适配层职责；与 /verify/claim 直读同模式）。proposal"零接触 prism-sentiment 源码"表述作废——正确边界是"零接触旧仓库（Agent项目/）"，prism-sentiment 已内化为 Prism 子服务。
2. **sentiment_defects 零特例**：explore v1 曾设计"工具显式传 30 天窗防 TTL 互踩"——基于旧仓库代码。生产版端点 start/end 已完全退役（TTL 不比对窗），通用路径即可，窗算特例作废。

## Step9 验证实录

- tsc：11 个历史基线错，index.ts/main.py 零新增 ✅
- 单测：sentiment_tools 4/4（风云T7 active / 银河E5 paused fallback / model y 归一 / 不存在 null）+ verify_claim 7 case ✅
- smoke:verify 129 tests（128 pass + 1 E2E 门控 skip + 0 fail）✅
- smoke:all 全绿（grounding 21/trap 28/truth 9/rubric 15/value_diff 39/prompt 8）✅
- 活端点：/sentiment/vehicles-all 返回 26 台（T7 active/E5 paused 实证）；defect-themes T7 TTL 命中 0.0s 返回 3 簇（配置不合理 238 评论/续航/刹车）✅
- 服务重启：8002（23:34）+ 9200 网关（23:39，带 PRISM_AUTO_APPROVE_UI=1；token 网关自读文件注入）✅；**eval 网关 9201 未动**（工具面隔离，见 explore 风险 2）
- E2E 真对话两问（15s/16s）：
  - Q1 银河E5 舆情：工具链 sentiment_overview→sentiment_defects→submit_conclusion；回复 1368 字含"停更/冻结/不代表近期动态"声明、无"未收录"误报；**出口闸 pass=true**（trajectories submission 实证）
  - Q2 风云T7 缺陷：工具链 sentiment_defects→submit×2；回复含四大吐槽簇+车主原话+抖音 URL 溯源；**出口闸 pass=true**
  - 已知非本 change 现象（记录不修）：settled 事件 verdict=None=mapEvent 读 verdict.json 时序竞态（旧账）；中间拒因"续航落差/续航问题 vs 续航里程"=R1-deep 名称近似遗留（同轮自纠，用户无感）
