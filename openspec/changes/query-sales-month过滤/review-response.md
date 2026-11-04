# Step7 隔离审查处置记录（query_sales month 实装 · 2026-10-15）

> 审查者：month-param-review 子代理（代码磁盘提取内嵌）｜ 结论：**可过 P0=0 / P1=0 / P2=6，无必修项**
> 处置：修 5 / 核实补注释 1 ｜ 修后 pytest 12/12 绿（含新增 null 语义锁 + config 对称测）

## 审查六大裁决（要点）

1. **月末口径红线：安全**。聚合分支 SQL WHERE 是并列 AND（`%月末` 限定与月号过滤同行求值，无先后问题——'8月中' 行进不了结果集）；spec 分支口径限定在原 SQL 未动，行内正则前导数字无 1/11 误配
2. **400 顶部校验：保留**。根因就是静默丢弃，移入 sales 分支会制造"有时 400 有时静默"的新不一致；非法 month 无论 dtype 都是消费方 bug，暴露优于吞掉
3. **month=9 → retail_sum=null：现状正确**。第二种如实缺失语义（无月末行→[]；有行零售全 NULL→1 行 null），null≠编数，与全量行为一致，"只缩行集不改口径"承诺兑现
4. 测试主防线成立：子集等价断言 + 外部真值锚 4436（金标 sales-14，非镜像）
5. schema 与后端行为一致（1-12/口径不变声明）
6. `import re` 后置导入：运行时成立（实证过）但模式脆弱 → P2

## P2 处置

| # | 发现 | 处置 |
|---|---|---|
| P2-1 | import re 在函数定义后（369 行） | **修**：上移顶部 import 区（含注释说明） |
| P2-2 | 400 全 dtype 生效是行为变化 | **核实+注释**：grep 证实现网零消费方（web 前端不调 /dashboard/，工具 schema 仅 query_sales 有 month）；校验处补三行注释防后人困惑 |
| P2-3 | 1/11 陷阱断言区分力依赖 2025 年 10/11/12 月历史行，数据裁剪后空真过 | **修**：条件化——库内有 10/11/12 月行才强断言"未吃进"，无则显性 note |
| P2-4 | execute 侧 `if (params.month)` falsy 吞 month=0（静默返全量——与 B1-6 同构的另一半） | **修**（超出审查建议的"记录"）：改 `!== undefined`，0 交后端 400 fail-loud；**生效需网关重启（Step9）** |
| P2-5 | retail_sum=null 语义无回归锁 | **修**：新增 test_null_retail_month_lock（动态找 null 月，过滤后须 1 行 null 不得剔空/填 0） |
| P2-6 | config 无副作用缺测；absent skip 用 print+return | **修**：新增 config 对称测 + `_skip()` 助手（pytest.skip 显性化，裸跑兼容） |

## 遗留（记录不修）

- 行 102 `import re as _re` 重复导入语义（合并属可选，非本 change 义务）
- 网关重启生效项：index.ts schema month 参数 + falsy 修复均需新 pi 进程加载（Step9 统一重启验证）

## 验证

- pytest 12/12（含 2 新增）；既有 export 5 例零回归
- 活端点三连（month=8=4436 / month=13=400 / spec 15 行全月末）由施工轮实测，本轮修复为行为中性改动（导入上移/注释/测试侧），不改变已验行为
