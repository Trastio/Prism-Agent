# 隔离审查报告 · 极性引擎切换 DeepSeek

**审查日期**：2026-10-20　**审查者**：隔离子代理（fork 型，独立从代码推导，未参与施工）
**审查范围**：proposal.md 所列 8 个文件（batch_runner 三方法 / deepseek_polarity.py / dashboard 可用性 / conftest / 夜跑脚本 / index.html 方法论一行 / 新测试 / 实验脚本）
**验证执行**：`python -m pytest tests/test_deepseek_polarity.py -q` → **16 passed in 0.68s**（全 mock 零外呼）

## 结论

**P0 = 0　P1 = 1　P2 = 6**

数据红线（绝不覆盖已有值）**成立**，fail-soft 主语义**成立**，测试非假绿（真实内存库 + 引擎 mock 恰当）。唯一 P1 是 `.secrets` 默认路径解析错一层目录，工位机被 pi-auth 兜底掩盖，按 proposal 的上云建议配置时会失效。

---

## P1（功能错误）

### P1-1：resolve_api_key 默认 .secrets 路径错一层目录——文档化的 key 来源实际不生效

**证据**：
- `pipeline/analysis/deepseek_polarity.py:38-39`：`secrets_path = str(Path(__file__).resolve().parent.parent / ".secrets")`。`__file__` 位于 `prism-sentiment/pipeline/analysis/`，`parent.parent` = `prism-sentiment/pipeline/` → 默认查找 **`prism-sentiment/pipeline/.secrets`**（磁盘上不存在，实测 `ls` 确认）。
- 项目规范位置是**仓库根** `prism-sentiment/.secrets`：磁盘存在（672B）；`utils/config.py:5` `_SECRETS_PATH = os.getenv("SECRETS_PATH", ".secrets")`（根相对）；**同 change 的实验脚本 `scripts/deepseek_polarity_experiment.py:55` 算的是根**（scripts/ 的 parent.parent = 仓库根）——实验脚本与引擎模块对同一来源的定位互相矛盾，坐实引擎模块算错。

**复现推理**：工位机上 env 无 key、`pipeline/.secrets` 不存在（except 吞掉）→ 落到 pi-auth（`~/.pi/agent/auth.json`）→ 有 key，症状被兜底掩盖。但 proposal §连带效应明文"上云前建议把 DeepSeek key 写入 .secrets"——运维按文档把 key 写进根目录 `.secrets`（既有的、utils/config 同款文件）后，引擎仍读不到 → `tag_polarity_batch` 抛 `DeepSeekPolarityError("config: 未找到 DeepSeek key")` → 所有批次 fail-soft 跳过、覆盖率再次归零，且 dashboard `comment_model_available=False` 恰好提示了不可用，容易误诊为 key 写错而非代码路径错。

**测试为何没抓到（假绿缺口）**：`test_key_secrets_then_auth`（tests/test_deepseek_polarity.py:30-44）全部走**显式注入路径参数**，默认路径分支从未被任何测试执行。

**修法建议**：`parent.parent.parent` 或复用 `utils/config.py` 的 `_SECRETS_PATH` 语义（根锚定），并补一条不注入路径、monkeypatch 根 `.secrets` 的默认路径测试。

---

## P2（健壮性/风格，非阻塞）

### P2-1：gather 首异常后兄弟任务不取消，客户端在其脚下被关闭

**证据**：`deepseek_polarity.py:116-117` `async with httpx.AsyncClient(...) as client: return list(await asyncio.gather(...))`（无 `return_exceptions`）；重试 catch 元组在 `:109` 只含 `TimeoutException/TransportError/HTTPStatusError`。
**推理**：任一任务抛 `DeepSeekPolarityError`（如 401）→ gather 立即上抛 → `async with` 退出触发 `client.aclose()`，**仍在飞/在退避的兄弟任务继续跑**：在关闭的 client 上重发 → `RuntimeError`（不在 catch 元组）→ 孤儿任务带未取回异常死亡（"Task exception was never retrieved" 日志噪声），期间白烧 API 配额（每孤儿最多 3 次×退避）。**无死锁/无信号量泄漏**（每次调用新建 Semaphore，孤儿自然消亡），**fail-soft 数据语义不受影响**（异常先于任何写库）。属资源浪费+日志噪声级。

