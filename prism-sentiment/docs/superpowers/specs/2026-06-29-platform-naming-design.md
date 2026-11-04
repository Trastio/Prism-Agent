# 主题 B：平台命名一致性 — 设计文档

> 日期：2026-06-29
> 治根主题 B（共 7 主题）：建立单一 platform 真理源，消除缩写/全名双命名与采集层写入不一致

## 1. 背景与根因

系统存在两套 platform 命名并行：**缩写**（`xhs/wb/dy/ks`）与**全名**（`xiaohongshu/weibo/douyin/kuaishou`）。侦察发现它们并非"旧数据缩写、新数据全名"的简单共存，而是**全栈散落、且采集层自身就不一致**：

**采集层写入（CdpCollector，`pipeline/collectors/cdp_collector.py`）—— 最严重：**
- 微博写 `"wb"`（702/726/962）、快手写 `"ks"`（764/793）、小红书写 `"xhs"`（915/928/1001）
- **抖音同一个采集器混写 `"dy"`（847/876）和 `"douyin"`（861/982）** —— 这是 bug 级不一致

**层间脱节：**
- 调度层 `scheduler.py:472` 用全名 `["weibo","xiaohongshu","douyin","kuaishou"]`，575 行又做 `缩写→全名` 转换
- 分析层 `batch_runner.py:20-23`、`pipeline_state.py:43` 用全名
- `platform_strategy.py:13-16` 却定义 `全名→缩写` 映射

**查询层别名兼容是"补丁"，且四处行为不一致（`api/routes/`）：**
| 端点 | 别名处理 | 后果 |
|------|---------|------|
| `/posts` (306) | 单向 `缩写→全名` | 传全名 `douyin` 只查 douyin，**漏掉旧 dy 数据** |
| `/top-posts` (379) | 双向 `缩写↔全名` | 正常 |
| `/platform-distribution` (248) | **无** | 库内 dy+douyin 共存 → 分两组 → 前端出现两个"抖音" |
| `dialog.py` (75/82/89) | **无** | 命名不符直接查不到数据 |

**前端** `app.js` 各自维护 alias：`filteredHotPosts`(143) 缩写→全名、`platformLabel`(814) 双向；`index.html` posts 筛选 select 用全名 value(272-278)，依赖后端别名兜底。

**共同根因**：没有"单一 platform 真理源"——每个文件各自硬编码缩写/全名/映射，新增平台要改 N 处，且无法保证一致。

逐个补别名 = 头痛医头；治根 = 一个 `platforms` 模块收口所有命名真理 + 统一采集写入 + 迁移历史数据，之后查询层不再需要任何兼容代码。

## 2. 目标

1. **单一真理源**：新建 `pipeline/platforms.py`，全名为规范值，提供常量 + 映射 + `normalize_platform()` + `platform_label()`。
2. **采集层一致**：CdpCollector 一律写规范全名，消除 dy/douyin 混用 bug。
3. **数据统一**：一次性迁移历史缩写数据 → 全名；迁移后查询层删除所有别名 OR 兼容。
4. **查询层收口**：dashboard/dialog 统一用 `normalize_platform()`，删除散落的 `_PLATFORM_ALIASES`。
5. **前端收口**：后端返回统一全名后，前端 alias map 简化/删除。
6. **治根判据**：未来新增平台，只改 `platforms.py` 一处；任何端点/前端自动正确，不再可能出现漏查/重复分组。

## 3. 设计

### 3.1 `pipeline/platforms.py` — 单一真理源

置信度：高（常量模块 + 规范化函数是标准实践）。

```python
# 规范全名（canonical）—— DB 存储与 API 交互的唯一标准
XIAOHONGSHU = "xiaohongshu"
WEIBO = "weibo"
DOUYIN = "douyin"
KUAISHOU = "kuaishou"
NEWS = "news"

ALL_PLATFORMS = (XIAOHONGSHU, WEIBO, DOUYIN, KUAISHOU, NEWS)
SOCIAL_PLATFORMS = (WEIBO, XIAOHONGSHU, DOUYIN, KUAISHOU)

# 遗留缩写 → 规范全名
_SHORT_TO_FULL = {"xhs": XIAOHONGSHU, "wb": WEIBO, "dy": DOUYIN, "ks": KUAISHOU}
# 规范全名 → 缩写（仅采集器内部/历史接口需要时用）
_FULL_TO_SHORT = {v: k for k, v in _SHORT_TO_FULL.items()}

_LABELS = {XIAOHONGSHU: "小红书", WEIBO: "微博", DOUYIN: "抖音", KUAISHOU: "快手", NEWS: "新闻源"}

def normalize_platform(p: str | None) -> str | None:
    """任意输入（缩写/全名/大小写）→ 规范全名；未知值原样返回。"""
    if not p:
        return None
    pl = p.lower()
    return _SHORT_TO_FULL.get(pl, pl)

def platform_label(p: str | None) -> str:
    return _LABELS.get(normalize_platform(p), p or "")
```

- `normalize_platform()` 是查询层/前端的统一入口
- 迁移完成后 `_SHORT_TO_FULL` 仅作历史输入兜底（用户/旧数据若仍传缩写也能 normalize）

