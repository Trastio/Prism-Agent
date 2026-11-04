# -*- coding: utf-8 -*-
"""舆情工具层跟进 · Step9 E2E 真对话验收（2026-10-20）
用法: python openspec/changes/舆情工具层跟进/e2e_check.py
前置: 五服务在跑（网关 9200 已带新 extension 重启）

两问验收：
Q1 银河E5（paused 车）→ 期待：调舆情工具拿到冻结数据，回复含"停更/冻结"语义，
   不出现"不在舆情系统收录范围"误报；出口闸 verdict=pass
Q2 风云T7 缺陷 → 期待：调 sentiment_defects，回复含缺陷簇内容（如"配置"类簇）；
   出口闸 verdict=pass（sentiment_defects 引用或其它合法引用）
"""
import json
import sys
import time
import urllib.request

BASE = 'http://127.0.0.1:8002'
PASS = '666666'


def login():
    req = urllib.request.Request(
        f'{BASE}/auth/login',
        data=json.dumps({'username': 'e2e-sentiment-followup', 'password': PASS}).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    res = urllib.request.urlopen(req, timeout=5)
    sc = res.headers.get('Set-Cookie', '')
    tok = sc.split('prism_token=')[1].split(';')[0] if 'prism_token=' in sc else ''
    assert tok, f'登录失败: {sc!r}'
    return tok


def traj_pass(since_iso, sid_hint=None):
    """settled 事件 verdict=None 是已知时序竞态（mapEvent 读 verdict.json 早于 extension
    写入）——回退读 .pi/sessions/trajectories.jsonl 的真实判定。
    P1-2（Step7 审查）三修：①按时间窗过滤（只取本轮问句开始后的行，防并发/上一问误配对）
    ②只认含 submission 的行（默认放行轮无 submission 不算判定）③取窗口内最后一行（回灌轮
    count 递增，末行=终态判定）。sid_hint 给出时再按 sessionId 收窄。"""
    try:
        rows = []
        for l in open('.pi/sessions/trajectories.jsonl', encoding='utf-8'):
            if l.strip():
                r = json.loads(l)
                rows.append(json.loads(r) if isinstance(r, str) else r)
        cand = [r for r in rows
                if str(r.get('timestamp', '')) >= since_iso
                and isinstance(r.get('submission'), dict)
                and (sid_hint is None or r.get('sessionId') == sid_hint)]
        if not cand:
            return None
        return bool(cand[-1]['submission'].get('pass'))
    except OSError:
        return None


def ask(tok, message, budget=180):
    """POST /chat/stream 收 NDJSON 流到 settled；聚合回复文本+工具调用+verdict。"""
    req = urllib.request.Request(
        f'{BASE}/chat/stream',
        data=json.dumps({'user_id': 'e2e-sentiment-followup', 'message': message}).encode(),
        headers={'Content-Type': 'application/json', 'Cookie': f'prism_token={tok}'}, method='POST')
    text, tools, verdict, settled = [], [], None, False
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=budget) as res:
        for raw in res:
            if time.time() - t0 > budget:
                break
            line = raw.decode('utf-8', errors='replace').strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ev.get('type')
            d = ev.get('data') or {}
            if t == 'text_delta':
                text.append(d.get('text', ''))
            elif t == 'tool_call':
                tools.append(d.get('name'))
            elif t == 'settled':
                settled = True
                verdict = ev.get('verdict')
    return ''.join(text), tools, verdict, settled, time.time() - t0


def main():
    tok = login()
    cases = [
        ('银河E5 舆情怎么样', ['停更', '冻结'], ['不在舆情系统收录范围']),
        ('风云T7 车主都在吐槽什么缺陷', ['配置'], []),
    ]
    ok = True
    for msg, must_have, must_not in cases:
        # 轨迹 timestamp 为 UTC（extension utcnow）——窗口锚点必须同用 UTC（gmtime），
        # 用 localtime 会把窗口整体后移 8h 导致全行被滤掉（时区 bug，已修）
        since = time.strftime('%Y-%m-%dT%H:%M', time.gmtime())
        text, tools, verdict, settled, dur = ask(tok, msg)
        print(f'\n=== Q: {msg} ({dur:.0f}s, settled={settled}, verdict={verdict and verdict.get("pass")})')
        print(f'工具链: {tools}')
        print(f'回复({len(text)}字): {text[:600]}')
        for kw in must_have:
            hit = kw in text
            print(f'[{"✓" if hit else "✗"}] 含关键词: {kw}')
            ok = ok and hit
        for kw in must_not:
            hit = kw in text
            print(f'[{"✗" if hit else "✓"}] 不含误报: {kw}')
            ok = ok and not hit
        # 出口闸判定：settled 事件优先，竞态缺 verdict 时回退 trajectories 窗口末行
        p = verdict.get('pass') if verdict else traj_pass(since)
        src = 'settled' if verdict else 'trajectories'
        if p is None:
            print(f'[✗] 出口闸判定缺失（{src} 无记录）')
            ok = False
        else:
            print(f'[{"✓" if p else "✗"}] 出口闸 pass（{src}）')
            ok = ok and p
    print('\n=== E2E 总判:', 'PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
