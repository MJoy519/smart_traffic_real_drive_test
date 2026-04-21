"""
核心模块：交通数据获取 + 最优情感路线计算
==========================================

提供两个主要函数：

  get_traffic_data_for_routes(origin_key, departure_time)
      获取两条情感路线的实时交通数据（测试模式 / 正式模式均可调用）。
      返回原始 API 字段 + 逐段 BTI 计算结果。

  calculate_best_emotion_route(origin_key, departure_time)
      在 get_traffic_data_for_routes 基础上计算路线综合得分，返回推荐路线。
      仅在正式模式（TEST_MODE=False）下使用。

测试模式说明：
  TEST_MODE=True  → "获取交通数据"按钮，调用真实 API，不推荐路线
  TEST_MODE=False → "计算最优情感路线"按钮，调用 API 并给出推荐
"""
import importlib.util
import os
import random
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from datetime import datetime
from config import TEST_MODE, ROUTE_VERSION, ORIGINS
from modules.segment_analyzer import fetch_route_traffic

# 读取根配置中的 ROUTE_CONTROL（避免与同名 backend/config.py 冲突）
_root_cfg_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "config.py")
)
_root_cfg_spec = importlib.util.spec_from_file_location("root_config", _root_cfg_path)
_root_cfg_mod  = importlib.util.module_from_spec(_root_cfg_spec)
_root_cfg_spec.loader.exec_module(_root_cfg_mod)
ROUTE_CONTROL: int = getattr(_root_cfg_mod, "ROUTE_CONTROL", 1)


def get_traffic_data_for_routes(
    origin_key: str,
    departure_time: datetime | None = None,
) -> dict:
    """
    获取两条情感路线的实时交通数据（两次 Directions API 调用）。

    Args:
        origin_key:     'cyberport' 或 'ma_on_shan'
        departure_time: 出发时间，默认为当前时间

    Returns:
        {
          "timestamp":   str,          # 出发时间 ISO
          "origin_key":  str,
          "test_mode":   bool,
          "route_1": {
            "raw_api_response": dict,
            "computed": {
              "departure_time_iso": str,
              "segments": [...],
              "total_distance_m": int,
              "total_free_flow_duration_s": int,
              "total_actual_duration_s": int,
              "total_congestion_delay_s": int,
              "total_bti": float,
            }
          },
          "route_2": { ... }           # 同 route_1 结构
        }
    """
    if departure_time is None:
        departure_time = datetime.now()

    route_1 = fetch_route_traffic(origin_key, 1, departure_time)
    route_2 = fetch_route_traffic(origin_key, 2, departure_time)

    return {
        "timestamp":  departure_time.isoformat(),
        "origin_key": origin_key,
        "test_mode":  TEST_MODE,
        "route_1":    route_1,
        "route_2":    route_2,
    }


def calculate_best_emotion_route(
    origin_key: str,
    departure_time: datetime | None = None,
) -> dict:
    """
    获取交通数据并计算最优情感路线得分，返回推荐路线编号。

    仅在正式模式（TEST_MODE=False）下调用此函数；
    测试模式请直接调用 get_traffic_data_for_routes。

    Returns:
        {
          "recommended_route": 1 | 2,
          "reason": str,
          "route_1_analysis": {"total_bti": float, "score": float, "segments": [...]},
          "route_2_analysis": {"total_bti": float, "score": float, "segments": [...]},
          "traffic_data": dict,   # get_traffic_data_for_routes 的完整返回
          "test_mode": False,
          "departure_time": str,
        }
    """
    if departure_time is None:
        departure_time = datetime.now()

    traffic = get_traffic_data_for_routes(origin_key, departure_time)

    computed_1 = traffic["route_1"]["computed"]
    computed_2 = traffic["route_2"]["computed"]

    recommended = _control_route_score()

    origin_name  = ORIGINS.get("cyberport", {}).get("name", "起点")
    dest_name    = ORIGINS.get("ma_on_shan", {}).get("name", "终点")
    route_prefix = f"{origin_name} ↔ {dest_name}"
    reason = f"【{route_prefix}】由 ROUTE_CONTROL 固定指定，推荐路线{recommended}"

    return {
        "recommended_route": recommended,
        "reason":            reason,
        "route_1_analysis":  {
            "total_bti": computed_1["total_bti"],
            "score":     None,
            "segments":  computed_1["segments"],
        },
        "route_2_analysis":  {
            "total_bti": computed_2["total_bti"],
            "score":     None,
            "segments":  computed_2["segments"],
        },
        "traffic_data":  traffic,
        "test_mode":     False,
        "departure_time": departure_time.isoformat(),
    }


def _control_route_score() -> int:
    """
    正式模式下的路线选择函数。
    以二分之一概率随机推荐路线1或路线2。
    """
    return random.choice((1, 2))

# def _control_route_score() -> int:
#     """
#     正式模式下的路线选择函数。
#     返回值固定由根配置 multi_data_collection/config.py 的 ROUTE_CONTROL 决定：
#       ROUTE_CONTROL = 1 → 推荐路线1
#       ROUTE_CONTROL = 2 → 推荐路线2
#     """
#     return 1 if ROUTE_CONTROL != 2 else 2

def _compute_route_score(computed: dict) -> float:
    """
    路线综合得分（占位框架，待情感权重公式确定后替换）。

    当前实现：距离加权 BTI 均值。
    公式：score = Σ(BTI_i × distance_i) / Σ(distance_i)
    得分越低越好（0 = 完全畅通）。

    TODO: 确定情感数据权重函数后，在此替换权重计算逻辑。
          示例扩展：score = Σ(BTI_i × distance_i × emotion_weight_i) / Σ(distance_i)

    Args:
        computed: fetch_route_traffic 返回的 "computed" 字段

    Returns:
        float: 综合得分（越低越好）
    """
    segments       = computed.get("segments", [])
    total_distance = computed.get("total_distance_m", 0)

    if not segments or total_distance == 0:
        return computed.get("total_bti", 0.0)

    weighted_bti = sum(
        seg["bti"] * seg["distance_m"]
        for seg in segments
    ) / total_distance

    return round(weighted_bti, 4)
