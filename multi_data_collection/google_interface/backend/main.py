"""
FastAPI 后端入口
提供情感路线计算、交通数据获取、路线数据查询等接口。

路由均挂载在 /api 前缀下，以便生产模式中同一服务器同时托管
React 静态前端（根路径 /）和 API（/api/...）。
开发模式下 Vite proxy 把 /api/xxx 直接转发至 http://localhost:17843/api/xxx，
无需任何 rewrite。
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import (
    ORIGINS, TEST_MODE, ROUTE_VERSION,
    ROUTE_1_WAYPOINTS_CP_TO_MOS, ROUTE_1_WAYPOINTS_MOS_TO_CP,
    ROUTE_2_WAYPOINTS_CP_TO_MOS, ROUTE_2_WAYPOINTS_MOS_TO_CP,
    ROUTE_1_SEGMENTS, ROUTE_2_SEGMENTS,
)
from modules.traffic_calculator import (
    calculate_best_emotion_route,
    get_traffic_data_for_routes,
)

app = FastAPI(title="Smart Traffic API", version="1.0.0")

# ── CORS：允许前端访问 ────────────────────────────────────────────────
ALLOWED_ORIGINS = [
    os.getenv("FRONTEND_URL", "http://localhost:5173"),
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:17843",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:17843",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ══════════════════════════════════════════════════════════════════════════════
#  API Router（/api 前缀）
# ══════════════════════════════════════════════════════════════════════════════

api = APIRouter(prefix="/api")


# ── 请求模型 ─────────────────────────────────────────────────────────

class EmotionRouteRequest(BaseModel):
    origin_key: str                       # 'cyberport' 或 'ma_on_shan'
    departure_time: Optional[str] = None  # ISO 格式，默认当前时间


# ── 内部工具：解析出发时间 ─────────────────────────────────────────────

def _parse_departure_time(departure_time_str: Optional[str]) -> Optional[datetime]:
    if not departure_time_str:
        return None
    try:
        return datetime.fromisoformat(departure_time_str)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="时间格式错误，请使用 ISO 格式：2026-04-10T08:30:00",
        )


# ── 内部工具：保存交通数据到受试者文件夹 ─────────────────────────────

def _save_traffic_data(data: dict, call_mode: str) -> None:
    """
    将交通数据追加保存到受试者文件夹的 traffic_data.json。

    call_mode: 'get_traffic_data' | 'calculate_emotion_route'
    受试者 ID 与数据根目录由 GUI 启动时通过环境变量注入。
    未配置环境变量时静默跳过（不影响接口响应）。
    """
    participant_id = os.environ.get("PARTICIPANT_ID", "").strip()
    data_root      = os.environ.get("DATA_ROOT", "").strip()
    if not participant_id or not data_root:
        return

    subj_dir = Path(data_root) / "subjects" / participant_id
    subj_dir.mkdir(parents=True, exist_ok=True)

    traffic_file = subj_dir / "traffic_data.json"
    records: list = []
    if traffic_file.exists():
        try:
            with open(traffic_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            records = existing if isinstance(existing, list) else [existing]
        except Exception:
            records = []

    records.append({
        "call_mode":    call_mode,
        "saved_at":     datetime.now().isoformat(),
        **data,
    })

    with open(traffic_file, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


# ── 路由 ─────────────────────────────────────────────────────────────

@api.get("/")
def root():
    return {"message": "Smart Traffic API is running", "version": "1.0.0"}


@api.post("/get-traffic-data")
async def get_traffic_data(request: EmotionRouteRequest):
    """
    获取两条情感路线的实时交通数据（测试模式专用）。
    调用真实 Google Directions API，返回逐段 BTI 及原始 API 字段。
    结果同步保存到受试者文件夹（traffic_data.json）。
    """
    if request.origin_key not in ORIGINS:
        raise HTTPException(
            status_code=400,
            detail=f"无效起点: {request.origin_key}，可选: cyberport（慈正村）, ma_on_shan（中央广场）",
        )

    departure_time = _parse_departure_time(request.departure_time)

    result = get_traffic_data_for_routes(
        origin_key=request.origin_key,
        departure_time=departure_time,
    )

    _save_traffic_data(result, call_mode="get_traffic_data")
    return result


@api.post("/calculate-emotion-route")
async def calculate_emotion_route(request: EmotionRouteRequest):
    """
    计算最优情感路线（正式模式）。
    获取实时交通数据 + 计算综合得分，返回推荐路线编号及详细分析数据。
    交通数据同步保存到受试者文件夹（traffic_data.json）。
    """
    if request.origin_key not in ORIGINS:
        raise HTTPException(
            status_code=400,
            detail=f"无效起点: {request.origin_key}，可选: cyberport（慈正村）, ma_on_shan（中央广场）",
        )

    departure_time = _parse_departure_time(request.departure_time)

    result = calculate_best_emotion_route(
        origin_key=request.origin_key,
        departure_time=departure_time,
    )

    # 保存交通数据（traffic_data 字段中含完整原始和计算数据）
    if result.get("traffic_data"):
        _save_traffic_data(
            {**result["traffic_data"], "recommendation": {
                "recommended_route": result["recommended_route"],
                "reason":            result["reason"],
                "route_1_score":     result["route_1_analysis"]["score"],
                "route_2_score":     result["route_2_analysis"]["score"],
            }},
            call_mode="calculate_emotion_route",
        )

    return result


@api.get("/route-data/{route_id}")
async def get_route_data(route_id: int):
    """获取情感路线的固定经纬度及分段数据（动态从 config 生成，随 ROUTE_VERSION 切换）。"""
    if route_id not in (1, 2):
        raise HTTPException(status_code=404, detail="路线 ID 不存在，可选 1 或 2")

    if route_id == 1:
        wp_fwd = ROUTE_1_WAYPOINTS_CP_TO_MOS
        wp_rev = ROUTE_1_WAYPOINTS_MOS_TO_CP
        segments = ROUTE_1_SEGMENTS
        color = "#10B981"
    else:
        wp_fwd = ROUTE_2_WAYPOINTS_CP_TO_MOS
        wp_rev = ROUTE_2_WAYPOINTS_MOS_TO_CP
        segments = ROUTE_2_SEGMENTS
        color = "#F59E0B"

    origin_info = ORIGINS.get("cyberport", {})
    dest_info   = ORIGINS.get("ma_on_shan", {})

    return {
        "id":    route_id,
        "name":  f"情感路线{route_id}",
        "color": color,
        "route_version": ROUTE_VERSION,
        "waypoints_cyberport_to_mos": wp_fwd,
        "waypoints_mos_to_cyberport": wp_rev,
        "segments": segments,
        "origin_name": origin_info.get("name", ""),
        "dest_name":   dest_info.get("name", ""),
    }


@api.get("/origins")
async def get_origins():
    """获取起终点信息。"""
    return ORIGINS


@api.get("/config/test-mode")
async def get_test_mode():
    """获取当前测试模式配置及路线版本。"""
    return {"test_mode": TEST_MODE, "route_version": ROUTE_VERSION}


# ── 路线选择保存 ──────────────────────────────────────────────────────

_ORIGIN_NAME_MAP = {
    key: info["name"] for key, info in ORIGINS.items()
}

_ROUTE_LABEL_MAP = {
    "fast":     "最快路线",
    "emotion1": "情感路线1（北线）",
    "emotion2": "情感路线2（南线）",
}


class RouteSelectionData(BaseModel):
    origin: str
    route_type: str                           # 'fast' | 'emotion'
    selected_route: str                       # 'fast' | 'emotion1' | 'emotion2'
    best_emotion_route: Optional[int] = None  # 1 或 2，仅情感路线有效


@api.post("/save-route")
async def save_route_selection(data: RouteSelectionData):
    """
    保存路线选择记录到受试者文件夹（route_selection.json，列表追加）。
    受试者 ID 与数据根目录由 GUI 启动时通过环境变量注入。
    """
    participant_id = os.environ.get("PARTICIPANT_ID", "").strip()
    data_root      = os.environ.get("DATA_ROOT", "").strip()

    if not participant_id or not data_root:
        raise HTTPException(
            status_code=503,
            detail="后端未配置受试者信息，请关闭浏览器后重新点击「路线选择」",
        )

    subj_dir = Path(data_root) / "subjects" / participant_id
    subj_dir.mkdir(parents=True, exist_ok=True)

    route_file = subj_dir / "route_selection.json"
    records: list = []
    if route_file.exists():
        try:
            with open(route_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            records = existing if isinstance(existing, list) else [existing]
        except Exception:
            records = []

    records.append({
        "origin":               data.origin,
        "origin_name":          _ORIGIN_NAME_MAP.get(data.origin, data.origin),
        "route_type":           data.route_type,
        "selected_route":       data.selected_route,
        "selected_route_label": _ROUTE_LABEL_MAP.get(data.selected_route, data.selected_route),
        "best_emotion_route":   data.best_emotion_route,
        "timestamp":            datetime.now().isoformat(),
    })

    with open(route_file, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    return {
        "status":        "ok",
        "participant_id": participant_id,
        "records_count": len(records),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  将 API Router 注册到 app
# ══════════════════════════════════════════════════════════════════════════════

app.include_router(api)

# ══════════════════════════════════════════════════════════════════════════════
#  生产模式：托管 React 静态文件
#  挂载须在所有 API 路由注册之后
# ══════════════════════════════════════════════════════════════════════════════

_dist_dir = os.environ.get("FRONTEND_DIST_DIR", "").strip()
if _dist_dir and os.path.isdir(_dist_dir):
    try:
        # 单独注册根路径，返回 index.html 并附加 no-cache 头，
        # 防止浏览器缓存旧版本；JS/CSS 已有内容哈希名，无需额外处理。
        _index_html = os.path.join(_dist_dir, "index.html")

        @app.get("/", include_in_schema=False)
        async def _serve_index(request: Request):
            return FileResponse(
                _index_html,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma":        "no-cache",
                    "Expires":       "0",
                },
            )

        app.mount("/", StaticFiles(directory=_dist_dir, html=True), name="frontend")
    except Exception as _e:
        print(f"[backend] 静态文件挂载失败（API-only 模式）: {_e}")
