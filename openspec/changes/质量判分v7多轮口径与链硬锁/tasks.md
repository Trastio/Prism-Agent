# tasks · 质量判分 v7

- [x] T0 explore：quality_judge.mjs 全文 + 两报告行结构核验（turnMessages 齐全/question=首轮 40 字截断实锤/sidecar 仅 8 items）
- [x] T1 Step5 施工（fork 子代理）：eval/quality_judge.mjs + eval/quality_judge.test.mjs
  - [x] T1.1 模板分型：v7 多轮三段式 + 单轮 v6 逐字节一致 + PROMPT_ARCHIVE.v6（指纹 8b7c7620）
  - [x] T1.2 资格硬锁：QUALIFIED 链过滤/探测全败硬错/429 指数退避（15→300s，行预算 10min）/链外模型永不被调
  - [x] T1.3 后置只读：--post/--find-gap 读 sidecar 缺判报数，零 LLM 零 sidecar 写；--judge 资格外拒绝；--calibrate 例外
  - [x] T1.4 单测：模板分型/归档指纹复算/硬锁过滤/429 退避 mock/只读后置（29/29）
  - [x] T1.5 施工报告
- [x] T2 Step7 隔离审查（general-purpose 子代理，磁盘自读；P0×0/P1×1/P2×8）
- [x] T3 Step8 修审（修 P1 指纹闸+P2×3，记 5；review-response.md）
- [x] T4 Step9 验证：
  - [x] T4.1 单测全绿（quality_judge 29/29 + eval 侧回归 179/179）
  - [ ] T4.2 校准复验 v7·glm-5.3-flash ρ≥0.7 PASS —— **卡 GLM 账户余额耗尽（code 1113，10:34 直证）**，充值后由驱动自动执行
  - [x] T4.3 langfuse 栈复活 + watchdog --post 核验（欠账#3）✅ **182 条（更正"186"口径：3 无 traceId 跳过+1 弃用侧，可写行全落库零丢失）**
  - [ ] T4.4 v1.3 全量重判 188 行 + v1.4 全量重判 189 行 —— 卡余额；驱动 logs/quality-v7-rejudge.cmd 备好（校准闸+裁判同质性+余额中止 exit 3）
  - [ ] T4.5 双报告 --post + --find-gap（只读）+ multi 冤案消除抽验（multi-02/12 D1）——随 T4.4
- [ ] T5 发版门槛正式结论（质量分配对检验 + 质量修复型变更定性）→ EVAL_STATUS —— 随 T4.4/T4.5
- [x] T6 尾巴处置：multi-07"25"量化/value_grounding 概率从命/辅助位泄漏 → 诊断与提案入档 EVAL_STATUS（辅助位观察结论挂起重判 D5 数据）；**不今日修 prompt（两臂语料纯净）**
- [x] T7 Step10 归档 commit（代码侧）+ memory 更新 —— 重判链（T4.2/T4.4/T4.5/T5）充值后由驱动续完，届时补归档
