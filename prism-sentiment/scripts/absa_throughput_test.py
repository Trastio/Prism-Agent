"""夜跑窗口实测（上线方案 §7.1.1 配套③）：微调 Qwen3-4B 本地 GPU 吞吐计时。

目的：量化"本地夜跑常态化"方案在 RTX 4080 Laptop (12GB) 上的批处理窗口，
推算 日增1万 / 峰值4.4万 / 欠账5,845 条的耗时，验证 08:00 触发线是否安全。

样本：优先取 dim_sentiment IS NULL 的真实欠账评论（即夜跑要处理的负载形态），
不足再补已打标评论（只计时不写库——predict_batch 纯推理，零写入）。

用法：python scripts/absa_throughput_test.py [N]   # N 默认 300
产出：scripts/absa_throughput_result.json + 控制台摘要
"""
import json
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")  # 须在 torch 导入前（OMP 重复库）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.analysis.local_absa import LocalABSAModel  # noqa: E402

DB = Path(__file__).resolve().parent.parent / "data" / "vehicle_sentiment.db"
ADAPTER = "C:/Users/<you>/Desktop/Qwen3-4B-finetuning/output"
OUT = Path(__file__).resolve().parent / "absa_throughput_result.json"
BATCH = 16  # 与 local_absa.predict_batch 默认一致


def load_sample(n: int):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    todo = [r[0] for r in conn.execute(
        "SELECT content FROM post_comments "
        "WHERE dim_sentiment IS NULL AND content IS NOT NULL AND length(content) >= 4"
    ).fetchall()]
    done_pool = [] if len(todo) >= n else [r[0] for r in conn.execute(
        "SELECT content FROM post_comments "
        "WHERE dim_sentiment IS NOT NULL AND content IS NOT NULL AND length(content) >= 4 "
        "LIMIT ?"
    ).fetchall()]
    conn.close()
    random.seed(42)
    random.shuffle(todo)
    sample = todo[:n]
    if len(sample) < n:
        random.shuffle(done_pool)
        sample += done_pool[: n - len(sample)]
    return sample, len(todo)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    sample, backlog = load_sample(n)
    print(f"样本 {len(sample)} 条（欠账池 {backlog} 条），batch={BATCH}", flush=True)

    model = LocalABSAModel.get()
    model.load(ADAPTER)

    t0 = time.perf_counter()
    model._ensure_loaded()  # 显式计时模型加载
    t_load = time.perf_counter() - t0
    print(f"模型加载 {t_load:.1f}s", flush=True)

    import torch
    torch.cuda.reset_peak_memory_stats()

    batch_times = []
    t_all = time.perf_counter()
    for i in range(0, len(sample), BATCH):
        chunk = sample[i:i + BATCH]
        t = time.perf_counter()
        model.predict_batch(chunk, batch_size=BATCH)
        batch_times.append(time.perf_counter() - t)
        if (i // BATCH + 1) % 5 == 0:
            print(f"  进度 {i + len(chunk)}/{len(sample)}，最近批 {batch_times[-1]:.2f}s", flush=True)
    t_infer = time.perf_counter() - t_all

    tps = len(sample) / t_infer
    vram_gb = torch.cuda.max_memory_allocated() / 1024**3
    result = {
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "gpu": torch.cuda.get_device_name(0),
        "n": len(sample), "backlog_pool": backlog, "batch": BATCH,
        "load_s": round(t_load, 1), "infer_s": round(t_infer, 1),
        "throughput_per_s": round(tps, 2),
        "per_item_ms": round(1000 / tps, 1),
        "vram_peak_gb": round(vram_gb, 2),
        "batch_times_head": [round(x, 2) for x in batch_times[:5]],
        "batch_times_tail": [round(x, 2) for x in batch_times[-5:]],
        "extrapolate_hours": {
            "daily_10k": round(10000 / tps / 3600, 2),
            "peak_44k": round(44000 / tps / 3600, 2),
            "backlog_5845": round(5845 / tps / 3600, 2),
        },
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    print(f"结果已存 {OUT}", flush=True)


if __name__ == "__main__":
    main()
