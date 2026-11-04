# review-response · 隔离审查处置表（G-5 Step8，2026-10-27）

> 对象：《审查报告.md》（0 P0 / 3 P1 / 10 P2）+ 工单修复清单（3 P1 + P2-1/2/4 + D5 分级拍板 + 单测同步）。
> 施工者=Step8 子代理（与审查者无关）。处置范围仅 `eval/quality_judge.mjs` + `eval/quality_judge.test.mjs`；
> 未跑 runner、未碰 .runner.lock / .pi/extensions* / tasks.json、未 commit、未起停服务。

## 一、审查项处置表

| 审查项 | 处置 | 落点与证据 |
|---|---|---|
| **P1-1** sidecar 跨槽指纹失效 | **修复**。选型=**指纹变更清空整个 by_judge**（非每槽自存指纹）：全局 prompt_fingerprint 是案卷唯一权威，只清当前槽必留"他槽旧 prompt 分被新 prompt 复用"缺口（审查复现序列成立）。代价=他槽缓存分与 usage 一并作废（本就属旧 prompt 理应重判；顺带修复 P2-⑩"跨版本混计 token"）；slot 另记 `prompt_fingerprint` 仅供取证。 | judgeBatch 选型注释 + `if (fresh) sidecar.by_judge = {}`。**生产实证**：v4→v5 指纹变更后 sidecar.by_judge 仅剩 Kimi 槽（GLM 槽整体消失），非只清当前槽 |
| **P1-2** repeat 维坍缩 | **修复**。`addrOf(row)=task#repeat` 导出寻址键；judgeBatch 按 entries=[{task,repeat}] 逐行寻址+缓存键 `task#repeat`；--post 的幂等 id/repeat/traceId 逐行取（`mainByAddr`）；selectGaps 主分按行；汇总分行数/题数双列。 | sidecar 现存缓存键全部 `cross-02#1` 形态；单测 addrOf+selectGaps 同名异 repeat 互不串两例。runner L784 同名多行报告（v1.3 219 行）从此逐行判、逐行绑 trace |
| **P1-3** 解析失败重试未实现 | **修复（选实现，非改注释）**。judgeTask 内 parse 失败 → 同候选链重召一次（callJudgeOnce 内含传输层重试），仍非法才弃（null_reason='解析失败（重试一次后仍非法 JSON）' 如实分层）；callJudgeOnce 注释改为如实声明"只管传输层，解析层重试在 judgeTask"。 | 单测两例：首答非法次答合法=恰好 2 次调用且出分；两答均非法=null 且不再有第三次调用 |
| **P2-1** parseJudgeJson 强转洞 | **修复**。维度只收真整数或 `"0"/"1"/"2"` 串（trim 容忍）；confidence 只收有限数 0-1（数字或非空数字串）；null/true/''/缺维一律 null。 | 单测 8 断言（d3:null/true/''→null；confidence:null/true/''→null；数字串容忍保留） |
| **P2-2** 模板 $ 模式注入 | **修复**。三处 `.replace('{x}', () => value)` 函数式替换。 | 单测：question/reply 含 `$&`、`` $` ``、`$'` 实序列断言 userText 原样保留、占位符全替换 |
| **P2-4** 两处空转单测 | **修复**。judgeTask 增第 4 参注入口 `callFn = callJudgeOnce`（生产路径不传，默认真实调用）；confidence 闸 / API 耗尽 / 解析重试 / $ 注入 6 例全部走 judgeTask 真路径、断言函数输出（含"恰好 1/2 次调用"外呼计数）；假脚手架（fakeJudge/calls）删除；手写字面量等价判定测试删除。 | 单测 15→**22 例全绿**（零外呼，~100ms） |
| **P2-⑩** v1/v2 正文不可复算 | **处置（如实，非复原）**。v3/v4 全文程序化留档 `PROMPT_ARCHIVE`（拼接自改动前模块导出，byte-exact；指纹按现行哈希输入复算=03786cb8/4bcfbcdf，机械验证入单测）。v1/v2 无法恢复（文件 untracked 无 git 史、sidecar 仅存指纹）——`PROMPT_ARCHIVE.lost` 如实声明"正文未留档不可复算"，**不事后重构伪造**（红线#1）。v5 起版本史逐版留档。 | 单测：archive.v3 复算指纹=03786cb8；lost 条目断言无 system 字段+note 含"不可复算" |
| P2-5（顺带，不在工单清单） | **修复**。spearman 单测注释算术改为审查核实值（d=[3,-1,-1,-1,0,0,0,0] Σd²=12→ρ=0.857），并补 Σd²=20→0.762 的真断言（原"错 4 位=0.81"无对应断言）。 | 单测 spearman Σd² 预算例 |
| P2-3 / P2-6 / P2-7 / P2-8 / P2-9 / P2-10 其余 | **记录在案未动**（不在工单清单；P2-3 当前调用点恒等长、P2-7 属案卷计量误差、其余低危）。 | — |

