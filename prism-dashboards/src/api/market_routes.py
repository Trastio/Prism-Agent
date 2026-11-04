"""市场看板路由（specs/market-dashboard v6）：销量/价格监测（CAM 双表）。

供最终用户在浏览器使用：
- /dashboard/market          页面骨架（车系/月份下拉 + 5 模块容器 + 导入按钮；
                             完整模板与交互 specs Task 7，本 Task 先渲染骨架）
- /dashboard/market/api/*    JSON 查询端点（v7 单表化：只读 sales_trim）

纪律：查询只读；唯一写端点是 POST /import（multipart 上传 CAM Excel →
scripts/import_sales_excel.py 解析落库），沿用 config 看板"collector 式手动写"边界。
不触碰 agent-loop / chat_routes 的编排逻辑（红线）。
"""
from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from src.api import market_data

router = APIRouter(prefix="/dash/market")
_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "web" / "templates"))

_IMPORTER = None

# P3-28: 上传文件大小上限（CAM 主表 19.7 万行约十几 MB，50MB 足够容错）
_MAX_IMPORT_BYTES = 50 * 1024 * 1024

# dashboard-v10 Task 1.2：写端点限流（与 dashboard_routes 同模式，独立计数器）。
# {ip: [window_start, count]}，窗口 60s 内超过 10 次 → 429。
_WRITE_RATE: dict[str, list] = {}
_RATE_LIMIT = 10
_RATE_WINDOW = 60.0


def _rate_limited(ip: str | None) -> bool:
    """滑动窗口计数（每 IP 每分钟 _RATE_LIMIT 次）。"""
    now = time.monotonic()
    ip = ip or "unknown"
    for k in [k for k, v in _WRITE_RATE.items() if now - v[0] >= _RATE_WINDOW]:
        _WRITE_RATE.pop(k, None)
    rec = _WRITE_RATE.get(ip)
    if rec is None or now - rec[0] >= _RATE_WINDOW:
        _WRITE_RATE[ip] = [now, 1]
        return False
    rec[1] += 1
    return rec[1] > _RATE_LIMIT

# I-3: 导入进度查询。内存 dict 存最近一次导入状态（进程级单例）。
# import_workbook 是同步全量解析（无分阶段回调），故进度只记开始/完成/失败三态
# + 时间戳 + 文件名（前端可轮询判断是否在进行中）。
_import_status: dict = {}


