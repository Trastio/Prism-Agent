# P0-评估锚点 · Step10 archive（2026-10-13 归档）

> 十步全部走完。change 目录：`openspec/changes/P0-评估锚点/`（explore / proposal / design / self-check / tasks / review-response / verification / archive 八件）。

## 一句话

给评估链装上三个锚——判分可信（trap 正则修正）、考卷唯一（题源合一）、考场可重置（快照+eval 专用端口）——并用 `--only=trap` 实跑当场翻案：r3 的 trap-04/05/06"未拦截"确系旧判分假阴性，agent 防线一直有效。

## 交付物

**新增 5 文件**：
- `eval/trap_check.mjs` — trap 判分纯函数（verdictFail 首要 + 方向化正则；NEG_RE 单源导出）
- `eval/trap_check.test.mjs` — 12 test / ~25 断言正反例契约（进 smoke:all）
- `eval/tasks.json` — 18 题唯一机器源（schema 含 snapshot_id/set/judge_rubric 三新字段）
- `eval/truth-expectations.json` — 环境敏感真值期望外置（月更只改 json 不改码）
- `eval/snapshot.py` — 快照工具 create/list（VACUUM INTO + manifest[as_of=口径日/sha256/first_mounted_at]）

**小改 8 文件**：runner.mjs（题源/trap 判定/NEG_RE/PRISM_API_BASE/头注释/统计变量改名/注释 18 题）、prism.py（eval start/stop/status 子命令 + manifest 文件校验 + first_mounted_at 留痕 + usage）、smoke_m3.ts（期望外置+import.meta.url 路径）、registry/smoke.ts（观察值注释）、package.json（smoke:trap 并入 smoke:all）、tasks_v1.ts（归档头注）、EVAL_STATUS.md（指针 v3.4.3 + r3 归因更正）、smoke:all 链。

**基建资产**：eval 专用端口组（sentiment 8100 / dashboards 8110 / api 8003 / gateway 9201），全 env 重定向、子项目零改动；生产 `_kill_supervisors` 隔离设计。

## 验证终态（两轮）

①单测 12/12 ✅ ②smoke:all 六段全绿 ✅ ③快照 snap-20261012-1222（哈希/as_of 齐）✅ ④eval 四实例全绿+stop 清四端口+生产 PID 不变 ✅ ⑤trap 6/6 score=5 否决率 100% ✅

## 关键裁决与教训（勿重复推导）

1. **r3 假阴性坐实**：旧 trap 正则 3 条方向颠倒把正确行为判 0——EVAL_STATUS r3 记录的"基线遗留"归因错误，已更正；agent 的 identity/no_evidence/gap 三道防线实际有效
2. **P1#3 运行时判死只读方案**：dashboards DB 层启动即执行 WAL pragma + create_all（db.py:21,36），mode=ro 确定性崩——**口径定案：快照 db 哈希=创建时指纹，eval 挂载后 WAL 漂移属预期（数据不损），first_mounted_at 留痕**；sentiment 同口径（DB_PATH 纯路径塞不进 URI）
3. **months 字段是字符串**：market_source.json 的 months 非列表，逐字符 join 产生乱码 as_of——已 isinstance 分支
4. **子项目零改动**：全部 env 钩子（DATABASE_URL/DASH_PORT/PORT/DB_PATH/AUTOHOME_DB_PATH/PRISM_SENTIMENT_DB/PI_SERVER/SENTIMENT_BOARD/PRISM_DASHBOARDS(_HTTP)/PRISM_GATEWAY_PORT/PRISM_FASTAPI）均为既有代码，explore 先行省掉了预估的"加 env"工作
5. **审查者协作模式**：隔离子代理审查 + 主会话 grep 实证关闭"待坐实"项，两轮审查（初版 5P1 → 终版 3P1）各发现真问题（窗口不对称/辆漏计/反向假阴/WAL 扩大）

## 留给后续（已挂账）

- P1（方案 §10.0）：scorer 抽取（trap_check.mjs 为种子）/ web 录制回放 / runner 超时+trajectory sessionId 精确匹配（eval 与生产共用 trajectories.jsonl 的根治）/ 成本记录
- P2：34 题转库回填 snapshot_id + 三分离切分 + **首次正式批跑**（= v1 基线，等用户 34 题）+ stats 接线 + EVAL_STATUS 台账激活
- 快照管理：snap-20261012-1217（已被 WAL 挂载过，留作哈希漂移口径的实证样本）；保留策略=最近 3 份+被引用者不删
- TikHub TODO-verify：social 题首次实跑时校准响应映射（随 P2）
