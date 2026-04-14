"""
核心模块：计算最优情感路线
============================
输入：起点标识 + 出发时间
输出：1 或 2（代表推荐的情感路线编号）

测试模式（TEST_MODE=True）：跳过 API，直接返回 TEST_MODE_FORCED_ROUTE。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime
from config import (
    TEST_MODE,
    TEST_MODE_FORCED_ROUTE,
    ROUTE_1_SEGMENTS,
    ROUTE_2_SEGMENTS,
)
from modules.segment_analyzer import analyze_route_segments


def calculate_best_emotion_route(
    origin_key: str,
    departure_time: datetime | None = None,
) -> dict:
    """
    分析两条情感路线的实时拥堵，返回推荐路线编号。

    Args:
        origin_key:     'cyberport' 或 'ma_on_shan'
        departure_time: 出发时间，默认为当前时间

    Returns:
        {
          "recommended_route": 1 | 2,
          "reason": str,
          "route_1_analysis": dict | None,
          "route_2_analysis": dict | None,
          "test_mode": bool
        }
    """
    if departure_time is None:
        departure_time = datetime.now()

    # ── 测试模式：不调用 API ──────────────────────────────────────────
    if TEST_MODE:
        return {
            "recommended_route": TEST_MODE_FORCED_ROUTE,
            "reason":            f"[测试模式] 强制选择路线 {TEST_MODE_FORCED_ROUTE}",
            "route_1_analysis":  None,
            "route_2_analysis":  None,
            "test_mode":         True,
            "departure_time":    departure_time.isoformat(),
        }

    # ── 正式模式：调用 Google API ────────────────────────────────────
    if origin_key == "cyberport":
        segments_1 = ROUTE_1_SEGMENTS
        segments_2 = ROUTE_2_SEGMENTS
    else:
        # 马鞍山出发：反转分段顺序并交换 start/end
        segments_1 = [
            {**seg, "start": seg["end"], "end": seg["start"]}
            for seg in reversed(ROUTE_1_SEGMENTS)
        ]
        segments_2 = [
            {**seg, "start": seg["end"], "end": seg["start"]}
            for seg in reversed(ROUTE_2_SEGMENTS)
        ]

    analysis_1 = analyze_route_segments(segments_1, departure_time)
    analysis_2 = analyze_route_segments(segments_2, departure_time)

    idx_1 = analysis_1["total_congestion_index"]
    idx_2 = analysis_2["total_congestion_index"]

    if idx_1 <= idx_2:
        recommended = 1
        reason = (
            f"路线1（北线）拥堵指数 {idx_1:.4f} ≤ 路线2（南线）{idx_2:.4f}，推荐北线"
        )
    else:
        recommended = 2
        reason = (
            f"路线2（南线）拥堵指数 {idx_2:.4f} < 路线1（北线）{idx_1:.4f}，推荐南线"
        )

    return {
        "recommended_route": recommended,
        "reason":            reason,
        "route_1_analysis":  analysis_1,
        "route_2_analysis":  analysis_2,
        "test_mode":         False,
        "departure_time":    departure_time.isoformat(),
    }
