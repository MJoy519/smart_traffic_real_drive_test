"""
分段拥堵分析模块（Directions API 版）
=====================================
使用 Google Directions API（含 stopover 途径点），一次调用获取整条情感路线
按检查点分段的交通数据。

分段结构（以数码港→马鞍山为例）：
  起点 → 途径点1 → 途径点2 → 途径点3 → 终点   共 4 个 leg

关键字段说明：
  distance_m              分段距离（米），来自 leg.distance.value
  free_flow_duration_s    自由流用时（秒），来自 leg.duration.value
  actual_duration_s       含实时交通预计用时（秒），来自 leg.duration_in_traffic.value
  congestion_delay_s      拥堵延误 = actual - free_flow（≥0）
  bti                     Buffer Time Index = congestion_delay / free_flow
                          （0 = 完全畅通，0.5 = 比畅通多花 50%）
  estimated_arrival_iso   预计到达该段终点的时刻（ISO 格式）

原始 API 字段与计算结果均由调用方负责保存到受试者文件夹。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import googlemaps
from datetime import datetime
from config import GOOGLE_MAPS_API_KEY, ORIGINS, TRAFFIC_WAYPOINTS


def fetch_route_traffic(
    origin_key: str,
    route_id: int,
    departure_time: datetime,
) -> dict:
    """
    调用 Directions API 获取一条情感路线的逐段交通数据。

    Args:
        origin_key:     'cyberport' 或 'ma_on_shan'
        route_id:       1 或 2
        departure_time: 出发时间（datetime）

    Returns:
        {
          "raw_api_response": {          # Directions API 原始字段（legs）
            "summary": str,
            "warnings": list,
            "waypoint_order": list,
            "legs": [
              {
                "start_address": str,
                "end_address": str,
                "start_location": {"lat": float, "lng": float},
                "end_location":   {"lat": float, "lng": float},
                "distance":              {"text": str, "value": int},
                "duration":              {"text": str, "value": int},
                "duration_in_traffic":   {"text": str, "value": int},
              }, ...
            ]
          },
          "computed": {
            "departure_time_iso": str,
            "segments": [
              {
                "leg_index":             int,
                "segment_name":          str,   # "起点标签 → 终点标签"
                "start_label":           str,
                "end_label":             str,
                "start_address":         str,
                "end_address":           str,
                "start_location":        {"lat": float, "lng": float},
                "end_location":          {"lat": float, "lng": float},
                "distance_m":            int,
                "free_flow_duration_s":  int,
                "actual_duration_s":     int,
                "congestion_delay_s":    int,
                "bti":                   float,
                "estimated_arrival_iso": str,
              }, ...
            ],
            "total_distance_m":           int,
            "total_free_flow_duration_s": int,
            "total_actual_duration_s":    int,
            "total_congestion_delay_s":   int,
            "total_bti":                  float,
          }
        }

    Raises:
        RuntimeError: Directions API 返回空结果或状态异常
    """
    gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)

    dest_key      = "ma_on_shan" if origin_key == "cyberport" else "cyberport"
    origin_info   = ORIGINS[origin_key]
    dest_info     = ORIGINS[dest_key]
    route_key     = f"route_{route_id}"
    waypoints     = TRAFFIC_WAYPOINTS[origin_key][route_key]

    # 构建节点标签列表：起点 + 3 个途径点 + 终点
    point_labels = (
        [origin_info["name"]]
        + [wp["label"] for wp in waypoints]
        + [dest_info["name"]]
    )

    # Directions API 调用
    result = gmaps.directions(
        origin=f"{origin_info['lat']},{origin_info['lng']}",
        destination=f"{dest_info['lat']},{dest_info['lng']}",
        waypoints=[f"{wp['lat']},{wp['lng']}" for wp in waypoints],
        mode="driving",
        departure_time=departure_time,
        traffic_model="best_guess",
    )

    if not result:
        raise RuntimeError(
            f"Directions API 返回空结果（origin={origin_key}, route={route_id}）"
        )

    route = result[0]
    legs  = route["legs"]   # 4 个 leg，对应 4 段

    # ── 逐段计算 ─────────────────────────────────────────────────────
    segments          = []
    cumulative_actual = 0  # 已累计的实际行驶时间（秒），用于估算到达时刻

    for i, leg in enumerate(legs):
        free_flow_s = leg["duration"]["value"]
        actual_s    = leg.get("duration_in_traffic", leg["duration"])["value"]
        distance_m  = leg["distance"]["value"]
        delay_s     = max(0, actual_s - free_flow_s)
        bti         = round(delay_s / free_flow_s, 4) if free_flow_s > 0 else 0.0

        # 预计到达该段终点的时刻
        arrival_ts  = departure_time.timestamp() + cumulative_actual + actual_s
        arrival_iso = datetime.fromtimestamp(arrival_ts).isoformat()

        segments.append({
            "leg_index":             i,
            "segment_name":          f"{point_labels[i]} → {point_labels[i + 1]}",
            "start_label":           point_labels[i],
            "end_label":             point_labels[i + 1],
            "start_address":         leg.get("start_address", ""),
            "end_address":           leg.get("end_address", ""),
            "start_location":        leg["start_location"],
            "end_location":          leg["end_location"],
            "distance_m":            distance_m,
            "free_flow_duration_s":  free_flow_s,
            "actual_duration_s":     actual_s,
            "congestion_delay_s":    delay_s,
            "bti":                   bti,
            "estimated_arrival_iso": arrival_iso,
        })

        cumulative_actual += actual_s

    # ── 路线汇总 ──────────────────────────────────────────────────────
    total_distance_m  = sum(s["distance_m"]           for s in segments)
    total_free_flow_s = sum(s["free_flow_duration_s"] for s in segments)
    total_actual_s    = sum(s["actual_duration_s"]    for s in segments)
    total_delay_s     = max(0, total_actual_s - total_free_flow_s)
    total_bti         = (
        round(total_delay_s / total_free_flow_s, 4)
        if total_free_flow_s > 0 else 0.0
    )

    # ── 原始 API legs 字段（仅保留有意义的字段，过滤超大 steps） ─────
    raw_legs = [
        {
            "start_address":       leg.get("start_address", ""),
            "end_address":         leg.get("end_address", ""),
            "start_location":      leg["start_location"],
            "end_location":        leg["end_location"],
            "distance":            leg["distance"],
            "duration":            leg["duration"],
            "duration_in_traffic": leg.get("duration_in_traffic", leg["duration"]),
        }
        for leg in legs
    ]

    return {
        "raw_api_response": {
            "summary":        route.get("summary", ""),
            "warnings":       route.get("warnings", []),
            "waypoint_order": route.get("waypoint_order", []),
            "legs":           raw_legs,
        },
        "computed": {
            "departure_time_iso":         departure_time.isoformat(),
            "segments":                   segments,
            "total_distance_m":           total_distance_m,
            "total_free_flow_duration_s": total_free_flow_s,
            "total_actual_duration_s":    total_actual_s,
            "total_congestion_delay_s":   total_delay_s,
            "total_bti":                  total_bti,
        },
    }
