#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prism-Agent 一键启动器。

用法：
  python prism.py start                # 按序拉起六个服务，探活，打印状态表，全绿开浏览器
  python prism.py stop                 # 清空六个端口（连子进程一起杀）
  python prism.py status               # 只探活打印表，不动进程
  python prism.py install-autostart    # 注册开机自启（登录时静默 start）
  python prism.py uninstall-autostart  # 移除开机自启
  python prism.py eval start [快照id]  # 拉起 eval 四实例(8100/8110/8003/9201，连 eval/snapshots 快照库)
  python prism.py eval stop            # 只清 eval 四端口（生产六服务不受影响）
  python prism.py eval status          # 探活 eval 四端口

服务注册表见 SERVICES：加一个服务 = 加一个 dict。
设计文档：设计图总览/Prism-Agent-一键启动-设计方案.md
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ANACONDA_PYTHON = os.path.expanduser(r"~\Anaconda3\python.exe")
# F5（2026-11-02）三库收敛：采集/周更只写 deploy/data，本地服务与推送同读这一份。
# 旧库 prism-dashboards/data/autohome.db 降级为历史副本（不再被生产服务引用）。
DEAL_DB = os.path.join(PROJECT_ROOT, "deploy", "data", "autohome.db")
NODE = r"C:\Program Files\nodejs\node.exe"
# 2026-10-08 收敛修正：舆情服务原指向已退役的旧项目
# （Desktop\Agent项目\Vehicle Sentiment Analysis Board），会导致用旧代码 + 旧库启动 :8000。
# 现改为 Prism 自持目录 prism-sentiment，与看板服务 prism-dashboards 同级。
SENTIMENT_DIR = os.path.join(PROJECT_ROOT, "prism-sentiment")
DASHBOARDS_DIR = os.path.join(PROJECT_ROOT, "prism-dashboards")
OPS_DIR = os.path.join(PROJECT_ROOT, "prism-ops")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
FRONTEND_URL = "http://localhost:5173"
STARTUP_DIR = os.path.join(
    os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")
STARTUP_LNK = os.path.join(STARTUP_DIR, "Prism-Agent-autostart.lnk")
VITE_JS = os.path.join(PROJECT_ROOT, "prism-web", "node_modules", "vite", "bin", "vite.js")

SERVICES = [
    # DB_PATH 钉死为绝对路径：models/database.py 默认用相对路径 "data/vehicle_sentiment.db"，
    # 一旦 cwd 不对就会静默换库（历史上正是这条路指向了旧项目库）。显式钉死消除该隐患。
    dict(name="sentiment", port=8000, cwd=SENTIMENT_DIR,
         cmd=[ANACONDA_PYTHON, "start.py"],
         env={"DB_PATH": os.path.join(SENTIMENT_DIR, "data", "vehicle_sentiment.db")},
         supervisor_script="start.py",   # start.py 内置看门狗，stop 需先杀父进程
         health="http://127.0.0.1:8000/health", timeout=40),
    dict(name="gateway", port=9200, cwd=PROJECT_ROOT,
         cmd=[NODE, os.path.join("prism-api", "pi_gateway.mjs")],
         # F5：pi 进程继承该 env，工具链（src/tools/_shared.ts）与看板读同一份库
         env={"PRISM_AUTO_APPROVE_UI": "1", "AUTOHOME_DB_PATH": DEAL_DB},
         health="http://127.0.0.1:9200/health", timeout=30),
    dict(name="api", port=8002, cwd=os.path.join(PROJECT_ROOT, "prism-api"),
         cmd=[sys.executable, "main.py"],
         # F5：与采集/周更同一份库（deploy/data）
         env={"AUTOHOME_DB_PATH": DEAL_DB},
         health="http://127.0.0.1:8002/health", timeout=30),
    # 2026-10-13 新增：北极星看板独立端口（openspec/changes/北极星看板独立端口化）——
    # 管理者运营数据与主站（~49 人只读）物理分离；默认仅绑 127.0.0.1，上云时挂 Basic-Auth 或不上云。
    # 探活走 GET /（单页 HTML，无独立 /health 端点）；python 用法对齐上方 api 服务。
    dict(name="ops", port=8020, cwd=OPS_DIR,
         cmd=[sys.executable, "ops_server.py"],
         # E3/E4：读取每日巡检汇总（本地部署目录），缺失时页面自动隐藏区块
         env={"PRISM_HEALTH_DIR": os.path.join(PROJECT_ROOT, "deploy", "data", "health")},
         health="http://127.0.0.1:8020/", timeout=30),
    # 2026-10-08 新增：三看板子服务（口碑/配置/市场）此前不在统一启动器内，
    # 且曾由外部 venv 拉起。现纳入 SERVICES，改用 Anaconda 自持解释器。
    dict(name="dashboards", port=8010, cwd=DASHBOARDS_DIR,
         cmd=[ANACONDA_PYTHON, "app.py"],
         # F5：与采集/周更同一份库（deploy/data）
         env={"DATABASE_URL": "sqlite:///" + DEAL_DB.replace("\\", "/")},
         health="http://127.0.0.1:8010/health", timeout=30),
    dict(name="web", port=5173, cwd=os.path.join(PROJECT_ROOT, "prism-web"),
         cmd=[NODE, VITE_JS], env={},
         health="http://localhost:5173/", timeout=30),  # vite 只绑 ::1，探活必须走 localhost
]


# ---------------------------------------------------------------------------
# P0-评估锚点（方案 v3.4.3 §4.1.1）：eval 快照实例，与生产端口全隔离。
# 全部走既有 env 钩子（explore §4 实证），子项目零改动：
#   sentiment: PORT + DB_PATH（start.py:50 / SERVICES 同款）
#   dashboards: DASH_PORT + DATABASE_URL（app.py:60 / db.py:27）
#   api: AUTOHOME_DB_PATH / PRISM_SENTIMENT_DB / PI_SERVER / SENTIMENT_BOARD /
#        PRISM_DASHBOARDS(_HTTP) / PRISM_AUTOHOME_CACHE_TTL（main.py:28/29/30/554/725/1015/745）
#   gateway: PRISM_GATEWAY_PORT + spawn env 透传 PRISM_FASTAPI（pi_gateway.mjs:22/:375）
# ⚠ eval sentiment 不走 start.py：_kill_supervisors 按脚本名无差别杀会误杀生产看门狗。
# ⚠ eval api 用 uvicorn 直拉：main.py:1285 端口写死 8002，无 env（self-check Gap1）。
# ---------------------------------------------------------------------------
EVAL_SNAP_ROOT = os.path.join(PROJECT_ROOT, "eval", "snapshots")
EVAL_PORTS = {"sentiment": 8100, "dashboards": 8110, "api": 8003, "gateway": 9201}


def _eval_services(snap_dir):
    def db(fname):
        return os.path.join(snap_dir, fname)
    api_env = {
        "AUTOHOME_DB_PATH": db("autohome.db"),
        "PRISM_SENTIMENT_DB": db("vehicle_sentiment.db"),
        "PI_SERVER": "http://127.0.0.1:%d" % EVAL_PORTS["gateway"],
        "SENTIMENT_BOARD": "http://127.0.0.1:%d" % EVAL_PORTS["sentiment"],
        "PRISM_DASHBOARDS": "http://127.0.0.1:%d" % EVAL_PORTS["dashboards"],
        "PRISM_DASHBOARDS_HTTP": "http://127.0.0.1:%d" % EVAL_PORTS["dashboards"],
        "PRISM_AUTOHOME_CACHE_TTL": "0",  # 快照不变，无需缓存；也防生产缓存口径串入
        # P0 北极星隔离（2026-10-26）：eval 栈与生产共用事件库，必须显式标记——
        # main.py /events 见到本标记直接丢弃，评估流量永远不会被算成真实用户。
        "PRISM_EVAL_STACK": "1",
    }
    return [
        dict(name="sentiment-eval", port=EVAL_PORTS["sentiment"], cwd=SENTIMENT_DIR,
             cmd=[ANACONDA_PYTHON, "-m", "uvicorn", "api.main:app",
                  "--port", str(EVAL_PORTS["sentiment"])],
             env={"DB_PATH": db("vehicle_sentiment.db")},
             health="http://127.0.0.1:%d/health" % EVAL_PORTS["sentiment"], timeout=40),
        dict(name="dashboards-eval", port=EVAL_PORTS["dashboards"], cwd=DASHBOARDS_DIR,
             cmd=[ANACONDA_PYTHON, "app.py"],
             # 审查 P1#3 裁决（Step9 实证）：mode=ro 确定性失败——dashboards DB 层启动即执行
             # WAL pragma + create_all DDL（db.py:21,36），只读库写不动（logs/dashboards-eval.log
             # 119 行 traceback 为证）。口径定案：快照 db 哈希=创建时指纹，eval 挂载后 WAL 化
             # 漂移属预期（数据不损），eval start 首挂写 manifest.first_mounted_at 留痕。
             env={"DASH_PORT": str(EVAL_PORTS["dashboards"]),
                  "DATABASE_URL": "sqlite:///" + db("autohome.db").replace("\\", "/")},
             health="http://127.0.0.1:%d/health" % EVAL_PORTS["dashboards"], timeout=30),
        dict(name="api-eval", port=EVAL_PORTS["api"], cwd=os.path.join(PROJECT_ROOT, "prism-api"),
             cmd=[sys.executable, "-m", "uvicorn", "main:app",
                  "--port", str(EVAL_PORTS["api"])],
             env=api_env,
             health="http://127.0.0.1:%d/health" % EVAL_PORTS["api"], timeout=30),
        dict(name="gateway-eval", port=EVAL_PORTS["gateway"], cwd=PROJECT_ROOT,
             cmd=[NODE, os.path.join("prism-api", "pi_gateway.mjs")],
             # A5 轨迹分离：eval 轨迹独立文件（extension 写入侧/runner 读取侧同读此 env；
             #   spawn 链 prism.py→gateway(os.environ.copy)→pi(...process.env) 全量透传已核）。
             # A4 实例标签（G4 env 方案，插件 src/index.ts:109 已核）：eval trace 落 environment=eval，
             #   生产/交互 pi 走 langfuse.json 文件缺省，UI 可按 environment 防混流。
             env={"PRISM_GATEWAY_PORT": str(EVAL_PORTS["gateway"]),
                  "PRISM_AUTO_APPROVE_UI": "1",
                  # 多轮评估批 change T3：eval 网关第三态——ui_request 不抢答，runner 按
                  # 题级 ui_strategy 模拟用户应答（skill-03 瞎代答根治；生产网关 9200 无此 env 零变化）
                  "PRISM_EVAL_UI_SIM": "1",
                  "PRISM_FASTAPI": "http://127.0.0.1:%d" % EVAL_PORTS["api"],
                  "PRISM_TRAJECTORY_FILE": os.path.join(
                      PROJECT_ROOT, "eval", "trajectories", "eval-trajectories.jsonl"),
                  "LANGFUSE_TRACING_ENVIRONMENT": "eval"},
             health="http://127.0.0.1:%d/health" % EVAL_PORTS["gateway"], timeout=30),
    ]


def _latest_snapshot():
    if not os.path.isdir(EVAL_SNAP_ROOT):
        return None
    cands = sorted(d for d in os.listdir(EVAL_SNAP_ROOT) if d.startswith("snap-"))
    return cands[-1] if cands else None


def cmd_eval():
    sub = sys.argv[2] if len(sys.argv) > 2 else ""
    if sub == "start":
        snap = sys.argv[3] if len(sys.argv) > 3 else _latest_snapshot()
        if not snap:
            print("无快照可启。先 python eval/snapshot.py create")
            return 1
        snap_dir = os.path.join(EVAL_SNAP_ROOT, snap)
        mf_path = os.path.join(snap_dir, "manifest.json")
        if not os.path.exists(mf_path):
            print("快照 manifest 缺失: %s" % snap_dir)
            return 1
        # 审查 P2#10：不止验 manifest 在，逐个验 manifest.files 实体在
        try:
            mf = json.loads(open(mf_path, encoding="utf-8").read())
        except Exception as e:
            print("快照 manifest 解析失败: %s (%s)" % (mf_path, e))
            return 1
        missing = [f for f in mf.get("files", {})
                   if not os.path.exists(os.path.join(snap_dir, f))]
        if missing:
            print("快照文件缺失，终止：%s" % ", ".join(missing))
            return 1
        print("eval 环境 · 快照: %s" % snap)
        # 多轮评估批 P1-2：快照活性戳——runner 批跑前置断言读此文件比对多轮题 snapshot_id
        # （快照轮换后 m03-t3 等"九月空"锚会静默失效，靠此戳 fail-closed 拒跑）
        try:
            with open(os.path.join(EVAL_SNAP_ROOT, "ACTIVE_SNAPSHOT.txt"), "w", encoding="utf-8") as fp:
                fp.write(snap)
        except Exception as e:
            print("警告：快照活性戳写入失败 (%s)" % e)
        # 审查 P1#3（终版扩大版）：sentiment-eval 的 async engine 也会 WAL 化快照舆情库
        # （models/database.py:8-13），dashboards 已 mode=ro 但 sentiment 的 DB_PATH 是
        # 纯路径无法塞 URI。口径定案：db 哈希=创建时指纹，eval 挂载后 WAL 化漂移属预期
        # （数据不损），manifest 记录 first_mounted_at 留痕。
        if "first_mounted_at" not in mf:
            mf["first_mounted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            try:
                with open(mf_path, "w", encoding="utf-8") as fp:
                    json.dump(mf, fp, ensure_ascii=False, indent=2)
            except Exception:
                pass
        rows, failures, skipped = [], [], False
        # A5：eval 轨迹目录预建（extension appendFileSync 只建父目录到 traj 文件本身，
        # 这里显式建齐防首个 spawn 前目录缺失；已存在无副作用）
        os.makedirs(os.path.join(PROJECT_ROOT, "eval", "trajectories"), exist_ok=True)
        for svc in _eval_services(snap_dir):
            if probe(svc["health"]):
                rows.append((svc, "跳过(已运行)", ""))
                skipped = True
                continue
            log_path = launch(svc)
            ok = wait_probe(svc)
            rows.append((svc, "启动 OK" if ok else "失败!", "" if ok else "查日志 " + log_path))
            if not ok:
                failures.append(svc["name"])
        print_table(rows)
        if failures:
            print("eval 实例未全绿：%s" % ", ".join(failures))
            return 1
        if skipped:
            print("\n注意：有实例已在运行，其快照指向未校验（可能仍连旧快照）——"
                  "建议 eval stop 后再 start 指定快照。")
        print("\n批跑入口（缺省全部题；trap 快验 --only=trap）：")
        print("  PRISM_API_BASE=http://127.0.0.1:%d "
              "PRISM_TRAJECTORY_FILE=\"%s\" node eval/runner.mjs --only=trap"
              % (EVAL_PORTS["api"],
                 os.path.join(PROJECT_ROOT, "eval", "trajectories", "eval-trajectories.jsonl")))
        print("口径提醒：批跑期间冻结生产服务操作、单进程运行（EVAL_STATUS 运营口径）；")
        print("          eval 轨迹已分离（PRISM_TRAJECTORY_FILE），批跑不写生产 trajectories.jsonl；")
        print("          runner 必须带同 env 起跑（上方命令已含），否则读到生产轨迹判分错源。")
        return 0
    if sub == "stop":
        rows = []
        for name, port in EVAL_PORTS.items():
            pids = pids_on_port(port)
            for pid in pids:
                subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
            time.sleep(1)
            rows.append((dict(name=name + "-eval", port=port),
                         "已停止" if pids else "本来就未运行", ""))
        print_table(rows)
        # 补审 P2：eval 停栈即清快照活性戳——防残留戳让 runner 在无 eval 会话时误判"快照一致"
        try:
            stamp = os.path.join(EVAL_SNAP_ROOT, "ACTIVE_SNAPSHOT.txt")
            if os.path.exists(stamp):
                os.remove(stamp)
                print("快照活性戳已随停栈清除。")
        except Exception as e:
            print("警告：活性戳清除失败 (%s)" % e)
        print("eval 四端口已清（生产六服务不受影响，_kill_supervisors 不参与）。")
        return 0
    if sub == "status":
        rows = []
        for name, port in EVAL_PORTS.items():
            rows.append((dict(name=name + "-eval", port=port),
                         "运行中" if probe("http://127.0.0.1:%d/health" % port) else "未运行", ""))
        print_table(rows)
        return 0
    print("用法: python prism.py eval start [snapshot_id] | eval stop | eval status")
    return 1


def probe(url):
    """活 = 收到任何 HTTP 应答（含 4xx/5xx，服务起来了但端点没配也算在跑）。"""
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=2)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def pids_on_port(port):
    # netstat 输出是 GBK（中文表头），不能用 text=True——手动解码，只解析 ASCII 列
    raw = subprocess.run(["netstat", "-ano"], capture_output=True).stdout
    out = raw.decode("utf-8", errors="replace")
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].endswith(":%d" % port):
            pids.add(parts[4])
    return pids


