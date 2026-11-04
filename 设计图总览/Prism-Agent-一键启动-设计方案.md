# Prism-Agent 一键启动 · 设计方案

> 2026-10-08 拍板（对话决策：形态 A / 方案一 / 含开机自启）。状态：已施工，验收 1-4 通过；
> 验收 5 注册项已落位并实测快捷方式可执行，重登录后零点击可用由用户日常确认。
> 对应代码：`prism.py` + 三个 .bat 壳（项目根目录）。

## 背景与问题

四个看板（舆情/口碑/销量/配置）+ 棱镜结论对话链，背后是 4 个独立进程，此前各自手动启动、
"自己干自己的"——2026-10-08 实测舆情 Board（:8000）根本没在跑，舆情看板 iframe 是坏的；
其余三个活着纯属"恰好都被起过"。启动姿势还有两个坑：
网关必须带 `PRISM_AUTO_APPROVE_UI=1`（否则工具调用全挂死）、
舆情必须用 Anaconda python（自带哨兵校验，普通 python 拒启动）。

## 目标形态

- **start** = 一条命令（或双击）：按序拉起 → 探活 → 状态表 → 全绿自动开浏览器
- **stop** = 一条命令：清空四个端口（连子进程一起杀）
- **status** = 只探活打印表，不动进程
- **install-autostart / uninstall-autostart** = 注册/移除开机自启（Windows 启动文件夹 + vbs 静默启动，无需管理员）
- 幂等：端口已活着就跳过（不区分是谁起的）；纯跳过不弹浏览器，只有本次拉起了服务才开

## 服务注册表（prism.py 内一个列表，加服务=加一行）

| 服务 | 端口 | 启动命令 | cwd | 特殊要求 | 探活 |
|---|---|---|---|---|---|
| sentiment | 8000 | `Anaconda3\python.exe start.py` | 舆情 Board 目录 | 必须 Anaconda python | GET /health |
| gateway | 9200 | `node prism-api/pi_gateway.mjs` | 项目根 | **env `PRISM_AUTO_APPROVE_UI=1`**；cwd=根（better-sqlite3 解析） | GET /health |
| api | 8002 | `python main.py`（内嵌 uvicorn） | prism-api | fastapi/uvicorn 在运行环境 | GET /health |
| web | 5173 | `cmd /c npm run dev` | prism-web | vite 仅绑 ::1，探活用 localhost | GET / |

启动顺序即上表顺序（无硬依赖，按"慢的先起"排，舆情有预热放最前）。

## 行为细节

- 探活：HTTP GET，每 2s 一次；单服务超时 40s（舆情预热慢放宽）；收到任何 HTTP 应答即算活
- 日志：`logs/<服务名>.log` 追加模式，每次 start 写时间戳分隔行
- 拉起：后台分离进程（CREATE_NO_WINDOW + 新进程组），父进程退出不影响
- stop：`netstat -ano` 找四个端口上 LISTENING 的 PID → `taskkill /T /F` 杀进程树；语义="清空这四个端口"
- 自启：**Startup 目录放 .lnk 快捷方式**（目标 = Anaconda pythonw，参数 = `"prism.py" start`，
  无窗口），登录即静默执行幂等的 start。**不用 .vbs/.bat：Defender 拦截 Startup 目录创建
  脚本文件（实测 WinError 5），.lnk 放行**；安装经 PowerShell COM 生成快捷方式
  （prism.py install-autostart）
- 出错：单服务起不来 → 表标红 + 日志路径，不阻塞其他服务；有红不开浏览器

## 范围外（明确不做）

日志轮转、崩溃自动拉起（舆情 start.py 自带、网关自带）、Atuohome 8001（不在依赖里，看板直读 SQLite）、
Langfuse、生产期阿里云编排（届时另立项）。边界：本工具不碰产品代码、不碰红线执行层。

## 验收清单

1. 全停 → start → 四服务全绿 → 浏览器自动开 → 四看板出真数据（重点：舆情 iframe 复活）
2. 再跑一次 start → 全部"跳过"，不弹浏览器
3. 手动杀掉舆情 → status 标红
4. stop → 四端口全清
5. 装自启 → 重新登录后零点击可用（注册项落位验证，实际重登录由用户验收）
