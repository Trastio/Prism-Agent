# 隔审处置（Step8）

隔审：fork 型子代理，0P0 / 1P1 / 6P2，报告见 review.md。处置如下：

| # | 发现 | 处置 |
|---|---|---|
| P1-1 | resolve_api_key 默认 .secrets 路径差一层（parent.parent → pipeline/.secrets，应为仓库根）；工位机被 pi-auth 兜底掩盖，上云写 .secrets 后会哑失败（打标全跳过、覆盖率归零） | **已修**：parents[2] 锚定仓库根（_DEFAULT_SECRETS 常量）+ 钉子测试 test_default_secrets_path_is_repo_root |
| P2-1 | gather 首异常后兄弟任务不取消、client 在其脚下关闭；RuntimeError 不在重试 catch | **已修**：gather(return_exceptions=True) 等全部落地后聚合判异常，非契约异常包成 DeepSeekPolarityError；测试 test_batch_permanent_error_among_successes |
| P2-2 | 200+非 JSON 体抛 JSONDecodeError 穿透引擎契约 | **已修**：_post_one 内 catch ValueError → DeepSeekPolarityError |
| P2-3 | POLARITY_ENGINE 任意非 local 串静默路由 deepseek（拼写错 fail-open） | **已修**：非法值 log warning 再按 deepseek（不再静默） |
| P2-4 | 测试缺口：默认路径零覆盖 / zip 短列表无守卫（短列表尾部静默落 "none" 哨兵=不可逆） | **已修**：路径钉子测试 + batch_runner 长度守卫（长度不等=契约破坏跳过本批）+ test_engine_short_result_leaves_queue。429/gather 部分永久错/key 文件损坏三支未单测（P2-1 机制已覆盖传播路径），记录 |
| P2-5 | conftest teardown pop 而非恢复原值 | **记录**：沿袭 TAG_IN_SERVICE 既有写法（fixture 先于 monkeypatch 恢复，顺序核验安全）；若未来有测试依赖外部预设 POLARITY_ENGINE 再改恢复语义 |
| P2-6 | test_availability_local_unloaded 近恒真断言 | **已修**：先断言 _loaded is False 再断言结果 is False |

修复后全量回归：**927 过 / 1 挂**（test_cache_bust 存量挂，非本 change）。

## 未入库件说明

scripts/polarity_experiment_detail.jsonl（1000 条明细）不入 git——脚本 seed=42 从库内确定性重抽样可完整再生；result.json（汇总+仲裁 ID）与 arbitration_sample.md（40 条分歧样本，留档未用）已入库。
