"""启动自检（dashboard-v8 Task 3.3 → v9 Task 5 资产一致性扩展）。

检测派生数据/资产的已知盲区，在看板顶部以黄牌提示运维操作：
- config_snapshots fetched_at 早于版本新鲜度阈值 → snapshot_stale（跑 collect_config_snapshots.py）
- 资产文件缺失/坏 JSON → asset_file_missing（option_prices/concept_weights/concept_configs）
- 口碑陈旧（owner_reviews 最新 post_date 距今超阈值）→ koubei_stale
- 无正文比例异常（>50% 口碑无 best_review_text）→ no_text_ratio_high
- 车系元数据陈旧（series_summaries updated_at 超阈值）→ metadata_stale

新鲜度阈值绑解析版本号（v9 Task 5.1）：PARSE_LOGIC_VERSION + _VERSION_DATES 映射，
每次解析逻辑变更（字体解码/字段还原/4态判读等）后递增版本号并登记发布日期，
快照 fetched_at 早于当前版本发布日期 → 判陈旧（需重采）。

自检为只读查询（COUNT/MIN/文件 stat），结果短 TTL 缓存（_CACHE_TTL 秒）——
selfcheck 是运维提示不要求秒级新鲜，缓存避免 /health 与 dashboard_index 每请求重算
6 查询 + 3 文件 IO。DB 引擎变更（测试切临时库）自动失效缓存。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

# 解析逻辑版本号：每次解析逻辑变更（字体解码/字段还原/4态判读/统一语义等）后递增。
# 快照 fetched_at 早于此版本发布日期 → 判陈旧（需重采）。
PARSE_LOGIC_VERSION = "v9"
_VERSION_DATES = {
    "v7": "2026-09-27",  # v7-hardening 合并（字段还原 + 字体丢字检测）
    "v8": "2026-09-29",  # v8 4态状态模型 + 阶梯真形态
    "v9": "2026-10-01",  # v9 字体解码 + 统一语义 + 资产自检
}
SNAPSHOT_FRESHNESS_DATE = _VERSION_DATES[PARSE_LOGIC_VERSION]

# 资产文件清单（相对项目 data/ 目录）：
# - REQUIRED：随仓库发行的必要资产，缺失或坏 JSON → 黄牌
# - OPTIONAL：用户维护（gitignore），缺失=空表（正常态）仅坏 JSON → 黄牌
_REQUIRED_ASSETS = ("concept_configs.json", "concept_weights.json")
_OPTIONAL_ASSETS = ("option_prices.json",)

# 陈旧阈值（天）：超过则黄牌
_KOUBEI_STALE_DAYS = 180      # owner_reviews 最新 post_date 距今超 180 天 → 口碑陈旧
_METADATA_STALE_DAYS = 180    # series_summaries updated_at 超 180 天 → 元数据陈旧
_NO_TEXT_RATIO_THRESHOLD = 0.5  # 无正文口碑占比 > 50% → 异常
# dashboard-v10 Task 1.1：字体解码命中率阈值 < 0.9 → 黄牌（之家可能改了加密算法）
_DECODE_HIT_RATE_THRESHOLD = 0.9

# 2026-10-14 概念映射一致性（NOA/差价方向根因配套，防再犯）：extract=boolean 的项若命中
# 字段值以「文本」为主（复合枚举/品牌名，如 辅助驾驶系统=猎鹰500、前排侧气囊="前● / 后●"），
# 说明字段形态与 extract 期望不符 → 看板展示与差价 presence 判读会失真（如"城市NOA"误显示
# 智驾系统品牌名），应改用 extract=sublist_contains + extract_pattern。出现任何此类项 → 黄牌。
# 2026-10-14：C1/C2/I1/D1/D2/D3/E4/F6/G4 已全部治理 → 白名单清空（新增项即告警）。
_CONCEPT_MISMATCH_KNOWN: set[str] = set()
_CONCEPT_MISMATCH_TEXT_RATIO = 0.3
_CONCEPT_MISMATCH_SAMPLE = 15

# S2：短 TTL 缓存——selfcheck 是运维提示不要求秒级新鲜，避免每请求 6 查询 + 3 文件 IO。
# DB 引擎变更（测试 tmp_db 切库 / 生产重启）自动失效。
_CACHE_TTL = 45  # 秒
_cache: dict = {}  # {"ts": float, "engine_url": str, "state": dict}


def _data_dir() -> Path:
    """项目 data/ 目录（Path(__file__) 绝对定位，不依赖 cwd）。"""
    return Path(__file__).parent.parent.parent / "data"


def _current_engine_url() -> str:
    """当前 DB 引擎 URL（用于缓存键；引擎变更 → 缓存失效）。"""
    try:
        from src.storage.db import _engine
        if _engine is not None:
            return str(_engine.url)
    except Exception:
        pass
    return ""


def _compute_selfcheck() -> dict:
    """计算并缓存自检状态（warnings + latest_post + owner_reviews_exists）。

    返回 {"warnings": list[dict], "latest_post": str|None,
          "owner_reviews_exists": bool}。
    短 TTL 缓存（_CACHE_TTL 秒）；DB 引擎 URL 变更时自动重算（测试切临时库即失效）。
    """
    now = time.time()
    eurl = _current_engine_url()
    c = _cache
    if c and (now - c.get("ts", 0) < _CACHE_TTL) and c.get("engine_url") == eurl:
        return c["state"]
    state = _do_selfcheck()
    _cache.clear()
    _cache.update(ts=now, engine_url=eurl, state=state)
    return state


def selfcheck_warnings() -> list[dict]:
    """返回黄牌列表，每项 {"code", "level", "msg"}。空列表=全通过。

    结果短 TTL 缓存（_CACHE_TTL 秒），DB 引擎变更自动失效。"""
    return _compute_selfcheck()["warnings"]


def _do_selfcheck() -> dict:
    """实际计算自检状态（不缓存）。返回 {"warnings", "latest_post",
    "owner_reviews_exists"}。latest_post 供 /health data_freshness 复用，
    避免重复 MAX(post_date) 查询（S1）。"""
    from sqlalchemy import inspect as sa_inspect, text

    from src.storage.db import session_scope

    warnings: list[dict] = []
    latest_post: str | None = None
    owner_reviews_exists = False
    with session_scope() as s:
        inspector = sa_inspect(s.bind)

        # 1. config_snapshots 陈旧（阈值绑版本号）+ decode_hit_rate 低（v10 Task 1.1）
        # v7 单表化：原"series_alias 表空"黄牌检查已删（该表与加权表整体退役）。
        if inspector.has_table("config_snapshots"):
            min_fa = s.execute(
                text("SELECT MIN(fetched_at) FROM config_snapshots")).scalar()
            if min_fa:
                fa = _parse_dt(min_fa)
                threshold = _parse_dt(SNAPSHOT_FRESHNESS_DATE)
                if fa and threshold and fa < threshold:
                    warnings.append({
                        "code": "snapshot_stale",
                        "level": "warn",
                        "msg": f"配置快照陈旧（最早 fetched_at={min_fa}，"
                               f"早于 {SNAPSHOT_FRESHNESS_DATE} {PARSE_LOGIC_VERSION} 修复），"
                               "请运行 python scripts/collect_config_snapshots.py --max-age-days 7",
                    })
            # dashboard-v10 Task 1.1：字体解码命中率 < 0.9 → 黄牌
            # 只查非 NULL（迁移前旧快照无此字段，不判）；MIN 低于阈值即告警
            try:
                min_dhr = s.execute(text(
                    "SELECT MIN(decode_hit_rate) FROM config_snapshots "
                    "WHERE decode_hit_rate IS NOT NULL")).scalar()
                if min_dhr is not None and min_dhr < _DECODE_HIT_RATE_THRESHOLD:
                    warnings.append({
                        "code": "decode_hit_rate_low",
                        "level": "warn",
                        "msg": f"字体解码覆盖率低（最低 decode_hit_rate={min_dhr:.2f}，"
                               f"< {_DECODE_HIT_RATE_THRESHOLD} 阈值），"
                               "之家可能改了加密算法，请检查 _clean_anti_scraping/字体映射",
                    })
            except Exception:
                pass  # 列不存在（未迁移）→ 跳过，不阻断自检

            # 7. 概念映射一致性审计（2026-10-14 NOA/差价方向根因配套，防再犯）
            warnings.extend(_concept_mismatch_warnings(s))

        # 3. 口碑陈旧（owner_reviews 最新 post_date 距今超阈值）
        if inspector.has_table("owner_reviews"):
            owner_reviews_exists = True
            max_post = s.execute(
                text("SELECT MAX(post_date) FROM owner_reviews "
                     "WHERE post_date IS NOT NULL AND post_date != ''")
            ).scalar()
            latest_post = max_post  # 供 /health data_freshness 复用（S1）
            if max_post:
                pd = _parse_dt(max_post)
                if pd:
                    days = (datetime.now() - pd).days
                    if days > _KOUBEI_STALE_DAYS:
                        warnings.append({
                            "code": "koubei_stale",
                            "level": "warn",
                            "msg": f"口碑数据陈旧（最新 post_date={max_post}，"
                                   f"距今 {days} 天超 {_KOUBEI_STALE_DAYS} 天阈值），"
                                   "建议重新采集口碑",
                        })

            # 4. 无正文比例异常（>50% 口碑无 best_review_text）
            total_rv = s.execute(text("SELECT COUNT(*) FROM owner_reviews")).scalar()
            if total_rv and total_rv > 0:
                no_text_n = s.execute(text(
                    "SELECT COUNT(*) FROM owner_reviews "
                    "WHERE best_review_text IS NULL OR best_review_text = ''"
                )).scalar()
                ratio = (no_text_n or 0) / total_rv
                if ratio > _NO_TEXT_RATIO_THRESHOLD:
                    warnings.append({
                        "code": "no_text_ratio_high",
                        "level": "warn",
                        "msg": f"无正文口碑占比过高（{no_text_n}/{total_rv}="
                               f"{ratio:.0%}，超 {_NO_TEXT_RATIO_THRESHOLD:.0%} 阈值），"
                               "标签覆盖率/提及率分母（taggable）会偏小，分析结论可信度受限",
                    })

        # 5. 车系元数据陈旧（series_summaries updated_at 超阈值）
        if inspector.has_table("series_summaries"):
            max_upd = s.execute(
                text("SELECT MAX(updated_at) FROM series_summaries "
                     "WHERE updated_at IS NOT NULL")
            ).scalar()
            if max_upd:
                ud = _parse_dt(str(max_upd))
                if ud:
                    days = (datetime.now() - ud).days
                    if days > _METADATA_STALE_DAYS:
                        warnings.append({
                            "code": "metadata_stale",
                            "level": "warn",
                            "msg": f"车系元数据陈旧（series_summaries 最新 updated_at="
                                   f"{max_upd}，距今 {days} 天超 {_METADATA_STALE_DAYS} 天），"
                                   "建议重新拉取车系概览",
                        })

    # 6. 资产文件可用性（option_prices/concept_weights/concept_configs 存在且合法 JSON）
    warnings.extend(_check_asset_files())
    return {
        "warnings": warnings,
        "latest_post": latest_post,
        "owner_reviews_exists": owner_reviews_exists,
    }


def _concept_mismatch_warnings(s) -> list[dict]:
    """概念映射一致性审计（抽样 config_snapshots）：extract=boolean 项命中字段值的
    「文本」占比超阈值 → 字段形态与 extract 期望不符。只报不在已知白名单的新 id
    （防再犯）。只读、抽样、异常静默（不阻断自检主流程）。"""
    try:
        from src.models.orm import ConfigSnapshot
        from src.insights.concept_config import (_load_configs, _find_param,
                                                  _extract_value, _as_str)
        from src.api.dashboard_data import _state
        bool_cfgs = [c for c in _load_configs() if c.get("extract") == "boolean"]
        if not bool_cfgs:
            return []
        rows = (s.query(ConfigSnapshot.categories)
                .order_by(ConfigSnapshot.series_id).limit(_CONCEPT_MISMATCH_SAMPLE).all())
        acc: dict[str, list[int]] = {c["id"]: [0, 0] for c in bool_cfgs}  # [文本数, 命中数]
        for (cats,) in rows:
            cats = cats or {}
            for cfg in bool_cfgs:
                pname, raw = _find_param(cats, cfg["ah_category"], cfg["ah_param"],
                                         cfg.get("match", "contains"))
                if pname is None:
                    continue
                for sid in (raw.keys() if isinstance(raw, dict) else [None]):
                    v = _extract_value(raw, sid) if sid is not None else _extract_value(raw, None)
                    if v is None:
                        continue
                    acc[cfg["id"]][1] += 1
                    if _state(_as_str(v)) == "文本":
                        acc[cfg["id"]][0] += 1
        bad = {cid for cid, (t, n) in acc.items()
               if n and t / n > _CONCEPT_MISMATCH_TEXT_RATIO}
        new = sorted(bad - _CONCEPT_MISMATCH_KNOWN)
        if not new:
            return []
        names = {c["id"]: c["name"] for c in bool_cfgs}
        detail = "、".join(f"{cid}({names.get(cid, '')})" for cid in new)
        return [{
            "code": "concept_field_mismatch",
            "level": "warn",
            "msg": f"概念项字段映射与 extract 期望不符：{detail} —— 命中字段值以文本为主，"
                   "应为该子项配置 extract=sublist_contains + extract_pattern，"
                   "否则看板展示与差价判读会失真（参见 城市NOA 根因）",
        }]
    except Exception:
        return []


def _check_asset_files(data_dir: Path | None = None) -> list[dict]:
    """检查资产文件存在性 + JSON 合法性。
    - 必要资产（concept_configs/weights）：缺失或坏 JSON → 黄牌
    - 可选资产（option_prices）：缺失=空表（正常态）不报，仅坏 JSON → 黄牌"""
    d = data_dir or _data_dir()
    out: list[dict] = []

    def _try_load(p: Path) -> str | None:
        """返回 None=合法；否则错误类型名。"""
        try:
            with open(p, "r", encoding="utf-8") as f:
                json.load(f)
            return None
        except (json.JSONDecodeError, OSError) as e:
            return type(e).__name__

    for fname in _REQUIRED_ASSETS:
        p = d / fname
        if not p.exists():
            out.append({
                "code": "asset_file_missing",
                "level": "warn",
                "msg": f"必要资产文件缺失：data/{fname}（随仓库发行，缺失=安装不完整）",
            })
            continue
        err = _try_load(p)
        if err:
            out.append({
                "code": "asset_file_missing",
                "level": "warn",
                "msg": f"资产文件损坏（非法 JSON）：data/{fname}（{err}）",
            })

    for fname in _OPTIONAL_ASSETS:
        p = d / fname
        if not p.exists():
            continue  # 用户维护文件，缺失=空表（正常态）
        err = _try_load(p)
        if err:
            out.append({
                "code": "asset_file_missing",
                "level": "warn",
                "msg": f"资产文件损坏（非法 JSON）：data/{fname}（{err}）",
            })
    return out


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None
