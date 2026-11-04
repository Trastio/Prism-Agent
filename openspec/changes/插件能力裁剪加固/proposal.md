# 插件能力裁剪加固 · Step 2 Proposal + Design + Tasks + Self-check

> 2026-10-06
> 前置：[explore.md](./explore.md) + [改造计划 v5](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-插件能力裁剪加固-改造计划.md)
> 范围聚焦（5 项改造 + 1 个 extension + 1 个 gateway + 2 个 settings），不拆 7 spec，用单文档覆盖

---

## WHY

四轮审查发现"白名单"概念在三处各一套逻辑（KNOWN_BUSINESS_TOOLS / setActiveTools scope / --exclude-tools denylist），未统一为单一来源。R1 黑名单脆弱 + R3 注释维持 + R6 死配置 + R5 无自检 + A-1 版本未 pin + Q2 项目级架空。

## WHAT（5 项）

| 项 | 核心 |
|---|---|
| A | ALLOWED_TOOLS 单一来源 + agent 显式 setActiveTools + 前缀门控换常量 + catch 降级 |
| B | permission 回填闭环 + 挂起超时拒绝实测 |
| C | Q3 测试 extensions 活/死 → 删配置 |
| D | EXCLUDE_TOOLS 常量 + tsx 单测（拆断言 + 版本） |
| E | pin 12 包 + 删 .pi/settings.json 3 重复 |

## 决策（v5 已拍板）

1. 复用 KNOWN_BUSINESS_TOOLS（不新建）
2. N1 验证决定 ask_user_question 是否加白名单
3. 前缀门控不变（P2）
4. catch 降级 [...KNOWN_BUSINESS_TOOLS]（P3）
5. permission 超时拒绝（P5，非自动批准）
6. D 拆两条断言（Q1）
7. E 删 .pi/settings.json 3 重复（Q2）
8. C 覆盖活/死两种（Q3）

## 影响范围

| 文件 | 改动 |
|---|---|
| .pi/extensions/prism-guardrails/index.ts | ALLOWED_TOOLS + agent setActiveTools + 前缀门控换常量 + catch 降级 |
| prism-api/pi_gateway.mjs | EXCLUDE_TOOLS 常量 + uiRequests 超时拒绝 |
| .pi/agent-minimal/settings.json | 12 包 pin 版本 + 删 extensions |
| .pi/settings.json | 删 3 重复声明 + 删 extensions |
| 新增单测文件 | D 静态断言 |

## 验收（9 条，同 v5）

## 不做

R2 删包 / B2 上下文对象化 / C 进程治理 / D1 双实现收敛 / mem0 评估（均留 v2/上线前）

---

## Design（落法）

### A
- `index.ts` 顶部：`export const ALLOWED_TOOLS = new Set([...KNOWN_BUSINESS_TOOLS]);`（保持 Set，N1 后可选加 ask_user_question）
- before_agent_start：agent scope 调 `pi.setActiveTools([...ALLOWED_TOOLS])`
- decideToolCall：`!ALLOWED_TOOLS.has(tn)`（Set.has，前缀门控不变）
- catch：agent 失败 → `pi.setActiveTools([...KNOWN_BUSINESS_TOOLS])`（去 ask_user_question）
- 删 L584 注释

### B
- 发管理者写操作请求触发 permission
- 观察前端 ui_request + /ui-response 回填
- 若挂起 → uiRequests 加 30s 超时 → 超时发 reject + 提示

### C
- 临时改 -e 路径为不存在的路径，看 pi 是否报错（不删 -e，避免启动失败）
- 据结果删两处 extensions 声明

### D
- `pi_gateway.mjs` 顶部 `export const EXCLUDE_TOOLS = [...]`
- 单测 `node --test --import tsx`：
  - `KNOWN_BUSINESS_TOOLS ⊆ 已注册`（grep 注册点）
  - `ALLOWED_TOOLS` 结构断言
  - `EXCLUDE_TOOLS ∩ ALLOWED_TOOLS = ∅`
  - 版本一致性（Read package.json vs settings）

### E
- agent-minimal settings.json 12 包加 @版本
- 删 .pi/settings.json 3 条重复

---

## Tasks

- [ ] N1.1 验证 setActiveTools(['ask_user_question']) 行为
- [ ] B.1 permission 回填闭环实测 + 超时拒绝
- [ ] A.1 ALLOWED_TOOLS Set + agent setActiveTools
- [ ] A.2 decideToolCall 换 ALLOWED_TOOLS
- [ ] A.3 catch 降级 [...KNOWN_BUSINESS_TOOLS]
- [ ] C.1 改 -e 路径测试 + 删 extensions
- [ ] D.1 EXCLUDE_TOOLS 常量 + 单测
- [ ] E.1 pin 12 包 + 删 3 重复

---

## Self-check（Step3.5）

### Gap 1（自查）· ALLOWED_TOOLS 类型
**问题**：KNOWN_BUSINESS_TOOLS 是 Set，ALLOWED_TOOLS 若数组则 .has 报错。
**修**：ALLOWED_TOOLS 也用 Set（`new Set([...KNOWN_BUSINESS_TOOLS, ...可选])`），decideToolCall 保持 .has。

### Gap 2（自查）· N1 验证方法
**问题**：RPC 模式怎么单独调 setActiveTools？
**修**：发一个 scope=agent 的真实请求，extension before_agent_start 会调 setActiveTools，看 pi 是否报错（pi_gateway 日志 + pi stderr）。

### Gap 3（自查）· C 测试方式
**问题**：移除 -e 可能导致 pi 启动失败。
**修**：不改 -e 为空，改 -e 路径为不存在的文件，看 pi 是否报错（报错=扩展加载成功=活路径；不报错=死路径）。

**自查结论**：3 Gap 全修（施工细节已明确），可进 Step5。
