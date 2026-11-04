# 极性引擎切换 DeepSeek（轻量十步）

**日期**：2026-10-20　**状态**：施工中　**拍板**：用户（"全自动化，不需要人工抽检，直接使用 v4 flash"）

## 起因

评论极性打标（comment_polarity）由本地 Qwen3-4B LoRA 承担，2026-10-17 起 TAG_IN_SERVICE 门默认关（防凌晨自动轮拉起模型占显存）→ 无人夜跑 → **覆盖率掉到 35-54%**（运维遗留②）。微调模型同时是舆情面留工位机的唯一 GPU 理由（Prism 上线方案 D3 拍板"本地夜跑常态化"）。

## 切换依据（前置实验，scripts/deepseek_polarity_experiment.py）

- 1000 条分层对比（seed=42 可复现）：总一致率 69.5%，负面召回 57.6%，kappa 0.52
- 分歧抽样读数：扣分项主要是微调的错——话题触发误报（提"安全/异响"即判负）、隐性负面漏检（"同款一样的问题"判中性）、反讽误读（"除了耗轮胎没啥毛病"判负）；DeepSeek 口径负面占比 31.5%→24.7%（微调虚报佐证）
- **未做人工仲裁**（用户拍板全自动直切）；40 条仲裁样本留档未用（scripts/polarity_arbitration_sample.md）
- 工程冒烟：deepseek-v4-flash 直连可用，thinking 成功关闭（每条 1 词元输出），实测成本 ¥0.07/千条

## WHAT

| # | 内容 | 文件 |
|---|---|---|
| 1 | 新引擎模块：DeepSeek 极性打标（key 解析 env>.secrets>pi-auth、并发 20、重试 3、thinking off） | pipeline/analysis/deepseek_polarity.py（新） |
| 2 | 打标入口引擎路由 POLARITY_ENGINE=deepseek(默认)/local；deepseek 路径不走 TAG_IN_SERVICE 门（无 GPU 依赖，治覆盖率根因）；批级失败 fail-soft 留队列；单次上限 DS_POLARITY_MAX_PER_RUN=5000 | pipeline/analysis/batch_runner.py |
| 3 | 降级字段引擎化：deepseek=key 可解析 / local=模型已加载 | api/routes/dashboard.py _check_comment_model_available |
| 4 | conftest 钉 POLARITY_ENGINE=local（存量测试走老路径不碰网） | tests/conftest.py |
| 5 | 手动夜跑脚本适配引擎（默认 deepseek） | scripts/run_comment_tagging.py |
| 6 | 方法论文案 + 口径断点标注 | frontend/index.html:448 |
| 7 | 新测试（全 mock 零外呼）：key 解析顺序/解析映射/重试/fail-soft/队列哨兵/上限/降级字段 | tests/test_deepseek_polarity.py（新） |

## 口径断点（as_of 纪律）

**2026-10-20 起 comment_polarity 由 DeepSeek v4-flash 判定，此前为本地 Qwen3-4B 产出。** 跨引擎趋势不作对比（看板"评论负面占比"线在断点前后量级有系统性偏移：实验测得负面占比约 -7pp）。老评论（有 dim_sentiment）永不重标（既有队列语义），极性轨/维度轨双轨口径不变（post_utils.derive_comment_sentiment 极性轨优先）。

## 连带效应

- 运维遗留②（极性覆盖率）结构性消失：03:00 计划任务/collection Phase 6 直接打标，无需 GPU 钥匙
- 上云 GPU 障碍消失，D3（本地夜跑常态化+PAI-EAS 备胎）作废——Prism 上线方案下轮修订时回写
- 上云前建议把 DeepSeek key 写入 .secrets 或 env（当前工位机走 pi-auth 兜底）

## 验收

1. 新测试全绿 + 存量套件零回归（pytest，存量 test_cache_bust 挂除外）
2. 真实回填一轮：两列皆空积压（~4k 条）打标完成，覆盖率显著回升（前后计数落档）
3. Step7 隔离子代理审查（fork 型），P0/P1 全处置
4. 前端方法论文案核对（断点标注可见）
