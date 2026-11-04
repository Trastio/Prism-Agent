# verification · 归因工具包（2026-10-16，微 change 主会话直修）

> 拍板：归因修复（A堆提示词修/B堆判分校准）**留给用户亲自判读**——本包只供材料不替人下结论。

## 交付三件

| # | 件 | 验证 |
|---|---|---|
| 1 | langfuse metadata 增强：score 写回加 truth_missing[] / truth_forbid_hits[] / rubric_missing[] / first_error_turn（writer + runner 接线，旧调用方零影响） | 单测 22/22 含材料包两件；真值随下轮批跑首见（langfuse score 详情页） |
| 2 | 归因材料包生成器 `eval/gen_attribution_pack.mjs` + 报告加 reply_full 字段 | **v1.1 实物已出**：`eval/reports/归因材料包-eval-2026-10-14T02-02-14.md`（6 题全：题面/判分规则/逐要素明细/首错轮/工具链/回复/候选信号；旧报告无 reply_full 自动降级预览+langfuse 指引） |
| 3 | DAU 口径分界标注：ops_server.py 注释更新 + EVAL_STATUS 记分界日 2026-10-15 | 防匿名期/实名期趋势误连（同 r3↔v1.1 教训） |

## 纪律

- 初步信号只给"候选A堆/B堆/混合"分类与验证指引，**不下结论**——归因结论由用户读材料后自下
- 不碰判分路径（runner 只加字段/传参）；不碰提示词（prompt-gate 指纹未变，无需冒烟）
- 用户归因产出修复方案后，执行走 prompt-gate 流程（改提示词→trap 冒烟→mark-green）

## 用户使用路径

1. 打开 `eval/reports/归因材料包-eval-2026-10-14T02-02-14.md`——6 题单文件读完
2. 每题看"回复原文"对照"初步信号"验证/推翻候选分类
3. 需要过程细节 → langfuse(3000) environment=eval 搜题号（score 卡此后直接带判分明细）
4. 归因结论告诉我 → 修复执行我来

## 追加（2026-10-16 盘点轮）：登录门适配活服务 smoke

梳理工程端时补跑根目录 tests/ 套件（登录门 Step9 当时只跑了 pytest，漏了这批）——**6 个活服务测试全 401**（abort/identity/verify_claim 直连 8002 不带 token）。非逻辑回归，是门禁与 smoke 的适配缺口。修：新建 `tests/auth_smoke.ts`（loginOnce+authHeaders，登录失败不吞——请求 401 红掉 fail-loud）三文件接入。复跑 **69 项 68 pass / 0 fail / 1 skip（E2E 门控）**。教训：Step9 验证矩阵必须包含"所有测试入口"——pytest 之外还有根目录 node 套件，两套入口两套清单。
