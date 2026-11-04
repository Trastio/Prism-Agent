# Brainstorming: Collector Extensions

## 背景

Phase 1-4 Code Review 遗留 3 个 Important 级别改进项：
1. Anspire 数据源未接入（目前新闻采集仅有 Tavily + Bocha）
2. 头条指数 + 谷歌指数方法未实现（gopup 仅采集百度 + 微博）
3. 所有 collector 和 scheduler 无日志，排查问题困难

## 需求澄清

**Q: 这 3 项是新增功能还是补全已有设计？**
A: 补全。OpenSpec spec 已定义了多源新闻采集和多指数采集，Phase 1 实现时只完成了核心路径，留了扩展点。Code Review 标记为 Important。

**Q: 改动范围？**
A: 纯扩展，不改架构。只涉及 3 个文件 + 对应测试：
- `pipeline/collectors/news_collector.py` — 加 search_anspire + logging
- `pipeline/collectors/gopup_collector.py` — 重构为 _collect_index_sync + 加 toutiao/google + logging
- `pipeline/scheduler.py` — 加 logging + _store_index_data 改 *args 接收多源指数

**Q: 技术方案？**
A:
- Anspire: 同 Tavily/Bocha 模式，httpx POST，返回统一 `{title, content, url, author, published_at, source, platform}` 格式
- 头条/谷歌指数: gopup 已有 `gp.toutiao_index` 和 `gp.google_index` API，提取 `_collect_index_sync` 通用方法消除重复
- Logging: 标准 `logging.getLogger(__name__)`，三级：debug（请求/响应细节）、info（结果摘要）、warning（失败）

## 决策

| 决策点 | 结论 | 理由 |
|--------|------|------|
| Anspire 接口格式 | 复用 Tavily/Bocha 的返回格式 | 统一处理，search_all 可直接 gather |
| gopup 重构策略 | 提取 `_collect_index_sync` 通用方法 | 4 个指数方法逻辑 90% 相同，消除重复 |
| scheduler _store_index_data | 改为 `*data_sets: list[dict]` 可变参数 | 未来加新指数源不用改签名 |
| logging 级别 | debug/info/warning 三级 | debug 看请求响应细节，info 看摘要，warning 看失败 |

## 输出

- 设计文档: `docs/superpowers/specs/2026-05-22-collector-extensions-design.md`
- 实施计划: `docs/superpowers/plans/2026-05-22-collector-extensions.md`（7 tasks）
