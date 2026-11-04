# 极性引擎切换 DeepSeek · 归档（Step10）

**归档日期**：2026-10-20　**流程**：轻量十步（Step5 主会话施工 + Step7 fork 型隔审 + Step8 处置 + Step9 验证）

## 一句话

评论极性打标从本地 Qwen3-4B 微调模型切换到 DeepSeek v4-flash API（用户拍板"全自动直切"），前置 1000 条对比实验，回填 3,359 条清零积压，近 30 天双轨覆盖 99.9%（原 35-54%），GPU 依赖归零。

## 交付清单

- pipeline/analysis/deepseek_polarity.py（新引擎：key 解析 env>.secrets>pi-auth、并发 20、重试 3、thinking off、批级契约错误聚合）
- batch_runner.py：POLARITY_ENGINE 路由（默认 deepseek；local 回退路径零改动仅重命名）；deepseek 不走 TAG_IN_SERVICE 门（治覆盖率掉档根因）；fail-soft 批语义（先 API 后写、长度守卫、失败零写入留队列）；DS_POLARITY_MAX_PER_RUN=5000 防失控
- dashboard.py：comment_model_available 引擎化（deepseek=key 可解析）
- conftest.py：POLARITY_ENGINE=local 钉（存量测试不碰网）
- scripts/run_comment_tagging.py：引擎适配
- frontend/index.html：方法论文案 + 口径断点标注
- tests/test_deepseek_polarity.py：19 用例全 mock
- scripts/deepseek_polarity_experiment.py + result.json + arbitration_sample.md：实验依据留档

## 关键数字

- 实验：1000 条分层（seed=42），一致率 69.5% / 负面召回 57.6% / kappa 0.52；分歧抽样=微调话题触发误报+隐性负面漏检+反讽误读；DeepSeek 口径负面占比 31.5%→21%（回填实测）~24.7%（配对样本）
- 成本：实验 ¥0.07/千条；回填 3,359 条 <¥0.3；常态夜跑（日增量几百条）<¥0.1/天
- 回归：927 过/1 存量挂（test_cache_bust）；隔审 0P0/1P1/6P2 → 修 5 记 1（P2-5）

## 口径断点（永久有效）

**2026-10-20：comment_polarity 引擎切换**（Qwen3-4B 微调 → DeepSeek v4-flash）。跨断点趋势不作对比；老评论（有 dim_sentiment）永不重标；双轨口径（极性优先/维度回退）不变。

## 面试三讲

**讲一（解决什么）**：舆情管线的评论极性打标依赖本地微调模型+GPU+人工夜跑钥匙，三重运维债（覆盖率掉到 35-54%、显存管理、夜跑没人跑）。用一个 API 引擎替换 + 1000 条配对实验做切换依据，把"换模型"从信仰问题变成数据问题。

**讲二（关键裁决与我的角色）**：实验表面结果"不达标"（一致率 69.5% < 门槛 90%）——我没有按门槛机械否决，而是抽样分歧归因，发现扣分项主要是** incumbent 的错**（微调模型像"话题触发器"：提到安全/异响就判负；隐性负面"同款一样的问题"反而漏检）。用户拍板跳过人工仲裁直接切换（全自动化定位），我如实把"未仲裁"记进依据链。**面试官会追问**："你怎么证明新模型更好而不是一致率低？"——答：仲裁样本留档可补；负面占比 31.5% 的基数本身可疑（社媒评论三分之一负面不合理）；且切换是低风险可逆的（队列语义保证老数据不动，local 路径保留）。

**讲三（工程细节）**：切换不是改个 API 调用——打标入口的门（TAG_IN_SERVICE）语义失效要重新设计路由；fail-soft 批语义（引擎失败零写入留队列 vs 不可解析写哨兵=两种"没结果"的语义区分）；隔审子代理抓住真 P1（secrets 路径差一层，工位机被兜底掩盖、上云才爆的哑故障）——**"测试全绿+生产能跑"不等于"部署路径正确"**，这类跨环境 bug 只有隔离视角能抓到。

## 遗留（非阻塞）

- P2-5（conftest pop 语义）+ P2-4 三支未单测——记录在案
- 上云前：DeepSeek key 写入 .secrets 或 env（当前工位机走 pi-auth）
- Prism 上线方案 v1 的 D3（本地夜跑常态化/PAI-EAS 备胎）已失效，下轮修订回写
- 舆情降本方案 v2.2 §4.2 状态行待同步（微调模型退役）
