# Collector Extensions: Anspire + 头条/谷歌指数 + Logging

> **STATUS: DEFERRED** — Design complete but implementation not started. Only logging was partially applied (news_collector). Anspire, toutiao/google index remain unimplemented. Revive when needed.

## 背景

Code review 遗留 3 个 Important 项：
1. Anspire 新闻数据源未实现（news_collector.py 只有 Tavily + Bocha）
2. 头条/谷歌指数未实现（gopup_collector.py 只有百度 + 微博）
3. 所有 collector 静默吞异常，无 logging

## 设计决策

**方案 C：在现有文件上扩展 + 模块级 logger。**
不拆文件、不改 import 链路，在现有文件内添加方法和日志。

## 1. Anspire 数据源

在 `pipeline/collectors/news_collector.py` 中：

- `__init__` 从 `.secrets` 读取 `anspire.api_key` → `self._anspire_key`
- 新增 `search_anspire()` 方法，与 Tavily/Bocha 同结构：
  - 无 key 返回 `[]`
  - httpx AsyncClient 请求 `https://api.anspire.ai/v1/news/search`
  - 异常返回 `[]`（加 WARNING 日志）
  - 返回格式与 Tavily/Bocha 统一：`{"title", "content", "url", "author", "published_at", "source": "anspire", "platform": "news"}`
- `search_all()` 的 `asyncio.gather` 加入 `search_anspire`
- `.secrets` 加入 `anspire.api_key` 字段（值暂空）

**注意：** Anspire API 端点和参数格式待拿到文档后调整，当前先用合理占位结构。

## 2. 头条/谷歌指数

在 `pipeline/collectors/gopup_collector.py` 中：

- 新增私有方法 `_collect_index(index_func, source_name, keyword, start_date, end_date)`
  - 封装 `asyncio.to_thread` + DataFrame 转换逻辑
  - 返回 `[{"date", "keyword", "index", "source": source_name}]`
  - 统一的 DEBUG/INFO/WARNING 日志
- 4 个公开方法委托给 `_collect_index`：
  - `collect_baidu_index` → `_collect_index(gp.baidu_index, "baidu", ...)`
  - `collect_weibo_index` → `_collect_index(gp.weibo_index, "weibo", ...)`
  - `collect_toutiao_index` → `_collect_index(gp.toutiao_index, "toutiao", ...)`
  - `collect_google_index` → `_collect_index(gp.google_index, "google", ...)`
- 现有的 `collect_baidu_index` 和 `collect_weibo_index` 重构为委托调用，行为不变

### Scheduler 侧改动

`pipeline/scheduler.py`:
- `_run_collectors` 中加入头条/谷歌指数采集调用
- `_store_index_data` 签名改为 `(self, vehicle_id, *data_sets)`，遍历合并处理
- 返回的 dict 带 `source` 字段，可区分不同指数来源

## 3. Logging 三级覆盖

### Collector 层

两个 collector 文件各建 `logger = logging.getLogger(__name__)`：

| 级别 | 触发时机 | 内容示例 |
|------|---------|---------|
| DEBUG | 请求发起前/响应返回后 | `"Tavily request: keyword=海豹, start=2026-01-01"`, `"Tavily response: status=200, count=15"` |
| INFO | 每次采集完成 | `"Tavily returned 15 results for '海豹'"`, `"baidu_index collected 90 data points"` |
| WARNING | except 块 | `"Tavily search failed: HTTPStatusError 500"`, `"baidu_index failed: Cookie无效"` |

### Scheduler 层

`scheduler.py` 也加 `logger = logging.getLogger(__name__)`：

| 级别 | 触发时机 | 内容示例 |
|------|---------|---------|
| INFO | 采集开始/完成 | `"开始采集 vehicle=海豹 mode=initial ranges=3"`, `"采集完成: 45 posts stored"` |
| WARNING | 单数据源失败 | `"news collector failed for 海豹, continuing with other sources"` |

### 测试文件

不改动。现有测试行为不变，不做 logging 断言。

## 改动范围

| 文件 | 改动类型 |
|------|---------|
| `pipeline/collectors/news_collector.py` | 加 `search_anspire()` + `logger` + 改 `__init__` + 改 `search_all` |
| `pipeline/collectors/gopup_collector.py` | 加 `_collect_index` + 重构现有方法 + 加 `collect_toutiao_index` + `collect_google_index` + `logger` |
| `pipeline/scheduler.py` | 加头条/谷歌调用 + 改 `_store_index_data` 签名 + `logger` |
| `.secrets` | 加 `anspire.api_key` 空字段 |
| `tests/test_news_collector.py` | 加 Anspire 相关测试 |
| `tests/test_scheduler.py` | 更新 `_store_index_data` 调用测试 |

## 不改动

- 数据库 schema（HeatMetric 表结构不变）
- 前端
- 其他 API routes
- 其他测试文件
