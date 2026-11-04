# -*- coding: utf-8 -*-
"""
D4（2026-10-14 评估迭代基建包）· 题×工具调用矩阵

读 eval 轨迹（PRISM_TRAJECTORY_FILE 侧，缺省 eval/trajectories/eval-trajectories.jsonl）
统计 题×工具调用计数 → eval/reports/tool-matrix-<run_id>.md（含零覆盖工具清单）。

题↔轨迹行映射（runner readLastTrajectory 同语义 + 题面兜底）：
  1. 行内显式 task/userId 字段（B2 若补）
  2. sessionId 含 'eval_<task_id>'
  3. conversation[0] 用户消息 = tasks.json 题面（归一化：去空白/标点）
  4. 均不中 → '(unmatched)' 行

工具全集（源=.pi/extensions/prism-guardrails/index.ts KNOWN_BUSINESS_TOOLS
+ TOOL_CATEGORIES.web/utility，含 tikhub.ts social_*4；改动 extension 后同步此表，
轨迹中出现表外工具会在"未知工具"节自报，防清单漂移静默）。
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
TOOL_UNIVERSE = {
    'business': [
        'query_reviews', 'query_sales', 'query_config',
        'sentiment_overview', 'sentiment_trend', 'sentiment_dimension',
        'sentiment_posts', 'sentiment_competitive', 'sentiment_events',
        'sentiment_defects',
        'search_cars', 'get_model_detail', 'get_similar_models',
        'get_trims', 'get_config_detail', 'compare_configs_valued',
        'get_review_analysis', 'search_reviews', 'get_dimension_reviews',
        'get_sales_detail', 'score_models', 'resolve_series', 'submit_conclusion',
    ],
    'web': ['web_search', 'fetch_content', 'source_check', 'get_search_content'],
    'social': ['social_search', 'social_post_comments', 'social_user_profile', 'social_user_posts'],
    'utility': ['ask_user_question', 'load_skill', 'export_document'],
}
ALL_TOOLS = {t for ts in TOOL_UNIVERSE.values() for t in ts}


def _norm(s: str) -> str:
    return re.sub(r'[\s，。？！,?!：:、·]+', '', s or '')


def load_tasks() -> dict:
    """tasks.json → {id: {'question':…, 'set':…}}；动态题不在其中（映射兜底 unmatched）"""
    try:
        tasks = json.loads((ROOT / 'eval' / 'tasks.json').read_text(encoding='utf-8'))
        return {t['id']: {'question': t.get('question', ''), 'set': t.get('set') or '-'} for t in tasks}
    except Exception:
        return {}


def map_task(obj: dict, tasks: dict) -> str:
    t = obj.get('task') or obj.get('userId')
    if isinstance(t, str) and t in tasks:
        return t
    sid = obj.get('sessionId') or ''
    for tid in tasks:
        if f'eval_{tid}' in sid:
            return tid
    conv = obj.get('conversation') or []
    if conv:
        # 轨迹 conversation 条目两种形态：'user: 题面' 字符串（当前 extension 序列化）
        # 或 {role, text} dict——统一取首条（用户题面）并剥 role 前缀
        first = conv[0]
        raw = str(first.get('text') or '') if isinstance(first, dict) else str(first)
        raw = re.sub(r'^[a-zA-Z_]+\s*[:：]\s*', '', raw)
        text = _norm(raw)
        if text:
            for tid, meta in tasks.items():
                q = _norm(meta['question'])
                if q and (q == text or q in text or text in q):
                    return tid
    return '(unmatched)'


def build_matrix(traj_path: Path) -> dict:
    tasks = load_tasks()
    rows = []          # [{task, set, counts: Counter}]
    totals = Counter()
    for line in traj_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        counts = Counter()
        for c in obj.get('toolCalls') or []:
            name = c.get('name') if isinstance(c, dict) else None
            if name:
                counts[name] += 1
                totals[name] += 1
        tid = map_task(obj, tasks)
        rows.append({'task': tid, 'set': tasks.get(tid, {}).get('set', '?'), 'counts': counts})
    # 同题多轨迹（重试/多轮）合并
    merged: dict = {}
    for r in rows:
        m = merged.setdefault(r['task'], {'task': r['task'], 'set': r['set'], 'counts': Counter()})
        m['counts'] += r['counts']
    return {'rows': sorted(merged.values(), key=lambda x: x['task']), 'totals': totals}


def render_md(matrix: dict, run_id: str, traj_path: Path) -> str:
    lines = [
        '# 工具覆盖矩阵 · ' + run_id,
        '',
        f'- 轨迹源: `{traj_path}`',
        f'- 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'- 覆盖工具: {len(matrix["totals"])}/{len(ALL_TOOLS)}（全集=extension KNOWN_BUSINESS_TOOLS+web/social/utility）',
        '',
        '## 题 × 工具调用计数',
        '',
        '| 题 | set | 工具调用（×次数） | 合计 |',
        '|---|---|---|---|',
    ]
    for r in matrix['rows']:
        cell = '、'.join(f'{n}×{c}' for n, c in r['counts'].most_common()) or '（零调用）'
        lines.append(f"| {r['task']} | {r['set']} | {cell} | {sum(r['counts'].values())} |")

    lines += ['', '## 工具覆盖汇总', '', '| 工具 | 调用总数 |', '|---|---|']
    for n, c in matrix['totals'].most_common():
        lines.append(f'| {n} | {c} |')

    lines += ['', '## 零覆盖工具清单', '']
    for cat, tools in TOOL_UNIVERSE.items():
        zero = [t for t in tools if t not in matrix['totals']]
        lines.append(f"- **{cat}**（{len(zero)}/{len(tools)} 未覆盖）: {('、'.join(zero) or '—')}")

    unknown = sorted(set(matrix['totals']) - ALL_TOOLS)
    if unknown:
        lines += ['', '## ⚠ 未知工具（不在全集——extension 改动后请同步 TOOL_UNIVERSE）', '', '、'.join(unknown)]
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser(description='D4 题×工具调用矩阵')
    ap.add_argument('--traj', default=os.environ.get('PRISM_TRAJECTORY_FILE',
                      str(ROOT / 'eval' / 'trajectories' / 'eval-trajectories.jsonl')))
    ap.add_argument('--run-id', help='缺省取 eval/reports/ 最新 eval-*.json 的 run_id')
    ap.add_argument('--out', help='缺省 eval/reports/tool-matrix-<run_id>.md')
    args = ap.parse_args()

    traj_path = Path(args.traj)
    if not traj_path.exists():
        print(f'轨迹文件不存在: {traj_path}', file=sys.stderr)
        sys.exit(1)

    run_id = args.run_id
    if not run_id:
        reports = sorted((ROOT / 'eval' / 'reports').glob('eval-*.json'),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        run_id = reports[0].stem if reports else 'adhoc-' + datetime.now().strftime('%Y%m%d-%H%M')

    matrix = build_matrix(traj_path)
    out = Path(args.out) if args.out else ROOT / 'eval' / 'reports' / f'tool-matrix-{run_id}.md'
    out.write_text(render_md(matrix, run_id, traj_path), encoding='utf-8')
    print(f'矩阵已写入: {out}')
    print(f'题数（含 unmatched）: {len(matrix["rows"])}，覆盖工具: {len(matrix["totals"])}/{len(ALL_TOOLS)}')


if __name__ == '__main__':
    main()