def launch(svc):
    """后台分离拉起，stdout/stderr 追加进 logs/<服务名>.log。返回日志路径。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, svc["name"] + ".log")
    log = open(log_path, "ab")
    try:
        log.write(("\n===== %s start =====\n"
                   % time.strftime("%Y-%m-%d %H:%M:%S")).encode("utf-8"))
        log.flush()
        env = os.environ.copy()
        env.update(svc.get("env", {}))
        subprocess.Popen(
            svc["cmd"], cwd=svc["cwd"], env=env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    finally:
        log.close()
    return log_path


def wait_probe(svc):
    deadline = time.time() + svc["timeout"]
    while time.time() < deadline:
        if probe(svc["health"]):
            return True
        time.sleep(2)
    return False


def pid_cell(svc):
    pids = pids_on_port(svc["port"])
    return ",".join(sorted(pids)) if pids else "-"


def print_table(rows):
    """rows: [(svc, state, extra)]"""
    print()
    print("Prism-Agent 服务状态  %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    print("-" * 78)
    print("%-11s%-8s%-14s%-10s%s" % ("服务", "端口", "状态", "PID", "备注"))
    for svc, state, extra in rows:
        print("%-11s%-8s%-14s%-10s%s"
              % (svc["name"], svc["port"], state, pid_cell(svc), extra))
    print("-" * 78)


def cmd_start():
    rows, failures, started = [], [], []
    for svc in SERVICES:
        if probe(svc["health"]):
            rows.append((svc, "跳过(已运行)", ""))
            continue
        log_path = launch(svc)
        if wait_probe(svc):
            started.append(svc["name"])
            rows.append((svc, "启动 OK", log_path))
        else:
            failures.append(svc["name"])
            rows.append((svc, "失败!", "查日志 " + log_path))
    print_table(rows)
    if failures:
        print("未全绿，浏览器未打开。失败服务日志见上表。")
        return 1
    if os.environ.get("PRISM_NO_BROWSER") == "1":
        if started:
            print("已拉起: %s → PRISM_NO_BROWSER=1，不弹浏览器" % ", ".join(started))
    elif started:
        os.startfile(FRONTEND_URL)
        print("已拉起: %s → 浏览器已打开 %s" % (", ".join(started), FRONTEND_URL))
    else:
        print("全部已在运行（本次纯跳过，不重复开浏览器）。")
    return 0


def _kill_supervisors():
    """先杀带自动重启的看门狗父进程，再清端口。

    sentiment 的 start.py 是 supervisor：uvicorn 崩了 3s 自动重启。若只 taskkill
    监听端口的子进程，看门狗会立刻把服务拉回来（stop 永远"停不干净"）。
    按命令行结尾匹配脚本名（supervisor 的 cmdline 是 `<python> start.py`，
    不含目录，无法按路径过滤）——本机范围内可接受。
    """
    scripts = [svc["supervisor_script"] for svc in SERVICES if svc.get("supervisor_script")]
    if not scripts:
        return
    conds = " -or ".join("$c.TrimEnd().EndsWith('%s')" % s for s in scripts)
    ps = ("Get-CimInstance Win32_Process | "
          "Where-Object { $c = $_.CommandLine; $c -and (%s) } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % conds)
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)


def cmd_stop():
    _kill_supervisors()
    time.sleep(1)
    rows = []
    for svc in SERVICES:
        pids = pids_on_port(svc["port"])
        for pid in pids:
            subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
        time.sleep(1)
        state = "已停止" if pids else "本来就未运行"
        rows.append((svc, state, ""))
    print_table(rows)
    leftovers = [s["name"] for s, _, _ in rows if probe(s["health"])]
    if leftovers:
        print("警告：仍未停干净 %s（可能有进程自动重启，查日志）" % ", ".join(leftovers))
        return 1
    print("六个端口已全部清空。")
    return 0


def cmd_status():
    rows = []
    for svc in SERVICES:
        rows.append((svc, "运行中" if probe(svc["health"]) else "未运行", ""))
    print_table(rows)
    return 0


def _pythonw():
    cand = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return cand if os.path.exists(cand) else sys.executable


def cmd_install_autostart():
    """登录自启用 .lnk 快捷方式（目标 pythonw，无窗口）。

    不用 .vbs/.bat：Defender 会拦截在 Startup 目录创建脚本文件（实测 WinError 5），
    .lnk 放行。经 PowerShell COM 创建快捷方式。
    """
    os.makedirs(STARTUP_DIR, exist_ok=True)
    py_path = os.path.join(PROJECT_ROOT, "prism.py")
    ps1 = os.path.join(PROJECT_ROOT, "prism-autostart-install.ps1")
    with open(ps1, "w", encoding="ascii", errors="strict") as f:
        f.write(
            "$ws = New-Object -ComObject WScript.Shell\n"
            "$lnk = $ws.CreateShortcut('%s')\n"
            "$lnk.TargetPath = '%s'\n"
            "$lnk.Arguments = '\"%s\" start'\n"
            "$lnk.WorkingDirectory = '%s'\n"
            "$lnk.Description = 'Prism-Agent autostart'\n"
            "$lnk.Save()\n"
            % (STARTUP_LNK, _pythonw(), py_path, PROJECT_ROOT))
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1],
        capture_output=True)
    if r.returncode != 0:
        print("注册失败：", r.stderr.decode("utf-8", errors="replace")[:300])
        return 1
    print("已注册开机自启：")
    print("  " + STARTUP_LNK)
    print("效果：每次登录 Windows 后 pythonw 静默执行 start（已运行的服务自动跳过）。")
    print("移除：python prism.py uninstall-autostart")
    return 0


def cmd_uninstall_autostart():
    removed = []
    for path in (STARTUP_LNK,
                 os.path.join(STARTUP_DIR, "Prism-Agent-autostart.vbs")):  # 兼容清理旧 vbs 方案
        if os.path.exists(path):
            os.remove(path)
            removed.append(path)
    if removed:
        print("已移除开机自启：")
        for p in removed:
            print("  " + p)
    else:
        print("未发现开机自启注册项。")
    return 0


def cmd_koubei_weekly():
    """口碑周更入口薄封装（口碑周更增量采集 change）：透传给 dashboards 侧脚本。

    用法：
      python prism.py koubei-weekly                       # dry-run（零写入零出网）
      python prism.py koubei-weekly --live                # 真采（自动备份先行）
      python prism.py koubei-weekly --live --budget-reviews 200
      python prism.py koubei-weekly --catchup [--check]   # 登录补跑判定
    透传参数：--live / --budget-reviews N / --catchup / --check / --db PATH。
    """
    passthrough = sys.argv[2:]
    allowed = ("--live", "--budget-reviews", "--catchup", "--check", "--db", "--push-only")
    valued = ("--budget-reviews", "--db")   # 带值参数（P1-2：空格形式成对消费）
    bad = []
    i = 0
    while i < len(passthrough):
        a = passthrough[i]
        key = a.split("=", 1)[0]
        if key not in allowed:
            bad.append(a)
            i += 1
        elif "=" not in a and key in valued and i + 1 < len(passthrough) \
                and not passthrough[i + 1].startswith("--"):
            i += 2   # --budget-reviews 200 / --db path：flag+值一起放行
        else:
            i += 1
    if bad:
        print("不支持的参数：%s（允许：%s）" % (", ".join(bad), ", ".join(allowed)))
        return 1
    script = os.path.join(DASHBOARDS_DIR, "scripts", "koubei_weekly_update.py")
    if not os.path.exists(script):
        print("脚本缺失: %s" % script)
        return 1
    return subprocess.call([ANACONDA_PYTHON, script] + passthrough,
                           cwd=DASHBOARDS_DIR)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if os.name != "nt":
        print("本工具仅支持 Windows。")
        return 1
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    actions = {
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "install-autostart": cmd_install_autostart,
        "uninstall-autostart": cmd_uninstall_autostart,
        "eval": cmd_eval,
        "koubei-weekly": cmd_koubei_weekly,
    }
    if action not in actions:
        print(__doc__)
        return 1
    return actions[action]()


if __name__ == "__main__":
    sys.exit(main())
