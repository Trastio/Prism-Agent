# Spec 2 · 技能层（load_skill + car-reputation-research 落地）

## 待办

- T1 load_skill 工具：{name, file?}；allowlist 根 = PROJECT_ROOT/.pi/skills；name `^[a-z0-9-]+$`、file `^[a-z0-9/_.-]+$` + resolve 后前缀校验防穿越；返回原文（truncateHead 50KB）+ 同目录文件清单
- T2 before_agent_start 系统提示词追加技能指针一行（不依赖 pi 原生发现，不修改 AGENTS.md 文件）
- T3 `.pi/skills/car-reputation-research/SKILL.md` Prism 版（design §2.2）：铁律 8 条（原 6+画像边界+成本纪律）/流程 5 步/TikHub 平台表/交付对接 export_document。成本纪律细则含**分轮推进**（单轮先 2-3 平台，续问补齐，缺口如实声明——模板 A 全网扫描 10 次>8 上限）与**社媒深挖流程优先于三维度 SOP 顺序**的说明
- T4 references/deliverable-spec.md：模板 A/B 保留，补 sheets 结构对照（headers/rows ↔ export_document 参数）
- T5 references/platform-notes.md：Prism 实际版（social_* 免登录四平台+哔哩；汽车之家 web fetch 游客全通含 URL 格式；删 CDP/MediaCrawler/3388）

## 设计细节

- 画像输出边界铁律原文（进 SKILL.md）："画像输出限于人群理解颗粒度（如'40岁女性外贸从业者'），不输出可定位到具体个人的信息组合（住址小区级/手机号/证件类）；溯源清单 URL 属证据链，对管理者可见"
- 成本纪律铁律原文："TikHub 每轮限 8 次调用；达到上限即基于已有数据分析，数据缺口走假设清单范式，不硬凑"
- 触发词保留原文（口碑/舆情/车主反馈/提车作业/试驾/吐槽/真实车主/水军/KOC）
- load_skill 工具描述：一句话功能 + 指向当前唯一技能（描述即触发面）

## 验收

1. load_skill('car-reputation-research') 返回完整 SKILL.md（含铁律 8 条）
2. load_skill('../secrets') / name 带大写/绝对路径/file 带 `..` 全部拒绝（fail-closed）
3. load_skill(name, 'references/deliverable-spec.md') 返回规范文件
4. 新会话系统提示词含技能指针行（RPC 模式实测 before_agent_start 生效）
5. skill 全文无 Claude Code 残留引用（grep web-access/CDP/MediaCrawler/3388 = 0）

## 依赖

- Spec 1（skill 流程引用 social_* 工具与 8 次上限）、Spec 3（交付步骤引用 export_document）
