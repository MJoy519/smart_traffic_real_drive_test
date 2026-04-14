"""
分段拥堵分析模块
调用 Google Distance Matrix API，对路线各分段计算拥堵延误和拥堵指数。

拥堵延误 = duration_in_traffic（预测实际时间）- duration（自由流时间）
拥堵指数 = 拥堵延误 / duration（越低越好）

API 调用策略：每条路线发起 1 次批量请求（以对角线元素取各段结果）。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import googlemaps
from datetime import datetime
from config import GOOGLE_MAPS_API_KEY


def analyze_route_segments(segments: list, departure_time: datetime) -> dict:
    """
    对路线所有分段进行拥堵分析，1 次 API 调用。

    Args:
        segments: 来自 config.py 的分段列表
        departure_time: 出发时间（datetime）

    Returns:
        {
          "departure_time": str,
          "segments": [
            {
              "id": int,
              "name": str,
              "distance_km": float,
              "free_flow_duration_s": int,
              "actual_duration_s": int,
              "congestion_delay_s": int,
              "congestion_index": float,
              "estimated_arrival": str   # HH:MM:SS
            }, ...
          ],
          "total_free_flow_duration_s": int,
          "total_congestion_delay_s": int,
          "total_congestion_index": float
        }
    """
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

    origins      = [(seg["start"]["lat"], seg["start"]["lng"]) for seg in segments]
    destinations = [(seg["end"]["lat"],   seg["end"]["lng"])   for seg in segments]

    result = gmaps.distance_matrix(
        origins=origins,
        destinations=destinations,
        mode="driving",
        departure_time=departure_time,
        traffic_model="best_guess",
        units="metric",
    )

    analyzed_segments = []
    cumulative_free_flow_s = 0
    total_congestion_delay = 0
    total_free_flow_duration = 0

    for i, segment in enumerate(segments):
        element = result["rows"][i]["elements"][i]  # 对角线：第i段origin→第i段destination

        if element["status"] != "OK":
            analyzed_segments.append({
                "id":     segment["id"],
                "name":   segment["name"],
                "status": "error",
                "error":  element["status"],
            })
            continue

        free_flow_s = element["duration"]["value"]
        actual_s    = element.get("duration_in_traffic", element["duration"])["value"]
        delay_s     = max(0, actual_s - free_flow_s)
        c_index     = delay_s / free_flow_s if free_flow_s > 0 else 0.0

        # 估算到达该段起点的时刻（基于累计自由流时间，简化模型）
        arrival_ts  = departure_time.timestamp() + cumulative_free_flow_s
        arrival_str = datetime.fromtimestamp(arrival_ts).strftime("%H:%M:%S")

        analyzed_segments.append({
            "id":                    segment["id"],
            "name":                  segment["name"],
            "road":                  segment.get("road", ""),
            "distance_km":           segment["distance_km"],
            "free_flow_duration_s":  free_flow_s,
            "actual_duration_s":     actual_s,
            "congestion_delay_s":    delay_s,
            "congestion_index":      round(c_index, 4),
            "estimated_arrival":     arrival_str,
            "estimated_arrival_ts":  arrival_ts,
        })

        cumulative_free_flow_s += free_flow_s
        total_congestion_delay += delay_s
        total_free_flow_duration += free_flow_s

    total_c_index = (
        total_congestion_delay / total_free_flow_duration
        if total_free_flow_duration > 0 else 0.0
    )

    return {
        "departure_time":            departure_time.isoformat(),
        "segments":                  analyzed_segments,
        "total_free_flow_duration_s": total_free_flow_duration,
        "total_congestion_delay_s":  total_congestion_delay,
        "total_congestion_index":    round(total_c_index, 4),
    }
