# P0-评估锚点 · tasks（Step5 施工清单）

> TDD 纪律：T1 先红后绿。每项完成打 [x]。

## 批A · trap 判分修正（#29）

- [x] T1 `eval/trap_check.test.mjs`：≥13 断言（6 规则 × 正反例 + verdictFail 优先级 + NEG_RE 单源导出）——先写测试
- [x] T2 `eval/trap_check.mjs`：trapBlocked 纯函数（D1 算法表）+ NEG_RE 导出；runner trap 块删内联改 import（含局部变量 trapBlocked→blocked 防遮蔽）；NEG_RE 改 import
- [x] T3 package.json：`smoke:trap` + 并入 `smoke:all` 链尾

## 批B · 题源合一（#30）

- [x] T4 `eval/tasks.json`（18 题三新字段齐）+ runner 改 readFileSync + tasks_v1.ts 头注归档声明

## 批C · 快照 + eval 环境（#28）

- [x] T5 `eval/snapshot.py`：create/list（VACUUM INTO 字面量形式 + sha256 + manifest as_of 口径日 + best-effort 舆情表探测）
- [x] T6 `prism.py`：eval start/stop/status（四实例 env 表 / Gap1 uvicorn 直拉 / stop 只清四端口不调 _kill_supervisors / PRISM_API_BASE 与 Gap3 提示行）

## 批D · 断言分组 + 顺手（#31 + doc rot）

- [x] T7 `eval/truth-expectations.json`（两键）+ smoke_m3 EXPECT 外置缺省回退 + registry smoke 观察值注释
- [x] T8 runner PRISM_API_BASE env + 头注释修正；EVAL_STATUS 指针 v3.4.3

## 施工附注（Step5-8）

- Step6 simplify 两处：runner L36 双语句拆行；snapshot.py VACUUM INTO 参数绑定改字面量转义（防版本差异）
- Step7 隔离审查 ✅（终版）：无 P0 / P1×3 / P2×10；初版两项"待坐实"经 env 实证关闭（models/database.py:7 / index.ts:205,303）
- Step8 ✅：P1 3/3 处置（窗口对称+caliber 两条件+快照哈希双轨：dashboards mode=ro / sentiment 口径定案+first_mounted_at 留痕）；P2 10/10；测试 ~25 断言含反向锚

## 批E · 验收（Step9 ✅ 验证子代理两轮执行，详见 verification.md）

- [x] T9 单测 12/12 全绿；smoke:all 六段全绿（verify 97 pass/1 预期 skip）
- [x] T10 快照 snap-20261012-1217 + 1222 产出（363MB/秒级），manifest/list 校验通过
- [x] T11 第一轮 dashboards-eval 只读判死→回退可写→第二轮四实例全绿；stop 清四端口；生产五服务 PID 不变
- [x] T12 `--only=trap` **6/6 score=5 否决率 100%**——r3 冤案坐实（trap-04/05/06 均为旧判分假阴性，agent 防线有效）
- [x] T13 缺省 8002 由 `process.env.PRISM_API_BASE || 'http://127.0.0.1:8002'` 代码保证；trap 轮显式带 env
