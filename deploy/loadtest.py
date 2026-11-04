# -*- coding: utf-8 -*-
"""Prism 容器冒烟压测（仅标准库，无第三方依赖）

用法示例：
    python deploy/loadtest.py health --concurrency 40 --total 400
    python deploy/loadtest.py chat   --concurrency 3  --total 6 --cookie "<登录后的 Cookie 串>"

说明：
    health 模式测 Nginx -> API 基础吞吐，成本低，可先跑；
    chat 模式测 /chat/stream 端到端，每个并发会拉起一个 pi 进程，
    内存消耗大（方案估算 40 进程最坏约 8.6GB），请逐步加并发。
"""
import argparse
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def _health_once(url, timeout):
    """单次健康检查请求，返回 (成功, 耗时秒)"""
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            ok = 200 <= resp.status < 300
        return ok, time.perf_counter() - t0
    except Exception:
        return False, time.perf_counter() - t0


def _chat_once(base, cookie, timeout, idx):
    """单次对话请求，读到 settled 视为成功，返回 (成功, 耗时秒, 失败原因)"""
    t0 = time.perf_counter()
    body = json.dumps(
        {"message": "银河E5 2026年9月销量多少", "user_id": f"loadtest-{idx}"},
        ensure_ascii=False,
    ).encode("utf-8")
    try:
        req = urllib.request.Request(base + "/chat/stream", data=body, method="POST")
        req.add_header("Content-Type", "application/json; charset=utf-8")
        if cookie:
            req.add_header("Cookie", cookie)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            last_types = []
            for raw in resp:
                txt = raw.decode("utf-8", "ignore").strip()
                if not txt:
                    continue
                try:
                    last_types.append(json.loads(txt).get("type", "?"))
                except Exception:
                    last_types.append("unparsable")
                last_types = last_types[-6:]
                if b'"settled"' in raw:
                    return True, time.perf_counter() - t0, ""
        return False, time.perf_counter() - t0, "no-settled:" + ",".join(last_types)
    except Exception as exc:
        return False, time.perf_counter() - t0, f"{type(exc).__name__}:{exc}"


def _summary(results, wall):
    """输出成功数、错误率、分位耗时与吞吐（兼容 2 元组/3 元组结果）"""
    def parts(r):
        return (r[0], r[1], r[2] if len(r) > 2 else "")

    costs = [c for ok, c, _ in map(parts, results) if ok]
    errs = [m for ok, _, m in map(parts, results) if not ok]
    total = len(results)
    print("\n===== 结果 =====")
    print(f"请求数   : {total}")
    print(f"成功     : {len(costs)}    失败: {len(errs)}    错误率: {len(errs) / total * 100:.1f}%")
    for m in errs[:3]:
        print(f"  - {m[:160]}")
    if costs:
        costs.sort()
        p50 = statistics.median(costs)
        p95 = costs[int(len(costs) * 0.95) - 1] if len(costs) >= 20 else costs[-1]
        print(f"p50      : {p50 * 1000:.0f} ms")
        print(f"p95      : {p95 * 1000:.0f} ms")
        print(f"max      : {costs[-1] * 1000:.0f} ms")
    print(f"总耗时   : {wall:.1f} s")
    print(f"吞吐     : {total / wall:.1f} req/s")


def run_health(args):
    """并发打 /health：每线程固定轮次，统计全量耗时"""
    per_thread = max(1, args.total // args.concurrency)

    def worker(_):
        return [_health_once(args.url, args.timeout) for _ in range(per_thread)]

    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        batches = list(ex.map(worker, range(args.concurrency)))
    wall = time.perf_counter() - wall_start
    _summary([r for b in batches for r in b], wall)


def run_chat(args):
    """并发打 /chat/stream：总请求数按并发分发；--cookie-file 支持每行一个 token 模拟多用户"""
    cookies = [args.cookie]
    if args.cookie_file:
        with open(args.cookie_file, encoding="utf-8") as fh:
            cookies = [ln.strip() for ln in fh if ln.strip()] or cookies

    def one(i):
        ck = cookies[i % len(cookies)]
        return _chat_once(args.url, ck, args.timeout, i)

    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        results = list(ex.map(one, range(args.total)))
    wall = time.perf_counter() - wall_start
    _summary(results, wall)


def main():
    ap = argparse.ArgumentParser(description="Prism 冒烟压测")
    ap.add_argument("mode", choices=["health", "chat"])
    ap.add_argument("--url", default="http://localhost")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--total", type=int, default=200)
    ap.add_argument("--timeout", type=float, default=120)
    ap.add_argument("--cookie", default="")
    ap.add_argument("--cookie-file", default="", help="每行一个 Cookie 串，用于模拟多用户并发")
    args = ap.parse_args()

    if args.mode == "health":
        run_health(args)
    else:
        run_chat(args)


if __name__ == "__main__":
    sys.exit(main())