### 3.2 采集层统一写全名

置信度：高（明确 bug 修复）。

CdpCollector 所有 `platform="wb"/"ks"/"dy"/"xhs"`（13 处）→ 引用常量 `platform=platforms.WEIBO` 等。重点修复抖音 `dy`/`douyin` 混用 → 统一 `DOUYIN`。输入侧 `if platform in ("weibo","wb")`（668-674）保留兼容（接受两种输入）但写入统一全名。

### 3.3 数据迁移（治根关键）

置信度：中高（幂等 UPDATE，可重复执行；但属历史数据变更，见 §5）。

新建 `scripts/migrate_platform_names.py`：
```python
# 幂等：UPDATE raw_posts SET platform=全名 WHERE platform=缩写
for short, full in _SHORT_TO_FULL.items():
    await session.execute(update(RawPost).where(RawPost.platform==short).values(platform=full))
# 同理 AnalyzedPost / 其他存 platform 的表（plan 阶段 grep 确认全量表）
```
迁移后 DB 内 platform 仅存规范全名。

### 3.4 查询层收口

置信度：高。

迁移完成后（数据全为全名），dashboard.py / dialog.py：
- 删除 `_PLATFORM_ALIASES`（306、379 两处重复定义）
- `RawPost.platform == normalize_platform(platform)` —— 单一条件，无需 OR
- `/platform-distribution` 不再有重复分组问题
- `dialog.py` 同样 normalize

过渡安全：即使迁移前，`normalize_platform()` 把传入缩写转全名，配合迁移后数据即可正确查询（不再需要 OR 双查）。

### 3.5 前端收口

置信度：高。

后端统一返回全名后：
- `app.js filteredHotPosts` 的 alias map（143-146）可删 —— 数据已是全名，tab 全名直接匹配
- `platformLabel`（814）简化为全名→中文（缩写分支可删，或保留作防御）
- `index.html` posts select（272-278）已用全名 value，无需改

## 4. 改造范围

| 层 | 文件 | 改动 |
|----|------|------|
| 新增 | `pipeline/platforms.py` | 真理源模块 |
| 采集 | `pipeline/collectors/cdp_collector.py` | 13 处写入改全名常量；修 dy/douyin 混用 |
| 迁移 | `scripts/migrate_platform_names.py` | 幂等缩写→全名 UPDATE |
| 查询 | `api/routes/dashboard.py` | 删 2 处 `_PLATFORM_ALIASES`，用 normalize_platform |
| 查询 | `api/routes/dialog.py` | 3 处 == 改 normalize |
| 采集 | `pipeline/collectors/platform_strategy.py` | 引用常量替换硬编码映射 |
| 调度 | `pipeline/scheduler.py` | 472/575/594 引用常量 |
| 分析 | `pipeline/analysis/batch_runner.py` | 20-23 引用常量 |
| 前端 | `frontend/static/js/app.js` | 删/simplify alias map |

## 5. 兼容与迁移策略（治根点）

- **数据迁移是治根的关键一步**：不做迁移则永远要带别名 OR 兼容（非治根）。迁移幂等可重入，风险低。
- **不可逆性**：UPDATE 改历史 platform 值。缓解：迁移脚本只做缩写→全名（无信息损失，缩写与全名一一对应），跑前可 `SELECT DISTINCT platform` 确认现状，跑后核对。**属数据变更，plan 阶段执行前需服务在线 + 用户知情。**
- **过渡期零中断**：先部署 normalize 代码（兼容缩写输入）→ 再跑迁移 → 最后删 OR 兼容。任一时刻查询都正确。
- **news 平台不涉及**（单一值，无缩写）。

## 6. 验证

后端有 pytest 基建：
1. `platforms.py` 单测：normalize 各种输入（缩写/全名/大小写/None/未知）→ 规范全名
2. 迁移脚本：建含缩写+全名+dy/douyin 混用的测试数据 → 跑迁移 → `SELECT DISTINCT platform` 仅剩全名
3. dashboard 端点测试：迁移后传 `douyin`/`dy` 均能查到抖音全部数据；platform-distribution 无重复
4. 实采验证（CDP/服务在线）：触发一次抖音采集 → 确认新数据 platform 全为 `douyin`（无 dy）

## 7. 涉及文件

- 新增：`pipeline/platforms.py`、`scripts/migrate_platform_names.py`
- 修改：`pipeline/collectors/cdp_collector.py`、`pipeline/collectors/platform_strategy.py`、`pipeline/scheduler.py`、`pipeline/analysis/batch_runner.py`、`api/routes/dashboard.py`、`api/routes/dialog.py`、`frontend/static/js/app.js`
- 测试：`tests/test_platforms.py`（新增）

## 8. 非目标（YAGNI）

- 不引入 Platform Enum（字符串常量 + normalize 函数已够，避免过度抽象）
- 不改 DB schema（platform 仍是 TEXT；只是值统一）
- 不做 platform 枚举校验约束（normalize 对未知值原样返回，宽松兼容）
- 不重写采集器结构（只改写入的 platform 字面量）
- news 平台不动
