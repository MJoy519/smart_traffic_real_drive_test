"""
FastAPI 后端入口
提供情感路线计算、路线数据查询等接口。

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

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import ORIGINS, TEST_MODE, TEST_MODE_FORCED_ROUTE
from modules.traffic_calculator import calculate_best_emotion_route

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
#  生产模式与开发模式均通过此前缀访问，Vite proxy 无需 rewrite。
# ══════════════════════════════════════════════════════════════════════════════

api = APIRouter(prefix="/api")


# ── 请求模型 ─────────────────────────────────────────────────────────

class EmotionRouteRequest(BaseModel):
    origin_key: str                       # 'cyberport' 或 'ma_on_shan'
    departure_time: Optional[str] = None  # ISO 格式，默认当前时间


# ── 路由 ─────────────────────────────────────────────────────────────

@api.get("/")
def root():
    return {"message": "Smart Traffic API is running", "version": "1.0.0"}


@api.post("/calculate-emotion-route")
async def calculate_emotion_route(request: EmotionRouteRequest):
    """计算最优情感路线，返回推荐路线编号（1 或 2）及详细分析数据。"""
    if request.origin_key not in ORIGINS:
        raise HTTPException(
            status_code=400,
            detail=f"无效起点: {request.origin_key}，可选: cyberport, ma_on_shan",
        )

    departure_time: Optional[datetime] = None
    if request.departure_time:
        try:
            departure_time = datetime.fromisoformat(request.departure_time)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="时间格式错误，请使用 ISO 格式：2026-04-10T08:30:00",
            )

    result = calculate_best_emotion_route(
        origin_key=request.origin_key,
        departure_time=departure_time,
    )
    return result


@api.get("/route-data/{route_id}")
async def get_route_data(route_id: int):
    """获取情感路线的固定经纬度及分段数据。"""
    if route_id not in (1, 2):
        raise HTTPException(status_code=404, detail="路线 ID 不存在，可选 1 或 2")

    file_path = os.path.join(os.path.dirname(__file__), "routes", f"emotion_route_{route_id}.json")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="路线数据文件不存在")

    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


@api.get("/origins")
async def get_origins():
    """获取起终点信息。"""
    return ORIGINS


@api.get("/config/test-mode")
async def get_test_mode():
    """获取当前测试模式配置。"""
    return {
        "test_mode":    TEST_MODE,
        "forced_route": TEST_MODE_FORCED_ROUTE if TEST_MODE else None,
    }


# ── 路线选择保存 ──────────────────────────────────────────────────────

_ORIGIN_NAME_MAP = {
    "cyberport":  "数码港",
    "ma_on_shan": "马鞍山",
}

_ROUTE_LABEL_MAP = {
    "fast":     "最快路线",
    "emotion1": "情感路线1（北线）",
    "emotion2": "情感路线2（南线）",
}


class RouteSelectionData(BaseModel):
    origin: str                          # 'cyberport' | 'ma_on_shan'
    route_type: str                      # 'fast' | 'emotion'
    selected_route: str                  # 'fast' | 'emotion1' | 'emotion2'
    best_emotion_route: Optional[int] = None  # 1 或 2，仅体验路线有效


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
#  生产模式：托管 React 静态文件（FRONTEND_DIST_DIR 由 GUI 子进程传入）
#  挂载须在所有 API 路由注册之后，否则 / 会被静态文件接管而导致 /api 失效
# ══════════════════════════════════════════════════════════════════════════════

_dist_dir = os.environ.get("FRONTEND_DIST_DIR", "").strip()
if _dist_dir and os.path.isdir(_dist_dir):
    try:
        app.mount("/", StaticFiles(directory=_dist_dir, html=True), name="frontend")
    except Exception as _e:
        print(f"[backend] 静态文件挂载失败（API-only 模式）: {_e}")
