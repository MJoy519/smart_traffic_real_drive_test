"""
路线选择器（对外接口）
只暴露 select_emotion_route，屏蔽内部计算细节。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime
from modules.traffic_calculator import calculate_best_emotion_route


def select_emotion_route(
    origin_key: str,
    departure_time: datetime | None = None,
) -> int:
    """
    根据实时交通选择最优情感路线。

    Returns:
        int: 1 或 2
    """
    result = calculate_best_emotion_route(origin_key, departure_time)
    return result["recommended_route"]
