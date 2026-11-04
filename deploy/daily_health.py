# -*- coding: utf-8 -*-
"""Prism 每日巡检汇总（A2，2026-11-02）

设计口径：
- 只陈述事实，不做推断；异常项置顶，正常项折叠。
- 巡检目标 = 云端真源（本脚本部署在 ECS，由 cron 08:00 运行）。
- 输出：$PRISM_ROOT/data/health/latest.json + YYYY-MM-DD.md
- latest.json 由 prism-api `GET /health/report` 读取（走登录门禁）。

运行：python3 deploy/daily_health.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import ssl
import subprocess
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(os.environ.get('PRISM_ROOT', '/root/prism'))
DATA = ROOT / 'data'
OUT = DATA / 'health'
TZ = timezone(timedelta(hours=8))

# 阈值（超过即异常）
TH_SENTIMENT_H = 36
TH_WEEKLY_D = 10
TH_SALES_D = 45
TH_EVENTS_H = 72
TH_CERT_D = 14


def _now() -> datetime:
    return datetime.now(TZ)


def _query(db: Path, sql: str):
    """只读查询；库不存在或查询失败返回 (None, 错误原因)。"""
    if not db.exists():
        return None, f'库不存在: {db.name}'
    try:
        c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        try:
            return c.execute(sql).fetchone(), ''
        finally:
            c.close()
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def _parse_dt(value):
    """解析常见时间串，返回带时区 datetime 或 None。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s2 = s.replace('T', ' ').split('.')[0]
    if len(s2) >= 19:
        try:
            # 库内时间统一按 UTC 存储（实测 analyzed_at/fetched_at 均比本地早 8h）
            return datetime.strptime(s2[:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.strptime(s[:10], '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _age_hours(value):
    dt = _parse_dt(value)
    if dt is None:
        return None
    return (_now() - dt).total_seconds() / 3600.0


def _age_text(hours: float) -> str:
    """人话化时间差；本地采集时间可能略晚于 UTC 基准，负值统一显示「刚刚」。"""
    if hours <= 0:
        return '刚刚'
    if hours < 48:
        return f'{hours:.1f} 小时前'
    return f'{hours / 24:.1f} 天前'


def _item(name, status, detail, threshold=''):
    return {'name': name, 'status': status, 'detail': detail, 'threshold': threshold}


def check_services():
    expect = [
        ('prism-prism-api-1', 'healthy'),
        ('prism-prism-dashboards-1', 'healthy'),
        ('prism-prism-sentiment-1', 'healthy'),
        ('prism-prism-ops-1', 'Up'),
        ('prism-prism-nginx-1', 'Up'),
    ]
    ok, bad = 0, []
    for name, want in expect:
        try:
            out = subprocess.run(
                ['docker', 'ps', '--filter', f'name={name}', '--format', '{{.Status}}'],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
        except Exception as e:  # noqa: BLE001
            out = f'ERR {e}'
        if want.lower() in out.lower():
            ok += 1
        else:
            bad.append(f'{name}={out or "not running"}')
    if bad:
        return _item('服务探活', 'abnormal', f'{ok}/{len(expect)} 正常；异常：' + '，'.join(bad))
    return _item('服务探活', 'ok', f'{ok}/{len(expect)} 正常')


def check_sentiment():
    row, err = _query(DATA / 'vehicle_sentiment.db', 'SELECT MAX(analyzed_at) FROM analyzed_posts')
    if err:
        return _item('舆情数据', 'abnormal', f'查询失败：{err}')
    val = row[0] if row else None
    age = _age_hours(val)
    if age is None:
        return _item('舆情数据', 'abnormal', '无 analyzed_at 记录')
    detail = f'最后 {val}（{_age_text(age)}）'
    return _item('舆情数据', 'abnormal' if age > TH_SENTIMENT_H else 'ok', detail, f'>{TH_SENTIMENT_H}h')


def check_reviews():
    row, err = _query(DATA / 'autohome.db', 'SELECT MAX(fetched_at) FROM owner_reviews')
    if err:
        return _item('口碑数据', 'abnormal', f'查询失败：{err}')
    val = row[0] if row else None
    age = _age_hours(val)
    if age is None:
        return _item('口碑数据', 'abnormal', '无 fetched_at 记录')
    detail = f'最后 {val}（{_age_text(age)}）'
    return _item('口碑数据', 'abnormal' if age > TH_WEEKLY_D * 24 else 'ok', detail, f'>{TH_WEEKLY_D}d')


def check_config():
    row, err = _query(DATA / 'autohome.db', 'SELECT MAX(fetched_at) FROM config_snapshots')
    if err:
        return _item('配置数据', 'abnormal', f'查询失败：{err}')
    val = row[0] if row else None
    age = _age_hours(val)
    if age is None:
        return _item('配置数据', 'abnormal', '无 fetched_at 记录')
    detail = f'最后 {val}（{_age_text(age)}）'
    return _item('配置数据', 'abnormal' if age > TH_WEEKLY_D * 24 else 'ok', detail, f'>{TH_WEEKLY_D}d')


def check_sales():
    row, err = _query(
        DATA / 'autohome.db',
        "SELECT year, month FROM sales_trim WHERE month LIKE '%月末' "
        'ORDER BY year DESC, CAST(month AS INTEGER) DESC LIMIT 1',
    )
    if err:
        return _item('销量数据', 'abnormal', f'查询失败：{err}')
    if not row or row[0] is None:
        return _item('销量数据', 'abnormal', '无月末销量记录')
    year, month = int(row[0]), int(str(row[1]).replace('月末', ''))
    # 月末口径：下月 1 日减 1 天
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=TZ) - timedelta(days=1)
    else:
        end = datetime(year, month + 1, 1, tzinfo=TZ) - timedelta(days=1)
    age_d = (_now() - end).total_seconds() / 86400.0
    detail = f'最新 {year}-{month:02d} 月末（{age_d:.0f} 天前）'
    return _item('销量数据', 'abnormal' if age_d > TH_SALES_D else 'ok', detail, f'>{TH_SALES_D}d')


def check_events():
    row, err = _query(DATA / 'prism_events.db', 'SELECT MAX(ts) FROM events')
    if err:
        return _item('埋点链路', 'abnormal', f'查询失败：{err}')
    val = row[0] if row else None
    age = _age_hours(val)
    if age is None:
        return _item('埋点链路', 'abnormal', '无事件记录')
    detail = f'最近事件 {val}（{age / 24:.1f} 天前）'
    return _item('埋点链路', 'abnormal' if age > TH_EVENTS_H else 'ok', detail, f'>{TH_EVENTS_H}h')


def check_cert():
    try:
        # getpeercert() 在 CERT_NONE 下返回空 dict，改走 openssl 取 enddate
        p = subprocess.run(
            'openssl s_client -connect 127.0.0.1:443 -servername prism-agent.example.com '
            '</dev/null 2>/dev/null | openssl x509 -noout -enddate',
            shell=True, capture_output=True, text=True, timeout=10,
        )
        line = p.stdout.strip()
        if 'notAfter=' not in line:
            return _item('HTTPS 证书', 'abnormal', f'读取失败：{line[:80] or "无输出"}')
        val = line.split('notAfter=', 1)[1].strip()
        ts = ssl.cert_time_to_seconds(val)
        days = int((ts - datetime.now(timezone.utc).timestamp()) / 86400)
        not_after = datetime.fromtimestamp(ts, tz=timezone.utc)
        return _item('HTTPS 证书', 'abnormal' if days < TH_CERT_D else 'ok',
                     f'剩余 {days} 天（至 {not_after.astimezone(TZ):%Y-%m-%d}）', f'<{TH_CERT_D}d')
    except Exception as e:  # noqa: BLE001
        return _item('HTTPS 证书', 'abnormal', f'读取失败：{e}')


def check_ingest_today():
    """今日新增入库帖数（本地日口径，2026-11-03 补）。

    库内 collected_at 存 UTC（实测比本地早 8h）：本地 03:00 采集在库里记的是
    前一日 19:00。因此起点必须把本地 00:00 换算成 UTC 再比较——直接按本地日期
    做 LIKE 会把凌晨采集漏成 0 条（该口径曾导致误判"采集空转"）。
    只陈述事实，不做阈值判断：无新内容不等于故障。
    """
    start_local = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    row, err = _query(
        DATA / 'vehicle_sentiment.db',
        "SELECT COUNT(*) FROM raw_posts WHERE collected_at >= '%s'" % start_utc,
    )
    if err or not row:
        return _item('今日入库', 'info', err or '库不可读')
    return _item('今日入库', 'ok', f'{int(row[0])} 条')


def check_collect_log():
    candidates = [ROOT / 'logs' / 'sentiment_daily.log', ROOT / 'logs' / 'sentiment_daily_manual.log']
    existing = [p for p in candidates if p.exists()]
    if not existing:
        return {'name': '采集任务日志', 'status': 'info', 'detail': '尚无日志（首次 cron 未运行）'}
    log = max(existing, key=lambda p: p.stat().st_mtime)
    lines = [ln.strip() for ln in log.read_text(encoding='utf-8', errors='ignore').splitlines() if ln.strip()]
    last = lines[-1] if lines else '空日志'
    mtime = datetime.fromtimestamp(log.stat().st_mtime, tz=TZ)
    return {'name': '采集任务日志', 'status': 'info',
            'detail': f'{log.name}（{mtime:%m-%d %H:%M}）{last[-140:]}'}


def render_md(report):
    items = report['items']
    abnormal = [i for i in items if i['status'] == 'abnormal']
    normal = [i for i in items if i['status'] == 'ok']
    head = f"系统健康 · {report['date']} 08:00"
    head += f"　⚠ 异常 {len(abnormal)} 项" if abnormal else '　✓ 全部正常'
    out = [f'# {head}', '']
    if abnormal:
        out.append('## 异常（置顶）')
        for i in abnormal:
            th = f"（阈值 {i['threshold']}）" if i.get('threshold') else ''
            out.append(f"- ⚠ **{i['name']}**：{i['detail']}{th}")
        out.append('')
    if normal:
        out.append('<details><summary>正常项（' + str(len(normal)) + '）</summary>')
        out.append('')
        for i in normal:
            out.append(f"- ✓ {i['name']}：{i['detail']}")
        out.append('')
        out.append('</details>')
        out.append('')
    if report.get('trend'):
        out.append('## 趋势观察（不计入异常）')
        for t in report['trend']:
            out.append(f"- {t['name']}：{t['detail']}")
        out.append('')
    out.append(f"> 生成时间：{report['generated_at']}　守卫：只陈述事实，不做推断")
    return '\n'.join(out) + '\n'


def main():
    now = _now()
    items = [
        check_services(),
        check_sentiment(),
        check_ingest_today(),
        check_reviews(),
        check_config(),
        check_sales(),
        check_events(),
        check_cert(),
    ]
    report = {
        'date': now.strftime('%Y-%m-%d'),
        'generated_at': now.strftime('%Y-%m-%d %H:%M:%S'),
        'abnormal_count': sum(1 for i in items if i['status'] == 'abnormal'),
        'items': items,
        'trend': [
            {'name': 'badcase 四象限', 'detail': '未接入（数据在本地 eval，不在云端）'},
            check_collect_log(),
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'latest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / f"{report['date']}.md").write_text(render_md(report), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

