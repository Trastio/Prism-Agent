# P0-评估锚点 · Step2 proposal（2026-10-13）

## 一句话

给评估链装三个锚——**判分可信**（trap 正则修正）、**考卷唯一**（题源合一）、**考场可重置**（快照 + eval 专用端口）——让此后每一次批跑的分数第一次变得可比、可信、可归因。对应方案 v3.4.3 差距表 #28/#29/#30/#31。

## 为什么现在

- r3 批跑（10-12）的 trap-04/05/06"未拦截"高度疑似判分 bug 冤案（三条方向颠倒正则恰好对应这三题）——修 agent 前必须先修阅卷
- 数据月更在即（CAM 月末批），无快照则下一次批跑分数不可归因
- 社媒题已激活（key 10-12 配好），题集即将从 18 题扩到 52+（等 34 题）——扩容前先把地基打平

## 做什么（五件 + 两顺手）

| # | 件 | 产出物 |
|---|---|---|
| 1 | trap 正则修正 + 正反例单测 | `eval/trap_check.mjs`（纯函数抽出）+ `eval/trap_check.test.mjs`（≥12 case）+ runner 引用 + smoke:all 挂载 |
| 2 | 题源合一 | `eval/tasks.json`（18 题单一机器源，schema 含 snapshot_id/set/judge_rubric 占位）+ runner 改读 + tasks_v1.ts 头注归档声明 |
| 3 | 快照脚本 | `eval/snapshot.py`（VACUUM INTO 双库 + market_source.json + manifest[as_of=口径日/sha256]） |
| 4 | eval 专用环境 | prism.py `eval start/stop` 子命令（8100/8110/8003/9201 四实例全 env 重定向，**子项目零改动**）+ runner `PRISM_API_BASE` env |
| 5 | 断言分组 | smoke_m3 真值期望外置 `eval/truth-expectations.json`；registry smoke 注释说明（现状只打印已属稳定组） |
| + | 顺手 | runner 头注释 9100 修正；EVAL_STATUS 指针 v3.3→v3.4.3 |

## 不做什么（防蔓延）

- **不做** runner 超时/轮数上限/并发修复（P1 #34）、scorer 全量抽取/8 态（P1 #2）、web_search 录制回放（P1 #32）、stats 接线/Pass^k/三分离切分（P2）、34 题转库（P2 等交付）
- **不动** gate 模式（E1-E9 断言引擎原样）、extension/gateway/main.py 任何源码（纯 env 复用）、生产 SERVICES 五件套行为（eval 子命令独立，stop 不碰生产端口——含 _kill_supervisors 规避设计）
- **不跑** 首次正式批跑（模考暂缓拍板不变；验收只跑 `--only=trap` 6 题 + dev 集烟测）

## 验收标准（Step9 用）

1. `node --test eval/trap_check.test.mjs` 全绿（每规则正反例）
2. smoke:all 原有项全绿 + 新增 trap 单测并入
3. `python eval/snapshot.py` 产出快照目录 + manifest（as_of 口径日、sha256 齐全、可 list）
4. `python prism.py eval start` 四实例全绿探活，`eval stop` 只清 eval 四端口、生产五服务不受影响（status 复核）
5. 服务在跑时 `node eval/runner.mjs --only=trap` 出 6 题结果——**r3 冤案假设当场判定**（trap-04/05/06 变 5 分=判分锅坐实；仍 0=真 badcase 转 P2 修复清单）
6. runner 不带 env 直跑生产行为不变（PRISM_API_BASE 缺省 8002）