### P2-2：fail-soft 只捕 DeepSeekPolarityError，200-非 JSON 响应可逃逸契约

**证据**：`batch_runner.py:433-438` 仅捕 `DeepSeekPolarityError`；`deepseek_polarity.py:77` `resp.json()` 在 200+畸形体（代理错误页等）时抛 `json.JSONDecodeError`，不在 `one()` 的重试 catch（`:107-111`）内 → 穿透 gather → 穿透 `run_comment_analysis`。
**推理**：违反"批级失败 log+break 留队列"的字面契约，但上游 `analysis.py:49-53`、`collection.py:99-103` 均有 broad try/except 兜住 → 服务不崩；且"先 API 后写库"保证当批零写入仍成立。建议 `_post_one` 把 200 解析包进 try 转 None 或 DeepSeekPolarityError。

### P2-3：POLARITY_ENGINE 值不校验，任意串静默路由 deepseek（fail-open）

**证据**：`batch_runner.py:402-405`、`dashboard.py:261-264`——仅 `== "local"` 判 local，其余（含拼写错误 "deeepseek"/"qwen"）全部走 deepseek。
**推理**：想回退 local 却拼错 env 的运维会在不知情下烧 API 配额。两处读法一致（同一逻辑），不产生分裂行为，故 P2 非 P1。

### P2-4：测试缺口清单（语义未钉死处）

- **默认 secrets 路径零覆盖**（P1-1 的假绿根因，tests/test_deepseek_polarity.py:22-44 全部注入路径）。
- **zip 长度不等无守卫无测试**：`batch_runner.py:439` `zip(valid, batch_results)`——引擎契约保证等长（gather 语义），但若 mock/未来实现返回短列表，缺的行静默落 "none" 哨兵（`pols.get` 返 None）= 数据被不可逆标记。建议加 `assert len(batch_results) == len(valid)` 或测试钉死。
- **429 可重试未测**（只测了 500 与 401）；**gather 部分任务永久错路径未测**（P2-1 场景）；**key 文件 JSON 损坏未测**（只测了文件不存在）。
- cap 批粒度边界（cap=600 一次跑 1000 超额 400）未测——docstring 已声明"批粒度检查（整批跑完才判）"，属已知设计而非缺陷。

### P2-5：conftest teardown pop 而非恢复原值

**证据**：`tests/conftest.py:69-73` 直接 `os.environ.pop`，若运维带着 `POLARITY_ENGINE=xxx` 跑 pytest，原值被销毁（沿袭既有 TAG_IN_SERVICE 同款写法，非本 change 引入的风格）。
**顺序核验（问题 8 结论）**：autouse fixture setup 先于 test body 的 `monkeypatch.setenv` → 测试内 deepseek 覆盖生效；teardown 反序（monkeypatch 先恢复 "local"，fixture 后 pop）→ 终态干净。全仓 grep 确认除本测试文件外无测试设 POLARITY_ENGINE，**无交叉污染**。

### P2-6：test_availability_local_unloaded 近恒真式断言

**证据**：`tests/test_deepseek_polarity.py:274` `assert dash._check_comment_model_available() is LocalABSAModel.get()._loaded`——等价于断言函数返回它自己引用的值。仅在"误走 deepseek 分支且本机真能解析到 key"时才能失败（工位机成立、别处未必）。能过但区分度弱。

---

## 必查清单逐条结论

