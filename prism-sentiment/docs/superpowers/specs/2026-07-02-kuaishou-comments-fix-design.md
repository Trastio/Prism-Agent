# 快手评论采集修复设计（2026-07-02）

## 背景与问题

项目阶段审视（[[project-stage-review-2026-07-01]]）确认快手评论采集为 **P0 阻塞项**：

| 平台 | posts | comments | ratio |
|---|---|---|---|
| weibo | 375 | 8884 | 23.7 |
| douyin | 260 | 4302 | 16.5 |
| xiaohongshu | 220 | 2868 | 13.0 |
| **kuaishou** | **306** | **30** | **0.1** |

快手 ratio 0.1，是其他平台的 1/130。这也是 `comment_summary` 覆盖率（1.6%）上不去的**共同根因**——阈值已降至 3、窗口已扩至 30 天（batch_runner.py:18-19），无进一步调整空间，瓶颈在评论量本身。

## 根因（cdp_collector.py:739-805 `_search_kuaishou`）

1. 评论分支**只处理 card 0**：line 771 `if cards:` → line 775 `document.querySelectorAll('.photo-card')[0]?.querySelector('.cover')?.click()`，其余 9 张 card 的评论从不采集
2. 所有评论挂 `posts[0]` / `post_note_id="0"`（line 795-796），丢失 post 归属
3. `comments_count=0` 硬编码（line 763），无法按评论数选帖
4. `except: pass`（line 799）静默吞错，失败不可见、不可观测
5. 依赖脆弱 DOM 选择器（`.hover-tip.commentPanel`），快手改版即坏

## 目标 / 非目标

**目标**
- 快手 comments/post ratio 从 0.1 → **≥0.5**（≥5x 改善；对标 douyin 16.5 的保守版本——保守档 top-10×30 数学上约 ~1.0，不追 douyin 的 16.5）
- **评论正确归属到多个 post**（`post_note_id = photo_id` 分布非全 '0'）——本任务的核心价值，比 ratio 数字更重要
- 让 `comment_summary` 有帖可生成（快手帖每帖 ≥3 评论即可入摘要，目标 ≥5 帖达标）
- 不破坏现有 306 帖的搜索产出
- 不引入封号风险（保守档位）

**非目标**
- 不抓子评论（subComments）——ROI 低，主评论已够 LLM 摘要
- 不改搜索方式（DOM `CARDS_JS` 能用就不动）——除非 recon 证明 photo_id 无效
- 不改其他平台采集
- 不在本任务内重跑 `comment_summary`（评论修完后由 batch_runner 自然提升，单独触发）

## 关键约束（侦察结论）

- **CDP client**（cdp_collector.py:50-120）仅支持 `eval_js`/`click`/`click_at`/`scroll`/`new_tab`/`close_tab`，**无网络拦截能力**（无 `Network.*`/`Fetch.*`）→ 排除"抓包捕获"方案
- **`eval_js` 在页面上下文执行** → 浏览器自动带 cookie（含 HttpOnly）→ in-page `fetch()` 可行，douyin 的 `SEARCH_FETCH_JS`（cdp_collector.py:413）已证明此模式工作
- **快手 API 契约**（vendor/MediaCrawler/media_platform/kuaishou/client.py:180-206 已逆向，仅作参考、不改 vendor）：
  - 一级评论：`POST /rest/v/photo/comment/list`，body=`{photoId, pcursor}` → 响应 `{result:1, rootCommentsV2:[...], pcursorV2, commentCountV2}`
  - 分页：`pcursor` 从 `""` 起，`pcursorV2 == "no_more"` 终止
  - V2 字段（待 recon 锁定确切命名）：`comment_id` / `author_name` / `content` / `timestamp` / `liked_count` 等

## 设计：in-page REST fetch（镜像 douyin）

### 总体策略
用 in-page `fetch()` 调快书 REST V2 评论 API，替换脆弱的 DOM 浮层抓取。复用 douyin 已验证的"页面内 fetch + 浏览器带 cookie"模式。

### 流程
1. **搜索**（不变）：DOM `CARDS_JS`（cdp_collector.py:345）抓 ≤10 张 card，提取 `{title, author, likes_text, photo_id}`（photo_id 由 regex `upic/[^/]+/([^_]+)` 从封面图 src 抽出）
2. **建 post**（小改）：`comments_count` 不再硬编码 0；评论抓完后用 `commentCountV2`（或抓到的实际条数）回填，让下游 `select_top_posts_for_comments` 能正确选帖
3. **评论**（重写，核心）：对 top-N 帖（按 likes 排序，N=10），在搜索页 tab 内 in-page fetch 评论 API，伪代码：
   ```js
   async function fetchComments(photoId) {
     const out = []; let pcursor = "";
     while (pcursor !== "no_more" && out.length < 30) {
       const resp = await fetch('/rest/v/photo/comment/list', {
         method: 'POST',
         headers: {'Content-Type': 'application/json'},
         body: JSON.stringify({photoId, pcursor}),
         credentials: 'include',
       });
       const data = await resp.json();
       if (data.result !== 1) break;
       out.push(...(data.rootCommentsV2 || []));
       pcursor = data.pcursorV2 || "no_more";
       await new Promise(r => setTimeout(r, 1200));  // 风控节流
     }
     return out.slice(0, 30);
   }
   ```
