# query_sales month 实装 · 任务单（小 change）

- [x] T1 api：路由签名加 month + 1-12 fail-loud 校验（400）；月度聚合 SQL 条件 + spec 分支行内前导数字过滤（月末口径限定原样保留）
- [x] T2 工具侧：schema 恢复 month 参数 + B1-6 债注更新
- [x] T3 单测 5→7 例（子集等价/缺失月空/1-11 陷阱/null 语义锁/400×2/reviews+config 无副作用）
- [x] T4 活端点实测（仅重启 api）：month=8 恰 1 行 4436；month=13→400；spec 全 '8月末'
- [x] T5 Step7 隔离审查（month-param-review 子代理）→ review-response.md（P0=0/P1=0/P2=6 → 修5/核实1）
- [x] T6 Step8 修复：import 上移 / 陷阱断言条件化 / falsy 吞0 / null 锁 + config 对称测 / pytest.skip 显性化
- [ ] T7 Step9 统一验证（与评估基建小包合并）：网关重启后 schema 生效 + smoke + 门禁
- [ ] T8 verification.md + 归档
