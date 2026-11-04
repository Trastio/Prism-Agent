# proposal · 取代性实验 B 系列（G-3，伞计划收官 P3；设计=评估方案 §10.2 v3.5 落档，本件为施工收口）

## WHY（§10.2 原文，2026-10-14 用户立项）

"通用 agent 越来越多，Prism 能否被『通用 agent + 数据库 + 一份 skill 文件』取代"——分歧不靠辩论裁决，靠跑分。**前置依赖「60 题基线出分」已满足：A0=P2 v1.3 repeat=3 首跑分**（同题库同快照同判分）。

## WHAT（四件，全部文件级——批跑期间不动活栈）

| # | 交付 | 落点 | 量级 |
|---|---|---|---|
| 1 | challenger extension（无任何 hook，仅注册 run_sql（快照只读 URI+20KB 自截断）+ read_file（白名单 SKILL.md/schema.sql）） | .pi/extensions/challenger-b1/index.ts（新） | ~80 行 |
| 2 | SKILL.md×2：B1a=AGENTS.md 原文（SOP 从宽给足）；B1b=+完整口径手册（22 语义工具的 SQL 语义文字化：两锚分离/year聚合/brand子品牌/BEV枚举/recent_retail/MG空格LIKE坑/万换算…） | .pi/extensions/challenger-b1/{SKILL-A.md,SKILL-B.md}（新） | A~300 行/B~600 行 |
| 3 | schema.sql（快照两库 .schema 导出，附给挑战者） | .pi/extensions/challenger-b1/schema.sql（新，生成物） | 脚本 |
| 4 | runner `--challenger` 模式：无 verdict/trajectories 判据（verdict=none），判最终回复文本（六分制断言+trap 拒绝词方向正则+缺口题正确拒绝+编造率抽检挂钩）；用户消息前缀带 SKILL 路径指示；默认路径零变化（flag 隔离） | eval/runner.mjs + eval/challenger_check.mjs（新） | ~120 行 |

## 决策（授权模式留痕）

1. **公平性五规则照 §10.2**：同快照哈希/同题库/同判分器（no-verdict 形态）/双无 web/挑战者顺序跑。
2. **B2 真实外部 agent 抽查不做**（本轮砍掉——Claude Code/GLM 接 MCP 的搭设是另一个 change，定性参照价值有限）。
3. **A0 复用 P2 分数 + 用 no-verdict 重放模式对齐口径**（replay 思路：A0 的 reply_full 以同款文本判分器重判，剔除 verdict 通道优势后再比——否则挑战者无出口闸天然吃亏判）。
4. 跑批时机：P2 完批 + eval 栈重启挂 challenger extension 后（网关 spawn `-e` 换指向）；**施工期间禁起服务禁跑题**。

## 影响面

- 新增：.pi/extensions/challenger-b1/{index.ts,SKILL-A.md,SKILL-B.md,schema.sql}、eval/challenger_check.mjs(+test)
- 改：eval/runner.mjs（--challenger flag，默认零变化）
- 不动：prism-guardrails、生产网关、题库、判分器、快照
- 预注册预测与判读门槛：§10.2 原文（Δ≥1.0+trap差≥40pp→护栏必要性成立；Δ<0.3→取代论成立产品重定位；中间带→分层拆）

## 验收

1. challenger extension 语法过 + 单测（run_sql 只读 URI 拒写/截断；read_file 白名单外拒）
2. SKILL-B 口径手册 ≥15 条口径逐条可溯源到语义工具源码（文件:行）
3. runner --challenger 单测绿 + 默认路径单测零回归（既有 129 判分器测试全绿）
4. 两臂跑批+stats.py 配对+报告（归档件）——**P2 完批后执行，不在本施工工单内**

## 不做边界

模拟器/自适应 agent；B2 外部 agent；上云；题库新增。
