# P0-评估锚点 · Step3.5 self-check（2026-10-13）

> 对照 design.md 逐条自查，5 Gap 全处置（3 修入设计 / 2 记为已知限制）。

**Gap1（消未知→设计更新）**：main.py:1285 `uvicorn.run(app, host='127.0.0.1', port=8002)` 端口**写死**，无 env。→ D4 定案：eval api 实例一律 `[sys.executable, "-m", "uvicorn", "main:app", "--port", "8003"]` cwd=prism-api 直拉（uvicorn CLI 参数优先级高于代码内 run，此处根本不走 `__main__` 分支）。

**Gap2（消未知→设计更新）**：smoke_m3 环境敏感断言实测仅两条——L103 `comfort.con === 313`（硬编码口碑真值）+ L89-97 `getSalesTruth('银河E5',2026).slice(0,3)` vs 固定文本 `3028/1823/6508`（销量前三月）。→ D5 定案：truth-expectations.json 两键 `koubei_e5_comfort_con: 313`、`sales_e5_2026_first3: [3028,1823,6508]`；m3[1] 的 verifyCompletion 合法 CLAIM 断言虽查库（行存在性）但属存在性检查，归稳定组边缘不动。

**Gap3（已知限制，不在 P0 修）**：eval gateway 与生产共用 `.pi/sessions/trajectories.jsonl`——并发生产流量 + eval 批跑时 readLastTrajectory"最后一条兜底"可能串。缓解：EVAL_STATUS 已册运营口径"批跑期间冻结服务操作、单进程运行"；根治在 P1 #34（sessionId 精确匹配）。P0 在 `prism.py eval start` 输出提示行。

**Gap4（已知限制）**：VACUUM INTO 期间源库高频写入（舆情采集进行时）理论上拉长导出时间但不破坏一致性；快照建议在 CAM 导入后静默期打。snapshot.py 结束打印 sha256 供复验。

**Gap5（设计澄清）**：trap_check.mjs 的 NEG_RE 与 runner L127 内联 NEG_RE 合一（trap_check 导出、runner import）——避免拒绝词表双源漂移（本题库双源的前车之鉴）。

**边界复核**：五件事均未触碰 extension/gateway/main.py 源码（D4 全 env/CLI 复用）；生产 SERVICES 与 cmd_start/stop 零改动；gate 模式零改动。改动面 = 新增 5 文件（trap_check.mjs/.test.mjs、tasks.json、truth-expectations.json、snapshot.py）+ 小改 5 文件（runner.mjs、prism.py、smoke_m3.ts、registry/smoke.ts、package.json）+ 2 处 doc（tasks_v1.ts 头注、EVAL_STATUS 指针）。
