# Archive：舆情缺陷簇链路闭环（2026-10-20，轻量十步走完归档 ✅）

## 起因与定性

用户在 T7 看板缺陷簇看到 T11 帖（音质帖）→ 全链路审计定性：**数据未串车，前端渲染串车**（loadDefectThemes fire-and-forget 无切车守卫）；同时挖出缺陷簇链路三处结构缺陷（窗口互踩/LLM 失败清空覆盖/事件表悬空引用）与两处运营断线。用户拍板"开干"。

## 交付

1. **前端竞态守卫**（app.js）：token 守卫 + 切车复位 defectThemes/defectLoading；fetch 参数退役
2. **LLM 失败语义**（defect_miner.py）：DefectJudgeError（坏 JSON/网络异常 raise）+ mine 返回 (themes, degraded)；合法空簇 ([],False) 与失败 ([],True) 分离
3. **30 天权威窗**：collection.py Phase 8 / dashboard.py 端点自愈 / **analysis.py trigger 管线**（P0 补修）三入口同算法（today−29 ~ today，isoformat）
4. **degraded 保旧载荷**：三个写入点全部"失败跳写"，端点 degraded 返回旧行
5. **judge 车型锚**：prompt 注入本车名 + "主要讨论其他车型 is_defect=false"
6. **事件表 prune 闭环**（cleanup_posts.py）：prune 同步 post_count + `--prune-only` 存量修复（幂等零删帖）
7. **数据修复实跑**：存量修剪 197 组/1,968 悬空 id/28 组 count 对齐 → 终态零悬空零漂移；R40 首次真删（备份 24MB 先行：153 帖/747 评/146 分析行，paused 豁免 2,233 帖全保）；.env 落 PRISM_CLEANUP_LIVE=1
8. 测试：6 文件适配+新增（judge 锚/raise 语义/degraded 三层/30 天窗/prune 幂等/analysis 路径 payload 结构防护）

## 验证终态

- pytest **908 passed / 1 failed**（test_cache_bust 已知存量挂，10-16 在账）
- 活端点：T7 defect-themes TTL 命中 0.05s 返回 3 簇（旧代码同场景必触发全量重算）
- 服务 :8000 单实例载新码；事件表 621 组悬空 0

## 关键裁决与教训

- **P0（隔审抓出）**：analysis.py:75 第三调用点漏适配元组——自查"grep 全覆盖"失实（只搜了已知文件）。**破坏性签名变更的调用方清点必须全仓 `grep -rn` 并留命中清单**。
- 首派审查子代理 NO-TOOLS 守卫退出（零臆测零副作用）→ 重试制重派命中——fork 型流程第二次实证有效。
- app.js 工作树 18 个外来 hunk（并行会话图表改造）——**提交按 hunk 分离**，未夹带。
- 端点参数退役而非删签名（API 兼容）；窗口列（v11/12）保留不回滚。

## 面试三讲

1. **解决什么**：用户报"缺陷簇串车"，审计证明数据干净、病灶在前端竞态——顺手挖出后端"LLM 一失败就把好数据清空覆盖"这类静默降级。产品判断：把"用户看到的一个 bug"修成"一条链路的可靠性闭环"。
2. **关键裁决与我的角色**：①"失败"与"合法空"必须可区分（DefectJudgeError）——降级不等于清零；②三入口统一权威窗口，缓存不再互踩；③隔离审查抓到我自查漏掉的第三调用点——用流程（重试制隔审+全仓 grep 纪律）补人眼盲区，而不是相信自己。
3. **面试官会追问**：为什么 TTL 缓存还会被浏览器随便一次访问覆盖？→ 因为原设计把"批产"与"读时自愈"混在一个可变行上且窗口当键；修复后单一权威窗+失败保旧，读路径只读不破坏。

## 遗留（不阻塞，转运维清单/愿望单）

- 计划任务 S4U 化（0x800710E0 交互式限制，两晚未跑；需管理员 PS 跑 install_daily_task.ps1）
- 评论极性覆盖率 35-54%（TAG_IN_SERVICE 关闭后无夜跑——切智谱 API 前的过渡方案待拍板）
- 双预算值漂移（任务命令 4000 vs .env 7000）
- P2①⑧ 降级体验（degraded 文案/负缓存）、P2②③ 测试质量、P2⑦ dry-run 连接
- judge 车型锚实际拦截效果观察（依赖 LLM 行为；跨车评论层过滤留二期）
