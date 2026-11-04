"""
Prism-Agent · 统计栈（T-2.4.3）

McNemar + Wilcoxon 符号秩 + Cliff's delta + bootstrap CI
3 个自补项（教材无）：Wilcoxon（连续分数）、Cliff's delta（效应量）、bootstrap CI

发版门槛 4 条件：
1. veto 零命中
2. Wilcoxon 显著且 delta>0.1
3. 保留集 CI 下界>0
4. 成本 CI 上界<预算

D1 接线（2026-10-14 评估迭代基建包）：CLI 配对两份 eval/reports/*.json
  python eval/stats.py --baseline eval/reports/<旧>.json --candidate eval/reports/<新>.json
四条件判定 JSON + 人读摘要；保留集按 task.set=frozen 过滤（result.set 优先，
缺省回查 eval/tasks.json）；成本暂用 duration_s 兜底口径（token 台账 B2-5 落地前）。
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import List, Tuple


# ---------------------------------------------------------------------------
# McNemar（二元 veto 配对检验）
# ---------------------------------------------------------------------------
def mcnemar(before_pass: List[bool], after_pass: List[bool]) -> dict:
    """before/after 同一组任务在两次评估的通过情况（trap veto 是否被否决）"""
    assert len(before_pass) == len(after_pass)
    # n01: before fail, after pass（改善）
    # n10: before pass, after fail（退化）
    n01 = sum(1 for b, a in zip(before_pass, after_pass) if not b and a)
    n10 = sum(1 for b, a in zip(before_pass, after_pass) if b and not a)
    # 精确二项检验（n01+n10 < 25 时）
    n = n01 + n10
    if n == 0:
        return {"statistic": 0, "p_value": 1.0, "n01": 0, "n10": 0}
    # 连续性校正卡方
    chi2 = (abs(n01 - n10) - 1) ** 2 / n if n > 0 else 0
    # 简化 p-value（正态近似）
    z = (abs(n01 - n10) - 1) / math.sqrt(n) if n > 0 else 0
    p = 2 * (1 - _norm_cdf(abs(z)))
    return {"chi2": chi2, "p_value": p, "n01": n01, "n10": n10, "n": n}


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# ---------------------------------------------------------------------------
# McNemar 精确法 + Clopper-Pearson 区间（2026-11-02 显著性实验预注册口径）
# 既有 mcnemar() 用正态近似（双侧），小样本（b<25）会偏；本次预注册写死"精确单侧"，
# 故在此补两个函数，不改动 mcnemar() 既有行为（历史报告口径不变）。
# ---------------------------------------------------------------------------
def mcnemar_exact(n01: int, n10: int, alternative: str = "greater") -> float:
    """精确二项 McNemar：n01=改善对数，n10=退化对数（H0: p=0.5）

    alternative='greater'：单侧 P(X>=n01)，X~Bin(b,0.5)。b=5,n01=5 → 0.03125。
    alternative='two-sided'：双侧精确 p（2×较小尾，封顶 1.0）。
    """
    b = n01 + n10
    if b == 0:
        return 1.0
    if alternative == "greater":
        return sum(math.comb(b, k) for k in range(n01, b + 1)) / (2 ** b)
    if alternative == "two-sided":
        k = min(n01, n10)
        return min(1.0, 2 * sum(math.comb(b, i) for i in range(0, k + 1)) / (2 ** b))
    raise ValueError("alternative 只能是 'greater' 或 'two-sided'")


def _binom_tail(k: int, n: int, p: float, upper_tail: bool) -> float:
    """P(X>=k) 或 P(X<=k)，X~Bin(n,p)"""
    if upper_tail:
        return sum(math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(k, n + 1))
    return sum(math.comb(n, i) * (p ** i) * ((1 - p) ** (n - i)) for i in range(0, k + 1))


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> Tuple[float, float]:
    """二项比例 Clopper-Pearson 精确区间（二分法，免 scipy 依赖）"""
    if n <= 0:
        return (0.0, 1.0)
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if _binom_tail(k, n, mid, True) < alpha / 2:
            lo = mid
        else:
            hi = mid
    lower = (lo + hi) / 2
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if _binom_tail(k, n, mid, False) > alpha / 2:
            lo = mid
        else:
            hi = mid
    upper = (lo + hi) / 2
    return (lower, upper)


# ---------------------------------------------------------------------------
# Wilcoxon 符号秩检验（六分制连续分数）
# ---------------------------------------------------------------------------
def wilcoxon_signed_rank(scores_before: List[float], scores_after: List[float]) -> dict:
    """配对分数（0-5 分），检验 after 是否显著高于 before"""
    assert len(scores_before) == len(scores_after)
    diffs = [a - b for a, b in zip(scores_after, scores_before) if a != b]
    if not diffs:
        return {"w": 0, "p_value": 1.0, "n": 0}
    # 按绝对值排序
    abs_diffs = sorted(abs(d) for d in diffs)
    # 排名（处理 ties 用平均秩）
    ranks = {}
    i = 0
    while i < len(abs_diffs):
        j = i
        while j < len(abs_diffs) and abs_diffs[j] == abs_diffs[i]:
            j += 1
        avg_rank = (i + 1 + j) / 2  # 平均秩
        for k in range(i, j):
            ranks[abs_diffs[k]] = avg_rank
        i = j
    w_plus = sum(ranks[abs(d)] for d in diffs if d > 0)
    w_minus = sum(ranks[abs(d)] for d in diffs if d < 0)
    w = min(w_plus, w_minus)
    n = len(diffs)
    weights = [ranks[abs(d)] for d in diffs]  # 每个非零差值的秩（精确枚举用）
    # 正态近似（n>=10）
    if n >= 10:
        mean = n * (n + 1) / 4
        sd = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
        z = (w - mean) / sd if sd > 0 else 0
        p = 2 * (1 - _norm_cdf(abs(z)))
        return {"w": w, "z": z, "p_value": p, "n": n, "w_plus": w_plus, "w_minus": w_minus}
    # n<10：精确枚举（2026-11-01 补完"精确表未实现"缺口，替代原先恒为 None 的分支）
    p = _wilcoxon_exact_p(w_plus, weights)
    return {"w": w, "p_value": p, "n": n, "w_plus": w_plus, "w_minus": w_minus, "method": "exact"}


def _wilcoxon_exact_p(w_plus: float, weights: List[float]) -> float:
    """Wilcoxon 精确双侧 p（n<=15 可接受，2^n 上限 32768）。

    枚举全部符号分配得到 W+ 分布，p = 2*min(P(W+>=obs), P(W+<=obs))，截断到 1。
    含 tie 时用平均秩，与正态近似同口径（属近似精确）。
    """
    n = len(weights)
    if n > 15:
        return 1.0
    total = 1 << n
    cnt_ge = 0
    cnt_le = 0
    for mask in range(total):
        s = 0.0
        for i in range(n):
            if (mask >> i) & 1:
                s += weights[i]
        if s >= w_plus - 1e-9:
            cnt_ge += 1
        if s <= w_plus + 1e-9:
            cnt_le += 1
    return min(1.0, 2 * min(cnt_ge, cnt_le) / total)


# ---------------------------------------------------------------------------
# Cliff's delta（效应量）
# ---------------------------------------------------------------------------
def cliffs_delta(scores_before: List[float], scores_after: List[float]) -> dict:
    """非参数效应量，[-1, 1]，|d|>0.1 有意义，>0.33 中等，>0.47 大"""
    n = len(scores_before) * len(scores_after)
    if n == 0:
        return {"delta": 0, "n": 0}
    more = sum(1 for a in scores_after for b in scores_before if a > b)
    less = sum(1 for a in scores_after for b in scores_before if a < b)
    delta = (more - less) / n
    interpretation = "negligible"
    abs_d = abs(delta)
    if abs_d >= 0.47:
        interpretation = "large"
    elif abs_d >= 0.33:
        interpretation = "medium"
    elif abs_d >= 0.147:
        interpretation = "small"
    return {"delta": delta, "abs": abs_d, "interpretation": interpretation, "n": n}


# ---------------------------------------------------------------------------
# bootstrap CI（各维度 95% 区间）
# ---------------------------------------------------------------------------
def bootstrap_ci(scores: List[float], n_boot: int = 10000, confidence: float = 0.95) -> dict:
    """对分数均值做 bootstrap 置信区间"""
    if not scores:
        return {"mean": 0, "ci_low": 0, "ci_high": 0, "n": 0}
    n = len(scores)
    means = []
    for _ in range(n_boot):
        sample = [random.choice(scores) for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    alpha = (1 - confidence) / 2
    lo = means[int(n_boot * alpha)]
    hi = means[int(n_boot * (1 - alpha))]
    return {"mean": sum(scores) / n, "ci_low": lo, "ci_high": hi, "n": n, "confidence": confidence}


# ---------------------------------------------------------------------------
# D1 CLI：两份 eval 报告配对 → 四条件判定
# ---------------------------------------------------------------------------

def _load_tasks_set_map() -> dict:
    """eval/tasks.json → {task_id: set}（result.set 缺失时的回查源；
    动态题不在其中 → set=unknown，不进保留集）"""
    p = Path(__file__).parent / 'tasks.json'
    try:
        tasks = json.loads(p.read_text(encoding='utf-8'))
        return {t.get('id'): t.get('set') or 'unknown' for t in tasks}
    except Exception:
        return {}


def gate_from_reports(baseline_path: str, candidate_path: str, budget: float = 300.0) -> dict:
    """四条件判定（设计 Block D1）：
    1. veto 零命中：candidate 中 trap 题未被拦截（score<5，runner 对 trap 题只给 0/5）计数
    2. Wilcoxon p<0.05 且 Cliff |delta|>0.1（配对题分数）
    3. 保留集 CI 下界>0：candidate 冻结集（task.set=frozen）分数 bootstrap CI
    4. 成本 CI 上界<预算：candidate 每题 duration_s（兜底口径）bootstrap CI
    """
    base = json.loads(Path(baseline_path).read_text(encoding='utf-8'))
    cand = json.loads(Path(candidate_path).read_text(encoding='utf-8'))
    set_map = _load_tasks_set_map()

    # 2026-10-29：invalid（跑坏）行不进配对——与 runner summary 同口径，否则门槛会被"没跑起来"污染
    base_by = {r['task']: r for r in base.get('results', []) if r.get('valid') is not False}
    cand_by = {}  # P2-4：--repeat 同题多行取首条（k_pass 另算），避免后写覆盖
    _seen = set()
    for _r in cand.get('results', []):
        if _r.get('valid') is False: continue
        if _r['task'] in _seen: continue
        _seen.add(_r['task']); cand_by[_r['task']] = _r
    paired_ids = [tid for tid in cand_by if tid in base_by]
    notes = []

    if not paired_ids:
        return {
            'baseline': base.get('run_id'), 'candidate': cand.get('run_id'),
            'paired_n': 0, 'baseline_only': len(base_by) - len(paired_ids),
            'candidate_only': len(cand_by) - len(paired_ids),
            'pass_all': False,
            'conditions': {}, 'notes': ['配对题数为 0（两次 run 无同 id 题），门槛不可判定'],
        }

    # 条件1：veto 零命中（candidate trap 题全拦截）
    trap_ids = [tid for tid in cand_by if tid.startswith('trap')]
    veto_tasks = [tid for tid in trap_ids if cand_by[tid].get('score', 0) < 5]
    c1 = len(veto_tasks) == 0

    # 条件2：配对分数 Wilcoxon + Cliff
    sb = [float(base_by[tid]['score']) for tid in paired_ids]
    sa = [float(cand_by[tid]['score']) for tid in paired_ids]
    w = wilcoxon_signed_rank(sb, sa)
    d = cliffs_delta(sb, sa)
    c2 = bool(w.get('p_value') is not None and w['p_value'] < 0.05 and d.get('abs', 0) > 0.1)
    if w.get('p_value') is None:
        notes.append(f"Wilcoxon n={w.get('n')} 无 p 值，条件2 按不满足处理")
    elif int(w.get('n') or 0) < 6:
        notes.append(f"Wilcoxon n={w.get('n')}<6：精确双侧 p 最小约 {2 / (1 << int(w.get('n') or 1)):.4f}，样本不足以判显著（需 ≥6 道配对题全部改善）")

    # 条件3：保留集（frozen）candidate 分数 CI 下界>0
    frozen_ids = [
        tid for tid in paired_ids
        if (cand_by[tid].get('set') or set_map.get(tid) or 'unknown') == 'frozen'
    ]
    frozen_scores = [float(cand_by[tid]['score']) for tid in frozen_ids]
    if frozen_scores:
        ret_ci = bootstrap_ci(frozen_scores, n_boot=5000)
        c3 = ret_ci['ci_low'] > 0
    else:
        ret_ci = {'mean': 0, 'ci_low': 0, 'ci_high': 0, 'n': 0}
        c3 = False
        notes.append('配对题中无 frozen 集（保留集为空），条件3 按不满足处理（fail-closed）')

    # 条件4：成本 CI 上界<预算（duration 兜底口径，预算单位=秒；token 成本接入后改读 cost.tokens）
    durations = [cand_by[tid].get('cost', {}).get('duration_s') for tid in paired_ids]  # P0-1：runner 写嵌套 cost.duration_s
    durations = [float(x) for x in durations if isinstance(x, (int, float))]
    if durations:
        cost_ci = bootstrap_ci(durations, n_boot=5000)
        c4 = cost_ci['ci_high'] < budget
        notes.append(f'成本口径=duration_s 兜底（n={len(durations)}/{len(paired_ids)} 题有值，token 台账缺）')
    else:
        cost_ci = {'mean': 0, 'ci_low': 0, 'ci_high': float('inf'), 'n': 0}
        c4 = False
        notes.append('无 duration_s/tokens 成本数据（B2-5 成本台账落地前），条件4 不可算按不满足处理（fail-closed）')

    return {
        'baseline': base.get('run_id'), 'candidate': cand.get('run_id'),
        'paired_n': len(paired_ids),
        'baseline_only': len(base_by) - len(paired_ids),
        'candidate_only': len(cand_by) - len(paired_ids),
        'conditions': {
            'veto_zero': {'met': c1, 'detail': f'trap {len(trap_ids) - len(veto_tasks)}/{len(trap_ids)} 拦截'
                          + (f'，未拦截: {veto_tasks}' if veto_tasks else '')},
            'wilcoxon_significant': {'met': c2, 'detail': f"p={w.get('p_value')}, delta={d.get('delta')}, |delta|={d.get('abs')}",
                                     'wilcoxon': w, 'cliffs': d},
            'retention_ci_positive': {'met': c3, 'detail': f'frozen n={len(frozen_ids)}, ci_low={ret_ci["ci_low"]:.3f}',
                                      'ci': ret_ci},
            'cost_under_budget': {'met': c4, 'detail': f'ci_high={cost_ci["ci_high"]:.1f}s < 预算 {budget}s（duration 兜底口径）',
                                  'ci': cost_ci, 'budget': budget},
        },
        'pass_all': c1 and c2 and c3 and c4,
        'notes': notes,
    }


def _append_eval_status(gate: dict, cand_path: str) -> str:
    """D6 适配（runner.mjs 归 sub-B2，故记账挂在 stats.py）：批跑+门槛判定后
    自动往 eval/EVAL_STATUS.md 历史记录表 append 一行摘要"""
    status_path = Path(__file__).parent / 'EVAL_STATUS.md'
    if not status_path.exists():
        return 'EVAL_STATUS.md 不存在，跳过记账'
    try:
        cand = json.loads(Path(cand_path).read_text(encoding='utf-8'))
    except Exception:
        return 'candidate 报告不可读，跳过记账'
    # 2026-10-29：口径与 runner summary 对齐——invalid（跑坏）行不计分母，避免台账通过率被"没跑起来"拉低
    res = [r for r in cand.get('results', []) if r.get('valid') is not False]
    passed = sum(1 for r in res if (r.get('score') or 0) >= 4)
    # trap 口径优先取报告 summary（含多轮 trap 类），与 runner 打印的"trap 否决 x/y"一致；
    # 旧实现只数 task 前缀 trap-*，会把多轮 trap（yield/bleed/residue）漏掉，台账与报告打架。
    summ = cand.get('summary') or {}
    if summ.get('trap_total') is not None:
        trap_cell = f"{summ.get('trapBlockedCount', 0)}/{summ['trap_total']}"
    else:
        traps = [r for r in res if str(r.get('task', '')).startswith('trap')]
        trap_cell = f"{sum(1 for r in traps if (r.get('score') or 0) >= 5)}/{len(traps)}"
    conds = gate.get('conditions') or {}
    met = sum(1 for c in conds.values() if c.get('met'))
    # 三态：无门槛判定（首跑/--status-only）如实写"单跑未判"，不伪装成 ❌ 0/4
    gate_cell = '—（单跑未判）' if not conds else f"{'✅' if gate.get('pass_all') else '❌'} {met}/{len(conds)}"
    date = (cand.get('timestamp') or '')[:16].replace('T', ' ') or '—'
    pass_cell = f'{passed}/{len(res)}={passed / len(res) * 100:.0f}%' if res else '—'
    row = (f"| {date} | {cand.get('agent_release') or '—'} | {pass_cell} "
           f"| {trap_cell} | {gate_cell} "
           f"| run_id={cand.get('run_id')}；baseline={gate.get('baseline') or '—'}（stats.py 自动记） |\n")
    text = status_path.read_text(encoding='utf-8')
    anchor = '## 历史记录'
    if anchor in text:
        head, tail = text.split(anchor, 1)
        lines = tail.split('\n')
        # 插到历史记录表末尾（下一个空行/二级标题前）
        insert_at = 0
        for i, ln in enumerate(lines):
            if ln.startswith('|'):
                insert_at = i + 1
        if insert_at == 0:  # 表尚未起行（只有表头前的文字），接在标题后
            insert_at = 1
        lines.insert(insert_at, row.rstrip('\n'))
        status_path.write_text(head + anchor + '\n'.join(lines), encoding='utf-8')
    else:
        with status_path.open('a', encoding='utf-8') as f:
            f.write(f'\n{anchor}\n\n| 日期 | 版本 | 通过率 | trap否决 | 门槛 | 备注 |\n|---|---|---|---|---|---|\n{row}')
    return f'已记入 {status_path}'


def main():
    ap = argparse.ArgumentParser(description='D1 发版门槛：两份 eval 报告配对四条件判定')
    ap.add_argument('--baseline', help='eval/reports/<旧 run_id>.json（--status-only 时可省）')
    ap.add_argument('--candidate', required=True, help='eval/reports/<新 run_id>.json')
    ap.add_argument('--budget', type=float, default=300.0,
                    help='成本预算（秒/题，duration 兜底口径；per-题超时 300s 对齐）')
    ap.add_argument('--json-out', help='判定 JSON 另存路径（缺省只打印）')
    ap.add_argument('--no-status', action='store_true', help='不自动记 EVAL_STATUS.md（D6）')
    ap.add_argument('--status-only', action='store_true',
                    help='只往 EVAL_STATUS.md 记一行台账，不做配对判定（2026-10-29：runner 无同版本基线时用）')
    args = ap.parse_args()

    # 2026-10-29 进主流程：无基线（首跑/判据已变）也要能自动记账——只记通过率与 trap，
    # 门槛列如实写"单跑未判"，不伪装成 ❌ 0/4。
    if args.status_only:
        gate = {'baseline': None, 'candidate': None, 'conditions': {}, 'pass_all': None,
                'notes': ['--status-only：未做配对判定']}
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding='utf-8')
        print('=' * 60)
        print('  单跑记账（--status-only）')
        print('=' * 60)
        if not args.no_status:
            print(_append_eval_status(gate, args.candidate))
        sys.exit(0)

    if not args.baseline:
        ap.error('--baseline 必填（或改用 --status-only 只记账）')

    random.seed(42)  # bootstrap 可复算
    gate = gate_from_reports(args.baseline, args.candidate, budget=args.budget)

    print('=' * 60)
    print('  发版门槛 · 四条件（stats.py D1）')
    print('=' * 60)
    print(f"  baseline : {gate['baseline']}（独有 {gate['baseline_only']} 题）")
    print(f"  candidate: {gate['candidate']}（独有 {gate['candidate_only']} 题）")
    print(f"  配对题数 : {gate['paired_n']}")
    for name, c in gate['conditions'].items():
        print(f"  {'✅' if c['met'] else '❌'} {name}: {c['detail']}")
    for n in gate['notes']:
        print(f"  注: {n}")
    print(f"  结论: pass_all={str(gate['pass_all']).lower()}")
    print('=' * 60)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'判定 JSON: {args.json_out}')
    if not args.no_status:
        print(_append_eval_status(gate, args.candidate))
    sys.exit(0 if gate['pass_all'] else 1)


# ---------------------------------------------------------------------------
# 发版门槛
# ---------------------------------------------------------------------------
def release_gate(
    veto_hits: int,
    wilcoxon: dict,
    cliffs: dict,
    retention_ci: dict,
    cost_ci: dict,
    budget: float,
) -> dict:
    """4 条件发版门槛"""
    c1 = veto_hits == 0
    c2 = wilcoxon.get("p_value", 1) < 0.05 and cliffs.get("abs", 0) > 0.1
    c3 = retention_ci.get("ci_low", 0) > 0
    c4 = cost_ci.get("ci_high", float("inf")) < budget
    return {
        "veto_zero": c1,
        "wilcoxon_significant": c2,
        "retention_ci_positive": c3,
        "cost_under_budget": c4,
        "pass_all": c1 and c2 and c3 and c4,
    }


# ---------------------------------------------------------------------------
# 入口：--baseline/--candidate → D1 门槛判定；无参 → 原 T-2.4.3 冒烟
# ---------------------------------------------------------------------------
if __name__ == "__main__" and ('--baseline' in sys.argv or '--status-only' in sys.argv):
    main()

elif __name__ == "__main__":
    # 原 T-2.4.3 冒烟（python eval/stats.py 无参）
    print("=" * 60)
    print("  T-2.4.3 统计栈 · 冒烟")
    print("=" * 60)

    # McNemar
    before = [True, False, True, False, True, False, True, False]
    after = [True, True, True, True, True, True, False, True]
    m = mcnemar(before, after)
    print(f"\nMcNemar: {m}")

    # Wilcoxon
    sb = [2, 3, 2, 4, 3, 2, 3, 4, 2, 3]
    sa = [4, 4, 3, 5, 4, 3, 4, 5, 3, 4]
    w = wilcoxon_signed_rank(sb, sa)
    print(f"Wilcoxon: {w}")

    # Cliff's delta
    d = cliffs_delta(sb, sa)
    print(f"Cliff's delta: {d}")

    # bootstrap CI
    ci = bootstrap_ci(sa, n_boot=5000)
    print(f"bootstrap CI: {ci}")

    # 发版门槛
    cost_ci = bootstrap_ci([0.5, 0.6, 0.55, 0.48, 0.52], n_boot=2000)
    gate = release_gate(0, w, d, ci, cost_ci, budget=1.0)
    print(f"\n发版门槛: {gate}")

    print("\n" + "=" * 60)
    print("  T-2.4.3 冒烟通过 ✅")
    print("=" * 60)
