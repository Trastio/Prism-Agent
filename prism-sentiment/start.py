import os
import subprocess
import sys
import time


# 项目核心依赖中，外部 venv（如 hermes-agent）最容易缺的几个。
# 启动期 import 一次，缺则立即拒启动 —— 避免"启动绿、跑到事件检测/词云才炸"。
SENTINELS = ["jieba", "networkx", "httpx"]


def ensure_dirs():
    for d in ["data", "data/cookies", "logs"]:
        os.makedirs(d, exist_ok=True)


def check_env():
    """哨兵校验：防止误用缺依赖的 venv。

    典型场景：从 Claude Code 等工具的 shell 启动时，PATH 里可能是
    hermes-agent 的 venv（缺 jieba），而非项目 conda base。
    哨兵在启动期就拦下，给出明确修复指引，而不是跑到事件检测/词云才崩。
    """
    import importlib.util
    # Windows 控制台默认 GBK，遇特殊字符会 UnicodeEncodeError 崩；errors='replace' 兜底
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    missing = [m for m in SENTINELS if importlib.util.find_spec(m) is None]
    if not missing:
        print(f"[supervisor] 环境校验通过 (python={sys.executable})", flush=True)
        return
    print(f"[supervisor] [FAIL] 当前 Python 缺项目依赖: {missing}", flush=True)
    print(f"  当前 python: {sys.executable}", flush=True)
    print("  若误用了其他 venv（如 hermes-agent），请用项目 conda base 运行：", flush=True)
    print(f"    {os.path.expanduser('~/Anaconda3/python.exe')} start.py", flush=True)
    print("  或在当前环境补装:  pip install -r requirements.txt", flush=True)
    sys.exit(1)


def run_with_restart():
    """uvicorn 崩了自动重启。

    服务存在无 Python trace 的进程级崩（段错误/OOM，多发生在分析阶段）。
    用 supervisor 包一层：子进程崩了 3s 后自动重启，保证前端可用；
    lifespan 预热会让重启后的 suggest 依然快（车系索引重建）。
    """
    host = os.getenv("HOST", "127.0.0.1")  # S-1：默认本地，需外部访问 env HOST=0.0.0.0
    port = os.getenv("PORT", "8000")
    while True:
        print("[supervisor] 启动 uvicorn...", flush=True)
        p = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "api.main:app",
            "--host", host, "--port", port,
        ])
        code = p.wait()
        print(f"[supervisor] uvicorn 退出(code={code}), 3s 后重启", flush=True)
        time.sleep(3)


if __name__ == "__main__":
    ensure_dirs()
    check_env()
    run_with_restart()
