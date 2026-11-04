# -*- coding: utf-8 -*-
"""
D5（2026-10-14 评估迭代基建包）· 金标重算 dry-run 演练

方案 §10.0.1 L2-7「快照→金标重算 SOP」的机制演练：
  1. 复制现快照为演练体（临时目录，不碰生产快照）
  2. 对演练环境重跑 _gen_user_gold.py（输出重定向到演练目录——生产金标不被覆写）
  3. diff 新旧 gold：无差异 → 幂等坐实；有差异 → 逐项列出，判定是否全部=裁决覆盖层产物
  4. _verify_user_gold.py 对演练快照+演练金标跑 131 断言（演练体的锚点可复算性）
  5. 清理演练目录；断言生产金标 mtime/内容未变（红线：不碰生产金标）

用法：python eval/gold/dryrun_regen.py [--keep]（--keep 保留演练目录供人工检查）
SOP 全文见同目录 重算SOP.md。
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
GOLD_DIR = ROOT / 'eval' / 'gold'
PROD_GOLD = GOLD_DIR / 'user-20261013.json'
SNAP_DIR = ROOT / 'eval' / 'snapshots' / 'snap-20261012-1222'
SNAP_FILES = ['autohome.db', 'vehicle_sentiment.db', 'manifest.json', 'market_source.json']


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def snapshot_state(p: Path) -> tuple:
    st = p.stat()
    return (st.st_mtime_ns, st.st_size, sha(p))


def diff_gold(old: list, new: list) -> list:
    """逐题逐字段 diff → [(new_id, field, 旧值摘要, 新值摘要)]"""
    old_by = {g['new_id']: g for g in old}
    out = []
    for g in new:
        og = old_by.get(g['new_id'], {})
        for k, v in g.items():
            if og.get(k) != v:
                out.append((g['new_id'], k, json.dumps(og.get(k), ensure_ascii=False)[:60],
                            json.dumps(v, ensure_ascii=False)[:60]))
    gone = [gid for gid in old_by if gid not in {g['new_id'] for g in new}]
    for gid in gone:
        out.append((gid, '(整题缺失)', '', ''))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep', action='store_true', help='保留演练目录（默认演练完清理）')
    args = ap.parse_args()

    if not PROD_GOLD.exists() or not SNAP_DIR.exists():
        print('生产金标或快照不存在，中止', file=sys.stderr)
        sys.exit(1)
    before = snapshot_state(PROD_GOLD)
    drill = GOLD_DIR / f'.dryrun-{time.strftime("%Y%m%d-%H%M%S")}'
    drill.mkdir()
    print(f'演练目录: {drill}')

    # 1. 复制现快照为演练体（shm/wal 不复制——只读连接会自建 shm，wal 为空）
    snap_drill = drill / 'snap'
    snap_drill.mkdir()
    for f in SNAP_FILES:
        shutil.copy2(SNAP_DIR / f, snap_drill / f)
    print(f'快照演练体: {len(SNAP_FILES)} 文件（{"%.0f" % (sum((snap_drill / f).stat().st_size for f in SNAP_FILES) / 1e6)}MB）')

    # 2. _gen 重跑（输出重定向到演练目录；生产金标路径不触碰）
    r = subprocess.run([sys.executable, str(GOLD_DIR / '_gen_user_gold.py'), str(drill / 'gold.json')],
                       cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    if r.returncode != 0:
        print('生成器失败:\n' + r.stdout + r.stderr, file=sys.stderr)
        sys.exit(1)
    print(r.stdout.strip().splitlines()[-1])

    # 3. diff 新旧 gold
    new_gold = json.loads((drill / 'gold.json').read_text(encoding='utf-8'))
    prod_gold = json.loads(PROD_GOLD.read_text(encoding='utf-8'))
    diffs = diff_gold(prod_gold, new_gold)
    if not diffs:
        print('diff 结论: 无差异（生成器重跑幂等，裁决覆盖层与生产金标逐字一致）')
    else:
        print(f'diff 结论: {len(diffs)} 处差异——逐项过目，判定是否全部=裁决覆盖层产物：')
        for gid, field, o, n in diffs:
            print(f'  {gid}.{field}: {o} → {n}')
        print('（非覆盖层产物的数字差异=快照数据变动漂移，需按 SOP 走锚点更新+用户过目）')

    # 4. 演练快照 + 演练金标 131 断言（env 覆写路径，生产脚本零改动行为不变）
    env = {**__import__('os').environ,
           'PRISM_GOLD_FILE': str(drill / 'gold.json'),
           'PRISM_GOLD_SNAP': str(snap_drill)}
    r2 = subprocess.run([sys.executable, str(GOLD_DIR / '_verify_user_gold.py')],
                        cwd=ROOT, capture_output=True, text=True, encoding='utf-8', env=env)
    tail = [ln for ln in (r2.stdout + r2.stderr).splitlines() if '自检结果' in ln]
    print('演练体断言: ' + (tail[-1] if tail else f'无输出（exit={r2.returncode}）'))
    if r2.returncode != 0 or 'FAIL=0' not in (tail[-1] if tail else ''):
        print('演练体断言未全过——保留演练目录供排查', file=sys.stderr)
        print(f'演练目录保留: {drill}', file=sys.stderr)
        sys.exit(1)

    # 5. 清理 + 生产金标未被触碰证明
    after = snapshot_state(PROD_GOLD)
    assert before == after, '生产金标被意外修改！'
    if args.keep:
        print(f'--keep：演练目录保留 {drill}')
    else:
        shutil.rmtree(drill)
        print('演练目录已清理')
    print(f'生产金标未触碰: mtime_ns={after[0]} sha256[:16]={after[2]}（前后一致）')
    print('演练结论: 全链通过（复制→重跑→diff→断言→复原）')


if __name__ == '__main__':
    main()
