# 极性引擎切换 DeepSeek · 验证记录（Step9）

**日期**：2026-10-20

## 1. 测试（全 mock 零外呼）

- 新增 tests/test_deepseek_polarity.py：16 用例（key 解析顺序×3 / prompt 口径 / _post_one 解析+错误分类×3 / 重试成功+耗尽+无key / 引擎路由+队列+哨兵+不写dim / fail-soft 零写入 / 不可解析哨兵 / 单次上限0 / 降级字段×3）
- 受影响套件：test_deepseek_polarity + test_t4_polarity_direct + test_batch_runner + test_degradation_visibility = **65/65 绿**
- 全量回归：**924 过 / 1 挂**（test_cache_bust::test_index_serves_mtime_versions = 已知存量挂，与 10-16 基线同款，零回归；908→924 = +16 新测试）

## 2. 真实回填（生产库，只写两列皆空行）

| 项 | 前 | 后 |
|---|---|---|
| 待打标队列（active） | 3,359 | **0** |
| 极性行总数 | 9,875 | **13,234**（+3,359，零失败） |
| 哨兵 none | 16 | 16（新批次 0 条不可解析——解析率 100%） |
| 近 30 天 active 车评论双轨覆盖 | —（极性轨 35-54%） | **14,176/14,189 = 99.9%** |

- paused 747 条按冻结语义不动（设计内）
- 新批次分布：负 705（21.0%）/ 中 1,755（52.2%）/ 正 899（26.8%）——负面占比较微调口径（31.5%）下移，与实验预测方向一致（口径断点，非舆情变化）
- 逐车输出：Model Y 858 / 风云T7 499 / A9 646 / T11 477 / T9L 131 / QQ3 414 / A9L 149 / T9 185

## 3. 工程冒烟

- `deepseek-v4-flash` 官方 API 直连可用；`thinking: {"type":"disabled"}` 生效（completion_tokens=1/条）
- key 解析链 env > .secrets > pi-auth 实测走 pi-auth（工位机），密钥零打印
- 实验成本实测：1000 条 ¥0.07；回填 3,359 条估 <¥0.3

## 4. 口径断点（as_of）

**2026-10-20 20:00 前后**（回填执行时点）：comment_polarity 此前=Qwen3-4B 微调产出，此后=DeepSeek v4-flash 产出。看板"评论负面占比"跨断点趋势不作对比（方法论段已标注）。老评论（有 dim_sentiment）不重标，极性轨优先/维度轨回退的双轨口径不变（post_utils.derive_comment_sentiment 零改动）。

## 5. Step7 隔离审查

fork 型子代理独立审查（第 0 步工具面守卫通过），**0P0 / 1P1 / 6P2**。核心结论：数据红线 PASS（两列皆空才入选、哨兵/老行永不重选）、fail-soft 主语义 PASS、路由完整 PASS、key 安全 PASS。P1-1（secrets 路径差一层，上云哑故障）+ P2-1/2/3/4/6 已修，P2-5 记录。处置明细见 review-response.md。修复后全量回归 **927 过 / 1 存量挂**。