def _load_importer():
    """scripts/ 非包，用 importlib 挂载 import_sales_excel（tests 同款模式）。"""
    global _IMPORTER
    if _IMPORTER is None:
        path = Path(__file__).resolve().parent.parent.parent / "scripts" / "import_sales_excel.py"
        spec = importlib.util.spec_from_file_location("import_sales_excel", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _IMPORTER = mod
    return _IMPORTER


@router.get("")
def market_page(request: Request, q: str = ""):
    """市场看板页（骨架版，specs Task 7 出完整模板）。
    P1-11: 空库（months 与 series_list 均空）时模板显示导入引导，不全空白。
    P1-12: 传数据时效（覆盖月份范围 + 最后导入月份代理）到模板。
    D4（2026-11-02）：支持 ?q=车系名 预选（对话侧车系联动）。"""
    months = market_data.market_months()
    series_list = market_data.market_series_list()
    # 默认月份取最新"有零售数"的月（月中快照零售未发布，直接选最新月会全 0）
    default_month = market_data.latest_retail_month() or (months[-1] if months else "")
    freshness = market_data.market_data_freshness()
    return _templates.TemplateResponse(request, "dash_market.html", {
        "request": request,
        "months": months,
        "default_month": default_month,
        "series_list": series_list,
        "freshness": freshness,
        "preselect": (q or "").strip(),
    })


@router.get("/api/series-list")
def api_series_list():
    return {"ok": True, "series": market_data.market_series_list()}


@router.get("/api/series-all")
def api_series_all():
    """竞品对比候选（2026-10 改造）：全库车系（不限最新月）。

    与 /api/series-list（最新有零售月车系，供顶部车系下拉）分开，
    避免顶部下拉口径被动变化；仅竞品对比用全库候选。
    """
    return {"ok": True, "series": market_data.market_series_all()}


@router.get("/api/series-filter")
def api_series_filter(kw: str = "", brand: str = "", energy: str = "",
                      level: str = "", price_min: str = "", price_max: str = "",
                      wheelbase_min: str = "", wheelbase_max: str = "",
                      limit: str = "50"):
    """跨车系筛选（人工题集转金标 Block 0）：价格/级别/能耗/轴距服务端过滤。

    供 agent 的 search_cars 筛选路径调用（人话条件 → 结构化过滤），只读。
    参数校验 fail-closed：energy 只收端点写死枚举（BEV/PHEV/NEV/ICE），非法或
    数值参数非数值 → 400 带提示文案；limit 上限 50（超出按 50 截断），命中超
    limit 截断附 _truncated 提示（线B模式）。与 series-list/series-all 互不影响。
    """
    energy = energy.strip()
    if energy and energy not in market_data.ENERGY_ENUMS:
        return JSONResponse(
            {"ok": False,
             "error": f"energy 非法枚举：{energy}（可选：BEV/PHEV/NEV/ICE）"},
            status_code=400)
    nums: dict[str, float | None] = {}
    for key, raw in (("price_min", price_min), ("price_max", price_max),
                     ("wheelbase_min", wheelbase_min),
                     ("wheelbase_max", wheelbase_max)):
        v = str(raw or "").strip()
        if not v:
            nums[key] = None
            continue
        try:
            nums[key] = float(v)
        except ValueError:
            return JSONResponse(
                {"ok": False, "error": f"{key} 非数值：{v}"}, status_code=400)
    lim_raw = str(limit or "").strip() or "50"
    try:
        lim = int(float(lim_raw))
    except ValueError:
        return JSONResponse(
            {"ok": False, "error": f"limit 非数值：{lim_raw}"}, status_code=400)
    lim = max(1, min(lim, 50))
    payload = market_data.market_series_filter(
        kw=kw.strip(), brand=brand.strip() or None,
        energy=energy or None, level=level.strip() or None,
        price_min=nums["price_min"], price_max=nums["price_max"],
        wheelbase_min=nums["wheelbase_min"], wheelbase_max=nums["wheelbase_max"],
        limit=lim)
    if payload["total_matched"] > len(payload["rows"]):
        payload["_truncated"] = {
            "kept_rows": len(payload["rows"]),
            "total_matched": payload["total_matched"],
            "hint": f"命中超 {lim} 条仅保留前 {lim}；加严筛选条件可缩小范围"}
    return {"ok": True, **payload}


@router.get("/api/trend")
def api_trend(series: str = ""):
    if not series.strip():
        return JSONResponse({"ok": False, "error": "缺少 series 参数"}, status_code=400)
    return {"ok": True, **market_data.series_trend(series.strip())}


@router.get("/api/retail")
def api_retail(series: str = ""):
    if not series.strip():
        return JSONResponse({"ok": False, "error": "缺少 series 参数"}, status_code=400)
    return {"ok": True, **market_data.retail_trend(series.strip())}


@router.get("/api/compare")
def api_compare(series: str = "", metric: str = "tp"):
    names = [x.strip() for x in series.split(",") if x.strip()]
    if not (2 <= len(names) <= 4):
        return JSONResponse({"ok": False, "error": "compare 需要 2-4 个车系（逗号分隔）"},
                            status_code=400)
    return {"ok": True, **market_data.peer_compare(names, metric=metric)}


@router.get("/api/scatter")
def api_scatter(month: str = ""):
    if not month.strip():
        return JSONResponse({"ok": False, "error": "缺少 month 参数"}, status_code=400)
    return {"ok": True, "points": market_data.price_volume_scatter(month.strip())}


@router.get("/api/level-summary")
def api_level_summary(month: str = ""):
    if not month.strip():
        return JSONResponse({"ok": False, "error": "缺少 month 参数"}, status_code=400)
    return {"ok": True, **market_data.level_summary(month.strip())}


@router.get("/api/months")
def api_months():
    return {"ok": True, "months": market_data.market_months()}


@router.get("/api/trim-structure")
def api_trim_structure(series: str = "", month: str = ""):
    """版型结构（v11 Task 1.3）：Top1/Top3 mix + hi_lo 分布 + 优惠有效性。"""
    if not series.strip():
        return JSONResponse({"ok": False, "error": "缺少 series 参数"}, status_code=400)
    m = month.strip() or None
    return {"ok": True, **market_data.trim_structure(series.strip(), month=m)}


@router.get("/api/trim-concentration-trend")
def api_concentration_trend(series: str = "", months: int = 12):
    """版型集中度时间序列（dashboards-tri-polish Q8）：多月 top1/top3 集中度趋势。"""
    if not series.strip():
        return JSONResponse({"ok": False, "error": "缺少 series 参数"}, status_code=400)
    return {"ok": True, **market_data.trim_concentration_trend(series.strip(), months)}


@router.get("/api/insight")
def api_insight(series: str = ""):
    """结论卡（v11 Task 1.4）：数据规则生成一句话洞察。"""
    if not series.strip():
        return JSONResponse({"ok": False, "error": "缺少 series 参数"}, status_code=400)
    return {"ok": True, **market_data.series_insight(series.strip())}


@router.post("/import")
async def api_import(request: Request, file: UploadFile = File(...)):
    """上传 CAM Excel → 解析落库（specs/market-dashboard v6 唯一写端点）。
    只接受 .xlsx；解析/导入异常如实返回，不吞错。

    P1-14: openpyxl 同步解析（19.7 万行数十秒）走 run_in_threadpool，不阻塞事件循环。
    P3-28: 超过 _MAX_IMPORT_BYTES 返回 413。
    I-3: 开始/完成/失败三态写入 _import_status（前端轮询 /import/status）。
    dashboard-v10 Task 1.2：写端点限流（防脚本循环刷导入）。
    """
    # 限流在最前：无论后续文件校验/解析结果，都计一次请求
    if _rate_limited(request.client.host if request.client else None):
        return JSONResponse({"ok": False, "error": "请求过于频繁，请稍后再试"},
                            status_code=429)
    name = os.path.basename(file.filename or "")
    if not name.lower().endswith(".xlsx"):
        return JSONResponse({"ok": False, "error": "只支持 .xlsx 文件"}, status_code=400)
    # P3-28: 文件大小校验（file.size 由 multipart 解析器填充；
    # 回退 seek 末尾兜底，防 size 为 None 的边角路径）
    size = file.size
    if size is None:
        try:
            cur = file.file.tell()
            file.file.seek(0, 2)
            size = file.file.tell()
            file.file.seek(cur)
        except Exception:
            size = 0
    if size > _MAX_IMPORT_BYTES:
        return JSONResponse(
            {"ok": False,
             "error": f"文件过大（{size} 字节，上限 {_MAX_IMPORT_BYTES // 1024 // 1024}MB）"},
            status_code=413)
    importer = _load_importer()
    # I-3: 记录导入开始
    _import_status.clear()
    _import_status.update({
        "status": "running", "filename": name,
        "started_at": time.time(), "finished_at": None,
        "error": None, "stats": None})
    # SpooledTemporaryFile 是 seekable 二进制句柄，openpyxl 可直接读，不落盘
    try:
        stats = await run_in_threadpool(importer.import_workbook, file.file)
    except ValueError as e:  # 缺核心列等结构错误 → 400
        _import_status.update({"status": "failed", "finished_at": time.time(),
                               "error": str(e)})
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:
        _import_status.update({"status": "failed", "finished_at": time.time(),
                               "error": f"导入失败：{e}"})
        return JSONResponse({"ok": False, "error": f"导入失败：{e}"}, status_code=500)
    finally:
        await file.close()
    _import_status.update({"status": "done", "finished_at": time.time(),
                           "stats": stats})
    return {"ok": True, "filename": name, "stats": stats}


@router.get("/import/status")
def api_import_status():
    """I-3: 导入进度查询。返回最近一次导入状态（进程级内存，重启清空）。
    {"status": "running"|"done"|"failed"|None, "filename", "started_at",
     "finished_at", "error", "stats"}。无导入记录 → {"status": None}。"""
    return {"ok": True, **_import_status} if _import_status else {"ok": True, "status": None}