4. **映射**：每条 `rootCommentsV2` → `_make_comment(content, author, likes, platform=KUAISHOU, post_url, post_note_id=photo_id, published_at=timestamp)`——修正"全挂 card 0"

### 取舍：搜索为何保留 DOM
- 306 帖证明 DOM 搜索可用；改 GraphQL 搜索 = 扩大改动面、风险波及工作流
- 手术式改动原则（[[karpathy-guidelines]] surgical changes）：只动坏的部分（评论路径）
- 残留风险：DOM 抽的 `photo_id` 可能不被 REST API 认 → **recon 第 1 步验证**；不认则启用回退方案

## 风控档位（已确认 A 保守）

| 参数 | 值 | 依据 |
|---|---|---|
| 评论 post 数 | top-10（按 likes） | 对标 douyin 实采规模 |
| 每帖评论上限 | 30 条 | 够 LLM 摘要（batch_runner `max_comments=30`）|
| 请求间隔 | ~1.2s | 对齐 vendor MediaCrawler 非商业学习许可"不得大规模爬取" |
| 预期产出 | ~300 评论 | ratio 0.1 → ~1.0（≥10x）；核心收益是**多帖归属**而非 ratio 绝对值 |

## TDD 与验证策略

**这是集成代码，纯单测测不了端到端。分层：**

| 层 | 可单测 | 方法 |
|---|---|---|
| JS 解析片断 | ✅ | fixture JSON 响应 → 断言解析出的评论字段 |
| Python 分页/聚合 helper | ✅ | mock pcursor 序列（含 `"no_more"`）→ 断言终止与条数上限 |
| 字段映射 → `_make_comment` | ✅ | fixture `rootCommentsV2` → 入参 |
| 端到端实采 | 集成验证 | 实跑一次（对标 douyin "8帖/250评论"），看 ratio |

**守卫测试（防回归）**：
- 现有 `tests/test_cdp_collector.py` 的 kuaishou 用例不破
- 新增：单测断言"评论 `post_note_id` 分布在多个值"（防 card-0 回归）

## 风险与回退

| 风险 | 概率 | 回退 |
|---|---|---|
| DOM 抽的 `photo_id` 不被 REST API 认 | 中 | 回退方案④：搜索改 GraphQL `visionSearchPhoto`（vendor client.py:145-165）取 canonical photoId |
| REST V2 需特殊 header（csrf/签名） | 低 | recon 探针先发现；in-page fetch 浏览器通常自动带 Referer/Origin/Cookie |
| 风控触发（412 / 封 cookie） | 中 | 保守档已对冲；失败退 1.5s 间隔 + 减 top-N |
| 响应字段名与 vendor 注释不一致（V2 改名） | 中 | recon 第 2 步锁定字段名再写解析 |
| CDP `eval_js` 超时（fetch 链路慢） | 低 | JS 内 `AbortController` 15s 超时（同 douyin） |

## 验证标准（完成定义）

1. 实跑一次快手采集，`comments/post` ratio **≥0.5**（≥150 评论，≥10x 改善）；recon 后若 photo_id 受限则给出实际可达值并说明
2. **评论 `post_note_id` 分布在 ≥5 个不同 photo_id**（非全 `'0'`）——核心防回归点
3. 全量 pytest 绿（含现有 `test_cdp_collector` + 新增守卫用例）
4. 不影响其他平台（回归跑一次 douyin/xhs/weibo smoke，ratio 不退化）

## 实现位置

- `pipeline/collectors/cdp_collector.py`
  - `KuaishouExtractor`（line 336-398）：新增 `COMMENTS_FETCH_JS` 模板（in-page fetch + 分页 + 解析），保留旧 `COMMENTS_JS` 作 fallback 或删除（plan 决定）
  - `_search_kuaishou`（line 739-805）：重写评论分支为 per-post fetch 循环
- `tests/test_cdp_collector.py`：新增 JS 解析 + 字段映射守卫用例

关联 [[project-stage-review-2026-07-01]] [[frontend-v7-fixes-2026-06-17]] [[published-at-root-fix-2026-06-29]]（侦察前置方法学）
