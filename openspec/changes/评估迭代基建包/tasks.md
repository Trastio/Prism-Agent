# 评估迭代基建包 · tasks（2026-10-14）

## Block A（sub-A 子代理）
- [x] A1 栈复活+restart 策略（Docker 自启待拍板②，不阻塞）
- [x] A2 插件装回+release=infrapack-v1
- [x] A3 writer 真实现（legacy score API+metadata{eval_run_id,task_id,set,snapshot_id,environment}；失败降级 warn）
- [x] A4 实例标签（G4：插件 env 覆盖验证，不行则 metadata 兜底）
- [x] A5 PRISM_TRAJECTORY_FILE 三点接线（extension:781/runner:44/prism.py eval）+mkdir；**先核 prism.py spawn env 透传链**
- [x] A6 ops 回放 `?traj=` 参数
- [x] A7 联调：真实 1 题→UI trace+score；eval 轨迹增长+生产 mtime 不变

## Block B1（sub-B1 子代理）
- [x] B1-1 trap_check 测试 4 例先行→value_grounding 实现→tasks.json trap_params
- [x] B1-2 runner --set
- [x] B1-3 truth 回填（38 题金标锚点机械回填+既有 22 题有则填）+scoring-rules.json 外置
- [x] B1-4 归一化比对（anchor 缺失/forbid 冲突→封顶2）
- [x] B1-5 eval-report 元数据头+reports/ 归档
- [x] B1-6 query_sales month 描述删参（**移入 sub-B2 派单**：extension 归 wave2）

## Block B2（sub-B2 子代理，依赖 B1-3 结构）
- [x] B2-1 rubric_check.mjs 三类判分+单测（排序/缺口/舆情）+插槽
- [x] B2-2 PRISM_EVAL_WEB 三态+extension 剔除 web4（social 不波及）+web fixture（PTC 录制）
- [x] B2-3 requires 探测 skip 不计分母（conditional_skipped 单列）
- [x] B2-4 per-题超时 300s
- [x] B2-5 成本台账（usage 事件探索，缺则 duration 兜底标 partial）
- [x] B2-6 PRISM_FAKE_TODAY 预留（trend 两处时间函数）
- [x] B2-7 多轮 turns schema+session 穿线+逐轮 truth（G6：trajectories 逐轮 verdict 验证）
- [x] B2-8 导出题插槽+假题单测

## Block C（sub-CD 子代理）
- [x] C1 verifyNames 通用域白名单（~20 词）+R1-deep 复现样本零误报+8 case 全保
- [x] C2 mapEvent auto_retry（case+渲染标签）

## Block D（sub-CD 子代理，stats 部分依赖 B 判分产物）
- [x] D1 stats.py --baseline/--candidate 接线+ci.sh 替换+文案清理
- [x] D2 --repeat=3 一致闸（verdict/8态/分差≤1→k_pass 率）
- [x] D3 runner 文件锁（PID+stale 30min）
- [x] D4 tool_matrix.py 矩阵脚本
- [x] D5 金标重算 dry-run 演练脚本+SOP 挂钩
- [ ] D6（可选）EVAL_STATUS 自动摘要

## Wave1 附注（10-14 主线采信）
- sub-A 偏差采纳：compose 本就 restart:always 不改；**writer 真路由=POST /api/public/scores+Basic pk:sk**（explore"legacy 201"已过时，实测 v4.50.0）；traceId 查本机 ClickHouse（public traces 404）凭据进 langfuse.json（gitignored）；G4=env 方案实证（LANGFUSE_TRACING_ENVIRONMENT 优先于文件）；prism.py env=全量继承制
- sub-B1 偏差采纳：truth 18 题/34 锚（缺口/范式/top3 题不放硬锚防假阴）；既有 22 题无结构化金标不编造；run_id 沿用 EVAL_RUN_ID 防双轨
- **wave2 派单增项**：trap-09/10 判分（prompt_injection/prompt_leak 分支，测试先行）+ truth_check.test 进 npm scripts + 验收口径 --only=trap 改 10/10 + B1-6 month 描述删参
- 观察项：runner 对"回复正文无 supported_by 字样"判 2 分（sales-12/13 联调）——证据正则过严，B4/首跑校准关注

## Wave2 附注（10-14 主线采信）
- sub-B2 亮点：G6 关闭（真实两轮实验：trajectories 逐轮记 verdict，双通道一致）；web 工具真名纠错（web_fetch 不存在，第4= get_search_content）；PTC fixture 录制+回放零外呼（录制内容证实"公开资料一致表述热泵空调+高压PTC标配"——用户 T7 有 PTC 断言获 web 佐证）；成本台账真值（34,081 tokens/$0.000649）
- b2 偏差采纳：fixture 走 tool 层（插件 realm fetch 补丁不可达，实证）；EVAL_WEB 缺省 off 判据=PRISM_TRAJECTORY_FILE 已注入（生产零影响）；trap-09 量词修假阳（"核对"撞"对"）；trap-09 判分单源 trap 分支（摘 truth.forbid 防双罚）；8态用签名占位（B4 切 scorer 时替换）
- cd 定位：verifyNames 真身=src/verify/grounding.ts:116 共享层；金标重算=字面量生成器**人工重测字面量**（SOP 第4步钉死）；生产网关 9200 待重启吃 mapEvent（Step9 统一）
- 观察项延续：证据正则过严（score=2）→ Step7 审查项+首跑校准

## Step6-10
- [x] Step6 simplify（并入 Step8：summarizeRun/default_tolerance/重复行 3 删 2 记）
- [x] Step7 code-review **隔离子代理**（1P0+4P1+8P2+4简化；smoke:all 实跑全绿；G1/G6 独立复核过）
- [x] Step8 receiving-review（P0/P1 全修+P2 修5记3+简化修3记1；review-response.md 落盘；**rubric 12 题挂载**）
- [ ] Step9 验收总表（design 末节 10 项）+ **60 题首跑（v1 基线一次成型）**
- [ ] Step10 archive + 方案 §10.0.1 勾进度 + EVAL_STATUS 激活