## 二、工单新增项处置

| 项 | 处置 |
|---|---|
| **D5 分级改造（已拍板）** | prompt 升 **v4**：D5 三级=2 零泄漏 / 1 恰单处轻度且在辅助位置（口径小节/尾部小字/列表项末尾）/ 0 两处及以上或单处在正文主体（开篇结论/主段/标题/表格主体）；leak_scan 增加"主体/辅助"位置标注。实录验证：config-05 得 D5=1（"尾部数据时点段带系统词快照"）=教科书案例；sales-09 未如工单预期得 1——Kimi 扫出比人工锚更深的多处泄漏（retail、对象身份核验工具、降级模式、别名表，数据缺口段落），按分级语义 D5=0 站得住（锚与裁判的**事实分歧**，非语义分歧；锚不许改，如实记录） |
| 重校准 | v4 Kimi 8/8 判齐 ρ_old=-0.709；启用工单允许的唯一次措辞调整 **v5**（D4 与 length_scan 机械绑定+评分纪律 d4 自检行）重跑 → 见第三节终值 |

## 三、Step8 新发现（审查未捕获）：校准 ρ 符号朝向反了（已修）

`spearman(judgeTotals, humanRanks)` 的两个输入"好"的方向相反（总分高=好，人工序号小=好），**完美一致的裁判会得 ρ=-1**，而 pass 条件 `rho >= 0.7` 使完美裁判也恒 FAIL。v1-v4 轮（含 W1-W3 施工报告的"5 轮全 FAIL"）均按此反号口径判读——**|ρ| 才一直是真实吻合度**。修复=`-spearman(...)`（+1=与人工序完全一致，输出行注明）。历史轮以 sidecar rounds 原始分复算修正值：

| 轮 | 裁判 | rho_old（反号口径） | **rho_corr** | ≥0.7 |
|---|---|---|---|---|
| v1' | GLM-4-flash | -0.733 | **0.733** | 是（数值过，但漏扫实锤泄漏=事实层不合格，见下） |
| v2 | GLM-4-flash | -0.732 | **0.732** | 同上 |
| v3 | GLM-4-flash | -0.491 | 0.491 | 否 |
| v3 | Kimi-k2.6 | -0.546 | 0.546 | 否 |
| v4 | Kimi-k2.6 | -0.709 | 0.709 | 是（贴线） |
| **v5（终）** | **Kimi-k2.6** | — | **0.761** | **是 → PASS（exit 0）** |

注：v1'/v2 GLM 数值过线不推翻"GLM 不配当质量裁判"结论——D5 是本 rubric 核心，GLM 对已核验实锤泄漏（sales-09 降级模式@648）连 v4 分级语义下仍给 D5=2（Step8 预检轮实录），漏扫=事实判读不合格，与排序数值无关。

## 四、基建参数修复（非 prompt，不耗措辞预算）

- Kimi maxTokens 4000→8000：v4 位置标注使推理链变长，4000 被 reasoning 挤爆致 4/8"空回复"弃用（成功请求 completion≈3.5K 贴顶）。
- Kimi timeoutMs 150s→240s：高负载时段（k3.1-pro 持续 429）最长回复 150s×3 超时弃用。
- 两项均不进 prompt 指纹（指纹只覆盖 version+system+user_template）。

## 五、遗留（如实记录，不在本工单处置）

1. **中段坍缩仍在**：v5 终轮 sales/reviews/sentiment/social 四题同分 10（并列平均秩救了 ρ）；工单"预期坍缩解除"仅部分成立（顶部/底部锚定够了，中段分辨力仍弱）。
2. **Kimi D4 长度感知不稳**：skill-01 与 social-01 同为 ~3.2K，前者 D4=1（"约3200字偏长"）后者 D4=2——v5 机械绑定措辞未完全根治，成对 badcase。
3. 锚 vs 裁判事实分歧：sales-09 人工锚按"单处泄漏小扣"排第 3，Kimi 扫出多处（数据缺口段 retail/对象身份核验/降级模式/别名表）给 D5=0。锚不许改；若未来锚更新可复核该题。
4. GLM 裁判资格维持否定（漏扫+顶部分辨力为零+今日 D5=2 漏扫再证）。
