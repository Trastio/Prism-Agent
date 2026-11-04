# archive · 多轮评估批 change（2026-10-25，十步全走完）

## 一句话

多轮题 12 道落库（63→75）+ 三机制（variants/branch_on/carryCheck）+ ask_user 模拟应答第三态 + traceId 补存 + /events 身份焊死 + trap 3 类——评估侧最后一块拼图就位，v1.2 基线批跑（Gate G1 口径）万事俱备只欠点火。

## 交付清单

| 件 | 落点 |
|---|---|
| 12 题（用户过审卷册→落库，锚点快照查证零手抄） | eval/tasks.json + 核心文档/05-多轮题卷册-12题-审阅版.md |
| 三机制纯函数 + 快照漂移闸 | eval/multi_turn.mjs（67→103 行）+ multi_turn.test.mjs（+4） |
| runner 接线（增量，单轮路径零变化） | eval/runner.mjs |
| Sheet4 穿线实值 | eval/report_lib.mjs + 测试 |
| ask_user 第三态（PRISM_EVAL_UI_SIM，仅 eval 网关） | prism-api/pi_gateway.mjs + prism.py（hunk 分离提交 056d717） |
| traceId 补存（run 链接激活） | eval/runner.mjs + langfuse_writer.ts（lookupTraceId）+ binding 注释修正 |
| /events 身份焊死 | prism-api/main.py:284-285 + test_auth.py +2 |
| trap 3 类（附和/串味/残留） | eval/trap_check.mjs + scoring-rules.json |
| 容差校准（P1-1） | scoring-rules.json multi-02#t2 rel=0.1 + calibration_log |

## 十步轨迹

explore（代码现状实读，行号级）→ propose/design/tasks（三件，机制设计先行）→ 3.5 自查（12 Gap 全处置）→ **Step5 fork 型子代理施工**（NO-TOOLS 守卫，208 工具调用，冒烟抓 2 真 bug 自修）→ 主会话验收抽查（5/5 中+测试独立复跑 129/128）→ Step6 简化（纯函数收敛）→ **Step7 隔离子代理审查**（0P0/2P1/6P2；锚点独立复刻 15 项、生产网关逐行等价、既有题 diff 零触碰实证）→ Step8 处置（P1×2 修：宽容差+活性戳闸三态端到端；P2 2 执行 4 记录）→ Step9 验证（判分四套 84/84 + smoke:verify 129/128 + 漂移闸三态 + 冒烟 3/3 全 5 分）→ Step10 归档（本文+EVAL_STATUS）。

**commits**：a031575（change 本体 40 文件）+ 056d717（prism.py 两 hunk 分离，并行会话 NO_BROWSER 未夹带）。工作树遗留：EVAL_STATUS.md（本 change +10-20 并行记档，未提交）、prism.py NO_BROWSER hunk（并行会话在途）。

**补审环（同日晚，用户拍板补上）**：Step8 两处主会话修复经隔离子代理复核——修复本体实证合格（rel=0.1 五形态命中+摘除容差反证；闸三态复现），另抓 **P1×1**（漂移放行留痕只在 console 未进报告/manifest——放行跑与干净跑审计件不可区分）+ **P2×3**（闸只护多轮题应加宽到全部快照绑定题 / eval stop 不清活性戳 / 写失败告警可接受）。全修：审计字段进 report+manifest、闸加宽（单轮 sales-11 九月空同族纳入，+2 对照测试 18/18）、stop 清戳；详见 补审报告.md 处置节。**流程环闭合：十步+修复补隔审全链可溯。**

## 面试三讲

**① 解决了什么问题**：单轮评估 90% 通过率只证明"一次问对"，不能证明"对话扛得住"——真实用户会甩错数字纠正你、追问不存在的数据、中途换题。这套题把"数据真实性红线"从静态问答升级成对话攻防：纠正题考"顶住不附和"（用户说错≠真相，仍以工具真值为准）、缺口题考"两轮都不编"、回访题考"跨会话不串味"。配套把三个基建挂账一并清零（ask_user 网关抢答、traceId 断链、/events 身份裸奔）。

**② 关键裁决与用户角色**：题目与锚点分工翻转（原方案"用户出话术"→用户拍板"AI 全权出题+落锚，我来审阅"）——AI 从快照库查证落锚（15 锚可复算），用户只做审阅把关，产能×质量两全；卷册审阅时用户"没啥问题"过审+追问审阅要点含义（知情确认）。两个查证驱动的设计变更（星愿口碑 0 条→t3 改撞缺口；E5/B10 con 率过近→t2 改指定对象）都是"先查库再定题"的产物。

**③ 面试官会追问什么**：Q"多轮判分怎么防止评分手抖？"——逐轮 truth 锚+首错轮+三档顶住判定全部机器化，gap 类答案用 expect_gap 语义词锚而非人工判；审查者独立复刻 15 锚抓出 1 个时间窗敏感假阴（差价 8月末/上半年/全年三个合法读法），修法是容差+校准账（每次校准必记 calibration_log 六字段）。Q"快照轮换了怎么办？"——活性戳+漂移闸 fail-closed：题库锚绑定快照 id，轮换不一致直接拒跑，宁可停下来重验锚也不静默出错误分数。