| # | 项 | 结论 | 关键证据 |
|---|---|---|---|
| 1 | **数据红线** | **PASS** | 两引擎路径同 WHERE（`batch_runner.py:424-425`）：`or_(pol IS NULL, pol='')` **AND** `or_(dim IS NULL, dim='')`——两列皆空才入选；'none' 哨兵行/老 dim 行（`dim='{"动力": 1}'`）均不匹配，永不重选。deepseek 路径只写 `comment_polarity`（`:443`），不碰 `dim_sentiment`。全仓生产写点仅 batch_runner 两处（grep `.comment_polarity =` 证实）。测试 `test_engine_routing_deepseek` 用真库钉死 c-old 不动（:198-199） |
| 2 | **fail-soft 语义** | **PASS**（P2-2 例外类除外） | 先 API 后写（`batch_runner.py:432-434`）；`DeepSeekPolarityError` → break 在任何赋值之前（`:435-438`）→ 当批**零写入含空内容哨兵**；批内 all-or-nothing（gather 契约：全列表或抛）；部分成功=不可解析 None→哨兵（测试 :229 钉死），耗尽=整批丢弃不半写（测试 :207-215 钉死 n=0 全 NULL） |
| 3 | **重试与并发** | 4xx 永久错**不**重试（PASS，`:107-108` `except DeepSeekPolarityError: raise`，401 有测试 :76-77）；重试仅 Timeout/Transport/HTTPStatusError（429→raise_for_status→HTTPStatusError→重试），退避 2s/4s。gather 兄弟泄漏=P2-1（无死锁、无信号量泄漏、不影响数据语义） |
| 4 | **路由完整性** | **PASS** | 调用方全枚举：`analysis.py:49-53`（try/except Exception）、`collection.py:99-103`（同）、`scripts/run_comment_tagging.py:43`（引擎错已被 fail-soft 吞，意外错崩溃=手动脚本可接受）。`DeepSeekPolarityError` 不会逃出 `run_comment_analysis`。延迟变化：首轮回填 ~4k 条在并发 20 下约分钟级、跑在后台任务 Phase 6 内——proposal 明文要此行为，属设计而非缺陷 |
| 5 | **引擎耦合点** | **PASS 无漏改** | 全仓 grep `local_absa/LocalABSAModel/TAG_IN_SERVICE`：`analyzer.py:9` 仅 import ALL_DIMENSIONS（维度白名单，非引擎）；clean_dim_sentiment.py / absa_throughput_test.py / 两个实验脚本均为离线工具；dashboard 可用性已双引擎化；无健康检查/启动逻辑引用本地模型 |
| 6 | **key 安全** | **PASS** | key 仅进 Authorization 头（`:75`）；异常文本只含状态码+服务端响应体前 120 字符（`:81`）与 httpx 异常（不含头）；来源名可打（实验脚本 :169 "内容不显示"）；dashboard 返回 bool；batch_runner 丢弃来源不落日志 |
| 7 | **测试质量** | 总体**真实非假绿**：batch_runner 四测用真 SQLite 内存库（StaticPool），mock 只打引擎边界（`dp.tag_polarity_batch` 模块级替换 + 方法内 inline import 恰好取到 patched 属性）；重试次数钉死 calls==3（:108）。缺口见 P2-4 |
| 8 | **conftest 钉 local** | **PASS 无污染**（顺序核验见 P2-5；全仓仅新测试文件显式 setenv deepseek） |
| 9 | **dashboard 可用性** | **PASS** | env 调用时读（`:261`，符合 T3 教训）；deepseek 分支文件不存在/JSON 损坏 → resolve 内 `except Exception` → ("", "none") → False，无抛出路径（`:40-55`） |
| 10 | **实验脚本指标** | **PASS 无方向性错误** | 混淆矩阵行=微调 列=DS 且键名自述（:199, :226）；负面召回 P(DS=-1\|ft=-1)（:222, :232）方向正确；负面扩张精度 P(ft=-1\|DS=-1)（:223, :233）正确；kappa 标准 po/pe + pe==1 守卫（:154-161）；分层按库内真实比例 seed=42；仲裁 A/B/C 分桶过滤条件正确（:241-245）；成本公式与单价声明一致。微瑕：末次失败后仍多睡 6s（:150）；`d not in arb` O(n²) 字典等值——40 条量级无碍 |

## 范围纪律备注

- `frontend/index.html` 为并行会话共享 dirty 文件（diff 16 hunks/~190 行）：本 change 仅"分析管线"一行（:450，已核对含断点标注"2026-10-20 前为本地 Qwen3-4B，跨引擎趋势不作对比"）；KPI title 等其余 hunk属并行会话，未审。
- `batch_runner.py` diff 证实：local 路径**只重命名+docstring**，方法体零改动——回退路径无回归面。

## 处置建议

- **P1-1 必修**（上云前；工位机当前被 pi-auth 掩盖，越晚修越容易在别的机器上炸成"覆盖率再次归零"的哑故障）。
- P2-1/P2-2 建议随手修（gather 加 return_exceptions=True 语义重组 / _post_one 包 JSON 解析）；P2-3/P2-4/P2-5/P2-6 记录在案，可并入下一轮。
