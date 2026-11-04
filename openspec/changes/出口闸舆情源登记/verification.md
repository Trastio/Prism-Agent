# Verification · Step9

## 验收对照（proposal 4 条）

1. **E2E 复问** ✅ 两轮（E2E-1 无身份引导 / E2E-2 含引导）：
   - 支持引用 `sentiment_overview:风云T7` 等被 /verify/claim 接受（不再是"库中无对应数据"）
   - E2E-1：出口闸通过、无"漏提交"保底（仅身份保底一轮——引导加入前）
   - E2E-2：resolve_series 前置、**零保底回灌**、出口闸通过、最终 verdict=pass（session 01a12b9c）
   - 注："首次 submit 即过"未字面达成——残留 R1-deep 普通词误报致同轮自纠 2~3 次（用户不可见，见 review-response）
2. **smoke:all** ✅ **55/55**（基线 50 + grounding 新 4 case + verify_claim_api 新 1 suite 内 5 断言）；旧 8 名称 case 零回归
3. **verify_claim_api.test.ts** ✅ 真车系过 / 假车系拒 / 真帖 ID 过 / 假 uuid 拒 / 三维度回归（sales_trim:银河E5/2026 过）
4. **fail-closed 防御** ✅ `sentiment_posts:00000000-…` 拒；`sentiment_dimension:风云T7/续航`（转写缩写）拒、`/续航里程`（库源真名）过——红线#6 守住

## 类型与语法

- 根 tsc --noEmit：11 = 历史基线，零新增
- prism-web tsc --noEmit：0
- main.py py_compile：OK

## 手测补充

- 混排 6 引用（sentiment_overview/board/dimension 真名+缩写/events:车系名/review_tags/sales_trim）：仅缩写 dimension 被拒（预期）
- 前端文案：ChatView isRetry 块改"自动复核…修正回复"（vite 热更生效）

## 环境

- 五服务经 prism.py stop/start 重启（2026-10-11 15:3x），PRISM_AUTO_APPROVE_UI=1 由启动器携带
- E2E 会话目录 .pi/sessions/e2e_sentrail_*/e2e_sent2_*（测试产物，可清理）


## 2026-10-12 补验收（子代理失败后主会话代行）

- 验收矩阵 4 组全 PASS（见 review-response.md 补流程记录）
- smoke:all 55→**57/57**（+2 边界 case）
- 注入探针（DROP TABLE / 100%--）实测：均被拒、参数绑定无害化、库完整
