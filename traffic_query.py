"""
traffic_query.py
================
功能：
  根据单个经纬度坐标点，调用 Azure Maps API 获取：

  【Traffic Flow Segment API】— 坐标点所在路段的实时交通状态
    ① 当前路段速度     —— 实时交通流量下的路段行驶速度（km/h）
    ② 当前路段通行时间 —— 实时交通下通过该路段所需时间（秒）
    ③ 自由流速度       —— 无拥堵理想状态下的路段速度（km/h）
    ④ 自由流通行时间   —— 无拥堵理想状态下通过该路段所需时间（秒）
    ⑤ 路段节点坐标     —— 路段完整折线节点列表，含每点转向角（用于弯曲度计算）

  【Traffic Incident API】— 坐标点 1km 范围内的交通事件
    ⑤ 事件类型         —— 事故/施工/封路/拥堵等
    ⑥ 延误等级         —— 0=未知 1=轻微 2=适中 3=重大 4=封路
    ⑦ 事件描述         —— 文字说明（如"道路封闭"）
    ⑧ 预计延误时间     —— 通过该事件路段额外需要的时间（秒）
    ⑨ 受影响路名       —— 事件所在道路名称/编号

使用的 API：
  - Traffic Flow Segment API
    文档：https://learn.microsoft.com/zh-cn/rest/api/maps/traffic/get-traffic-flow-segment
  - Traffic Incident Viewport API（获取 trafficmodelid）
    文档：https://learn.microsoft.com/zh-cn/rest/api/maps/traffic/get-traffic-incident-viewport
  - Traffic Incident Detail API（获取事件详情）
    文档：https://learn.microsoft.com/zh-cn/rest/api/maps/traffic/get-traffic-incident-detail

坐标输入格式：
  GeoJSON 惯例：(经度, 纬度) 顺序。
  调用 Azure Maps API 时自动转换为其要求的 (纬度, 经度) 顺序。

依赖库：
  - requests

安装依赖：
  pip install requests
"""

import sys
import math
import json
import requests
from datetime import datetime

# 强制 UTF-8 输出，避免 Windows 终端 GBK 编码导致乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ══════════════════════════════════════════════════════════════
#  全局配置
# ══════════════════════════════════════════════════════════════
import os
# Azure Maps 共享主密钥（Primary Key）
AZURE_MAPS_KEY = os.environ.get("AZURE_MAPS_KEY")

# ── 输入坐标（GeoJSON 惯例：经度在前，纬度在后）────────────────
# 实车使用时将此处替换为当前 GPS 坐标
POINT = (114.18892673199872, 22.300936974545845)   # (经度, 纬度)

# ── 事件查询半径（单位：km）────────────────────────────────────
# 以每个坐标点为中心，查询该半径范围内的所有交通事件
INCIDENT_RADIUS_KM = 1.0

# ── Azure Maps API 端点 ────────────────────────────────────────
TRAFFIC_FLOW_SEGMENT_URL  = "https://atlas.microsoft.com/traffic/flow/segment/json"
TRAFFIC_INCIDENT_VIEWPORT = "https://atlas.microsoft.com/traffic/incident/viewport/json"
TRAFFIC_INCIDENT_DETAIL   = "https://atlas.microsoft.com/traffic/incident/detail/json"

# 请求超时（秒）
REQUEST_TIMEOUT = 15


# ══════════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════════

def safe_get(d: dict, *keys, default="N/A"):
    """
    安全递归取嵌套字典的值。
    任意中间层不存在或类型不符时返回 default，避免 KeyError。
    """
    for key in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(key)
        if d is None:
            return default
    return d


def lon_lat_to_query(lon: float, lat: float) -> str:
    """
    将 (经度, 纬度) 转换为 Azure Maps 查询字符串格式 "纬度,经度"。
    Azure Maps 所有接口的 query/boundingbox 参数均使用纬度在前的顺序。
    """
    return f"{lat},{lon}"


def seconds_to_hms(seconds) -> str:
    """将秒数格式化为可读字符串。"""
    if not isinstance(seconds, (int, float)):
        return str(seconds)
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    if m == 0:
        return f"{s} 秒"
    return f"{m} 分 {s} 秒"


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    计算从点1到点2的方位角（0°~360°，正北为0°，顺时针）。

    使用球面三角学公式，适合短距离路段节点间的方向计算。
    """
    dlon = math.radians(lon2 - lon1)
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    x = math.sin(dlon) * math.cos(rlat2)
    y = math.cos(rlat1) * math.sin(rlat2) - math.sin(rlat1) * math.cos(rlat2) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360


def turning_angle(lat_a: float, lon_a: float,
                  lat_b: float, lon_b: float,
                  lat_c: float, lon_c: float) -> float:
    """
    计算路段在 B 点处的转向角（0°~180°）。

    原理：
        计算 A→B 和 B→C 两段的方位角差值。
        差值绝对值即为 B 点处的转向角，越大说明该点越弯曲。
          0°~5°  ：直路
          5°~20° ：轻微弯道
         20°~45° ：中等弯道
         45°以上 ：急弯
    """
    b_in  = bearing(lat_a, lon_a, lat_b, lon_b)   # 进入 B 点的方向
    b_out = bearing(lat_b, lon_b, lat_c, lon_c)   # 离开 B 点的方向
    diff  = abs(b_out - b_in)
    # 方位角差值大于 180° 时取补角（因为 0° 和 359° 之差应为 1°）
    return min(diff, 360 - diff)


def curvature_label(angle: float) -> str:
    """将转向角映射为中文弯曲等级描述。"""
    if angle < 5:   return "直路"
    if angle < 20:  return "轻微弯道"
    if angle < 45:  return "中等弯道"
    return              "急弯"


def build_bounding_box(lon: float, lat: float, radius_km: float) -> tuple:
    """
    以 (lon, lat) 为中心，构建边长约为 2×radius_km 的矩形边界框。

    原理：
        纬度方向：1° ≈ 111.0 km（全球一致）
        经度方向：1° ≈ 111.0 × cos(纬度) km（随纬度变化）
    
    返回：
        (min_lat, min_lon, max_lat, max_lon) 的元组
        即 Azure Maps boundingbox 参数要求的顺序
    """
    # 纬度偏移量（°）
    lat_offset = radius_km / 111.0
    # 经度偏移量（°），需除以 cos(纬度) 修正经线收缩
    lon_offset = radius_km / (111.0 * math.cos(math.radians(lat)))

    min_lat = lat - lat_offset
    max_lat = lat + lat_offset
    min_lon = lon - lon_offset
    max_lon = lon + lon_offset
    return (min_lat, min_lon, max_lat, max_lon)


# ══════════════════════════════════════════════════════════════
#  第一部分：Traffic Flow Segment API
#  GET /traffic/flow/segment/json
# ══════════════════════════════════════════════════════════════

def get_traffic_flow_segment(lon: float, lat: float, point_name: str) -> dict:
    """
    查询指定坐标点所在路段的实时交通流量数据。

    关键请求参数：
        style   -- "absolute"：返回 km/h 绝对速度值
        zoom    -- 地图缩放级别，影响路段粒度；
                   脚本从高到低自动回退，直到找到有效路段
                     15：城市街道级（香港等国际地区首选）
                     12：城市道路级
                     10：城市区域级
                      8：干道/城际级（中国大陆通常可用的最高级别）
                      6：主干道/省道级

    返回：
        flowSegmentData 字典
    """
    print(f"\n  ▶ 查询{point_name}路段交通流量 ({lat:.6f}, {lon:.6f}) ...")

    zoom_candidates = [15, 12, 10, 8, 6]
    query_str = lon_lat_to_query(lon, lat)

    for zoom in zoom_candidates:
        params = {
            "api-version":      "1.0",
            "style":            "absolute",
            "zoom":             zoom,
            "query":            query_str,
            "subscription-key": AZURE_MAPS_KEY,
        }
        try:
            resp = requests.get(TRAFFIC_FLOW_SEGMENT_URL, params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            print(f"    [网络错误] {e}")
            sys.exit(1)

        if resp.status_code == 200:
            data = resp.json()
            if "flowSegmentData" in data:
                zoom_label = {
                    15: "城市街道", 12: "城市道路",
                    10: "城市区域",  8: "干道/城际", 6: "主干道/省道"
                }.get(zoom, f"zoom={zoom}")
                print(f"    ✔ 路段数据获取成功（zoom={zoom}，{zoom_label}级别）")
                fsd = data["flowSegmentData"]
                # 将输入 GPS 坐标注入结果字典，供 print_segment_report 定位最近节点使用
                fsd["_gps_lat"] = lat
                fsd["_gps_lon"] = lon
                return fsd

        try:
            err_msg = resp.json().get("error", {}).get("message", "")
        except Exception:
            err_msg = ""

        if "too far from nearest" in err_msg.lower() or resp.status_code == 400:
            print(f"    ⚠ zoom={zoom} 该区域无路段数据，尝试更低精度...")
            continue

        print(f"    [HTTP 错误] {resp.status_code}\n    响应：{resp.text}")
        sys.exit(1)

    print(f"    [错误] 该坐标在所有 zoom 级别下均无路段数据，可能超出 Azure Maps 覆盖范围。")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════
#  第二部分：Traffic Incident API（两步调用）
#  步骤 A：GET /traffic/incident/viewport/json  → 获取 trafficmodelid
#  步骤 B：GET /traffic/incident/detail/json   → 获取事件详情
# ══════════════════════════════════════════════════════════════

def get_traffic_model_id(bbox: tuple) -> str:
    """
    调用 Traffic Incident Viewport API，获取当前时刻的交通模型 ID。

    trafficmodelid 是 Azure Maps 服务端交通数据快照的时间戳标识符。
    每隔约 1 分钟更新一次，必须在查询事件详情前实时获取，
    不能写死——否则查询的是过期快照的数据。

    参数：
        bbox -- (min_lat, min_lon, max_lat, max_lon) 边界框元组

    返回：
        trafficmodelid 字符串
    """
    min_lat, min_lon, max_lat, max_lon = bbox
    bb_str = f"{min_lat},{min_lon},{max_lat},{max_lon}"

    # overviewBox 是 Viewport API 的必填参数，表示"概览视图"的边界框。
    # 通常设置为比 boundingbox 更大的范围（此处扩大 3 倍半径）。
    # Azure Maps 用它来决定哪些事件在概览图中聚合显示。
    min_lat, min_lon, max_lat, max_lon = bbox
    lat_c = (min_lat + max_lat) / 2
    lon_c = (min_lon + max_lon) / 2
    lat_half = (max_lat - min_lat) * 1.5
    lon_half = (max_lon - min_lon) * 1.5
    overview_bb_str = (f"{lat_c - lat_half},{lon_c - lon_half},"
                       f"{lat_c + lat_half},{lon_c + lon_half}")

    params = {
        "api-version":      "1.0",
        "boundingbox":      bb_str,
        "boundingZoom":     11,           # 主视图城市级别缩放
        "overviewBox":      overview_bb_str,  # 概览视图（更大范围）
        "overviewZoom":     9,            # 概览视图缩放级别（比主视图低）
        "subscription-key": AZURE_MAPS_KEY,
    }

    try:
        resp = requests.get(TRAFFIC_INCIDENT_VIEWPORT, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"    [HTTP 错误（Viewport）] {e}\n    响应：{resp.text}")
        sys.exit(1)
    except requests.RequestException as e:
        print(f"    [网络错误（Viewport）] {e}")
        sys.exit(1)

    data = resp.json()

    # Viewport API 实际返回的结构为：
    #   { "viewpResp": { "trafficState": { "@trafficModelId": "...", "@trafficAge": ... } } }
    # 字段名带 "@" 前缀是 Azure Maps v1.0 的私有格式。
    model_id = safe_get(data, "viewpResp", "trafficState", "@trafficModelId", default=None)

    if model_id is None:
        print(f"    [错误] 无法获取 trafficmodelid。原始响应：")
        print(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(1)

    return str(model_id)


def get_traffic_incidents(lon: float, lat: float,
                           radius_km: float, point_name: str) -> list:
    """
    查询指定坐标点 radius_km 公里范围内的所有交通事件。

    流程：
        1. 根据坐标和半径构建边界框
        2. 调用 Viewport API 获取最新 trafficmodelid
        3. 用 trafficmodelid 调用 Incident Detail API 获取事件列表

    关键请求参数（Incident Detail）：
        boundingbox    -- 矩形查询范围，格式：min_lat,min_lon,max_lat,max_lon
        boundingZoom   -- 缩放级别，影响事件聚合程度；
                          11=城市级，较高值返回更细粒度的独立事件
        trafficmodelid -- 从 Viewport API 实时获取的数据快照 ID
        language       -- 事件描述语言；zh-HK=繁体中文（适合香港），en-US=英文
        expandCluster  -- true=展开聚合点，返回每个独立事件（而非合并的聚合图标）
        projection     -- 坐标系；EPSG4326=WGS84（GPS 标准，与输入坐标一致）

    返回：
        事件特征列表（GeoJSON Feature 格式），无事件时返回空列表
    """
    print(f"\n  ▶ 查询{point_name}周边 {radius_km} km 范围内的交通事件 ...")

    bbox = build_bounding_box(lon, lat, radius_km)
    min_lat, min_lon, max_lat, max_lon = bbox
    bb_str = f"{min_lat},{min_lon},{max_lat},{max_lon}"

    # 步骤 A：获取 trafficmodelid
    print(f"    → 获取 trafficmodelid ...")
    model_id = get_traffic_model_id(bbox)
    print(f"    ✔ trafficmodelid = {model_id}")

    # 步骤 B：查询事件详情
    params = {
        "api-version":      "1.0",
        "boundingbox":      bb_str,
        "boundingZoom":     11,
        "trafficmodelid":   model_id,
        "subscription-key": AZURE_MAPS_KEY,
        # style 是必填参数，控制返回的图标样式集
        # "s1"=日间标准样式，"s2"=夜间样式，"s3"=高对比度样式
        # 样式仅影响图标渲染用途的元数据，不影响事件数据内容本身
        "style":            "s1",
    }

    try:
        resp = requests.get(TRAFFIC_INCIDENT_DETAIL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"    [HTTP 错误（Incident Detail）] {e}\n    响应：{resp.text}")
        sys.exit(1)
    except requests.RequestException as e:
        print(f"    [网络错误（Incident Detail）] {e}")
        sys.exit(1)

    data = resp.json()

    # api-version=1.0 返回私有格式：
    #   { "tm": { "@id": "模型ID", "poi": [ ...事件列表... ] } }
    # poi 为空列表时表示该区域当前无交通事件，属正常情况。
    incidents = data.get("tm", {}).get("poi", [])

    count = len(incidents)
    print(f"    ✔ 发现 {count} 个交通事件")
    return incidents


# ══════════════════════════════════════════════════════════════
#  第三部分：格式化输出
# ══════════════════════════════════════════════════════════════

def print_segment_report(seg: dict, point_name: str) -> None:
    """
    打印 Traffic Flow Segment API 返回的路段交通数据。

    主要字段：
        frc                -- 功能道路等级（FRC0=高速，FRC6=小路）
        currentSpeed       -- 当前实测速度（km/h）
        freeFlowSpeed      -- 自由流速度（km/h），历史无拥堵基准
        currentTravelTime  -- 当前实时通行时间（秒）
        freeFlowTravelTime -- 自由流通行时间（秒）
        confidence         -- 数据置信度（0.0~1.0）
        coordinates        -- 路段折线几何节点列表
    """
    frc_desc = {
        "FRC0": "高速公路",    "FRC1": "主干道",
        "FRC2": "次干道/快速路", "FRC3": "城市主路",
        "FRC4": "城市次路",    "FRC5": "支路",
        "FRC6": "小路",        "FRC7": "步行/非机动车道",
    }

    frc        = safe_get(seg, "frc")
    frc_cn     = frc_desc.get(frc, "未知等级")
    cur_speed  = safe_get(seg, "currentSpeed")
    free_speed = safe_get(seg, "freeFlowSpeed")
    cur_time   = safe_get(seg, "currentTravelTime")
    free_time  = safe_get(seg, "freeFlowTravelTime")
    confidence = safe_get(seg, "confidence")

    # 拥堵指数 = 当前速度 / 自由流速度
    if isinstance(cur_speed, (int, float)) and isinstance(free_speed, (int, float)) and free_speed > 0:
        ratio = cur_speed / free_speed
        if   ratio >= 0.9: congestion = "畅通"
        elif ratio >= 0.7: congestion = "基本畅通"
        elif ratio >= 0.5: congestion = "轻度拥堵"
        elif ratio >= 0.3: congestion = "中度拥堵"
        else:              congestion = "严重拥堵"
        congestion_str = f"{congestion}（当前/自由流 = {ratio:.0%}）"

        # 路段延误 = 当前通行时间 - 自由流通行时间
        if isinstance(cur_time, (int, float)) and isinstance(free_time, (int, float)):
            delay = cur_time - free_time
            delay_str = f"{delay} 秒  ({seconds_to_hms(delay)})"
        else:
            delay_str = "N/A"
    else:
        congestion_str = "N/A"
        delay_str      = "N/A"

    # ── 提取路段节点（供后续节点打印使用）────────────────────────
    nodes = safe_get(seg, "coordinates", "coordinate", default=[])

    # ── 找到离输入 GPS 最近的节点 ────────────────────────────────
    nearest_idx  = None
    nearest_dist = float("inf")
    if nodes and isinstance(nodes, list):
        gps_lat = safe_get(seg, "_gps_lat", default=None)
        gps_lon = safe_get(seg, "_gps_lon", default=None)
        if gps_lat is not None and gps_lon is not None:
            for i, nd in enumerate(nodes):
                nd_lat = nd.get("latitude",  nd.get("lat", None))
                nd_lon = nd.get("longitude", nd.get("lon", None))
                if nd_lat is None or nd_lon is None:
                    continue
                dlat = (nd_lat - gps_lat) * 111000
                dlon = (nd_lon - gps_lon) * 111000 * math.cos(math.radians(gps_lat))
                dist = math.sqrt(dlat**2 + dlon**2)
                if dist < nearest_dist:
                    nearest_dist = dist
                    nearest_idx  = i

    print(f"\n  ┌─ 路段信息 ──────────────────────────────────────────")
    print(f"  │  道路等级        ：{frc}  {frc_cn}")
    print(f"  │  数据置信度      ：{confidence}")
    print(f"  │")
    print(f"  │  【① 当前路段速度】     ：{cur_speed} km/h")
    print(f"  │  【② 当前路段通行时间】 ：{cur_time} 秒  ({seconds_to_hms(cur_time)})")
    print(f"  │  【③ 自由流速度】       ：{free_speed} km/h")
    print(f"  │  【④ 自由流通行时间】   ：{free_time} 秒  ({seconds_to_hms(free_time)})")
    print(f"  │")
    print(f"  │  拥堵状态        ：{congestion_str}")
    print(f"  │  路段延误时间    ：{delay_str}")
    print(f"  └────────────────────────────────────────────────────")

    # ── ⑤ 路段节点输出 ────────────────────────────────────────────
    if not nodes or not isinstance(nodes, list):
        print(f"\n  【⑤ 路段节点】：无节点数据")
        return

    total = len(nodes)

    # 预先计算每个中间节点的转向角（首尾节点无法计算，设为 None）
    angles = [None] * total
    for i in range(1, total - 1):
        def get_nd(idx):
            n = nodes[idx]
            return n.get("latitude", n.get("lat")), n.get("longitude", n.get("lon"))
        la, loa = get_nd(i - 1)
        lb, lob = get_nd(i)
        lc, loc = get_nd(i + 1)
        if None not in (la, loa, lb, lob, lc, loc):
            angles[i] = turning_angle(la, loa, lb, lob, lc, loc)

    # 路段总长度估算（相邻节点距离累加）
    total_len = 0.0
    for i in range(1, total):
        n0, n1 = nodes[i - 1], nodes[i]
        la0 = n0.get("latitude",  n0.get("lat",  0))
        lo0 = n0.get("longitude", n0.get("lon", 0))
        la1 = n1.get("latitude",  n1.get("lat",  0))
        lo1 = n1.get("longitude", n1.get("lon", 0))
        dlat = (la1 - la0) * 111000
        dlon = (lo1 - lo0) * 111000 * math.cos(math.radians((la0 + la1) / 2))
        total_len += math.sqrt(dlat**2 + dlon**2)

    # 路段整体最大转向角
    valid_angles = [a for a in angles if a is not None]
    max_angle    = max(valid_angles) if valid_angles else None
    max_label    = curvature_label(max_angle) if max_angle is not None else "N/A"

    # 最近节点信息
    if nearest_idx is not None:
        nearest_info = (f"第 {nearest_idx + 1} 号节点"
                        f"（距输入坐标 {nearest_dist:.1f} m）")
    else:
        nearest_info = "N/A（未提供 GPS 坐标）"

    print(f"\n  【⑤ 路段节点】")
    print(f"    节点总数        ：{total} 个")
    print(f"    路段估算长度    ：{total_len:.1f} m  ({total_len/1000:.3f} km)")
    print(f"    最近节点        ：{nearest_info}")
    print(f"    路段最大转向角  ：{max_angle:.1f}°  →  {max_label}"
          if max_angle is not None else f"    路段最大转向角  ：N/A")

    # 展示窗口：最近节点前后各 WINDOW 个，若无最近节点则展示首尾各3个
    WINDOW = 5
    if nearest_idx is not None:
        lo_idx = max(0, nearest_idx - WINDOW)
        hi_idx = min(total - 1, nearest_idx + WINDOW)
        show_range = range(lo_idx, hi_idx + 1)
        print(f"\n    节点详情（最近节点 ±{WINDOW} 个，共展示 {len(show_range)} 个）：")
        print(f"    {'序号':>5}  {'经度':>14}  {'纬度':>13}  {'转向角':>8}  弯曲等级   标记")
        print(f"    {'─'*5}  {'─'*14}  {'─'*13}  {'─'*8}  {'─'*8}   {'─'*4}")
        for i in show_range:
            nd  = nodes[i]
            lat = nd.get("latitude",  nd.get("lat",  "?"))
            lon = nd.get("longitude", nd.get("lon", "?"))
            ang = angles[i]
            ang_str   = f"{ang:>6.1f}°" if ang is not None else "     —  "
            label_str = curvature_label(ang) if ang is not None else "—"
            mark      = " ◀ 当前" if i == nearest_idx else ""
            print(f"    [{i+1:>4}]  {lon:>14.8f}  {lat:>13.8f}  {ang_str}  {label_str:<8}{mark}")
    else:
        # 无最近节点时展示首尾各3个
        edge = min(3, total // 2)
        print(f"\n    节点详情（前 {edge} 个 + 后 {edge} 个）：")
        print(f"    {'序号':>5}  {'经度':>14}  {'纬度':>13}  {'转向角':>8}  弯曲等级")
        print(f"    {'─'*5}  {'─'*14}  {'─'*13}  {'─'*8}  {'─'*8}")
        show = list(range(edge)) + (["..."] if total > edge * 2 else []) + list(range(total - edge, total))
        for item in show:
            if item == "...":
                print(f"    {'...':>6}  （省略中间 {total - edge * 2} 个节点）")
                continue
            nd  = nodes[item]
            lat = nd.get("latitude",  nd.get("lat",  "?"))
            lon = nd.get("longitude", nd.get("lon", "?"))
            ang = angles[item]
            ang_str   = f"{ang:>6.1f}°" if ang is not None else "     —  "
            label_str = curvature_label(ang) if ang is not None else "—"
            print(f"    [{item+1:>4}]  {lon:>14.8f}  {lat:>13.8f}  {ang_str}  {label_str}")


def print_incidents_report(incidents: list, point_name: str,
                            center_lon: float, center_lat: float) -> None:
    """
    打印 Traffic Incident Detail API 返回的事件列表。

    Azure Maps Incident API (api-version=1.0) 返回私有格式：
    每个事件（poi）的主要字段：
        id      -- 事件唯一 ID
        ic      -- iconCategory（图标分类，见下方对照表）
        ty      -- 事件类型数字代码
        cs      -- magnitudeOfDelay（延误等级，0~4）
        d       -- 事件描述文字（language 参数控制语言）
        dl      -- delay（预计延误秒数）
        f       -- from（事件起始路名）
        t       -- to（事件结束路名）
        l       -- length（受影响路段长度，米）
        r       -- roadNumber（道路编号）
        p       -- 事件位置坐标 {"x": 经度, "y": 纬度}
        ed      -- endDate（事件预计结束时间）
    """
    # iconCategory 对照表
    icon_desc = {
        0: "未知",       1: "事故",       2: "雾",
        3: "危险路面",   4: "施工",       5: "车辆故障",
        6: "道路封闭",   7: "交通管制",   8: "拥堵",
        14: "计划封路",
    }
    # 延误等级对照表
    delay_level_desc = {
        0: "未知", 1: "轻微", 2: "适中", 3: "重大", 4: "道路封闭"
    }

    sep_inner = "─" * 50
    print(f"\n  ┌─ {point_name}周边 {INCIDENT_RADIUS_KM} km 事件列表"
          f"（共 {len(incidents)} 个）────────────────")

    if not incidents:
        print(f"  │  该范围内当前无交通事件。")
        print(f"  └{sep_inner}")
        return

    for i, poi in enumerate(incidents, 1):
        # Azure Maps Traffic Incident Detail API (api-version=1.0) 私有格式字段：
        #   ic  -- iconCategory：事件图标分类（整数）
        #   ty  -- type：事件类型代码（整数，与 ic 相近但更细化）
        #   cs  -- clusterSize / magnitudeOfDelay：延误等级（0~4）
        #   d   -- description：事件文字描述
        #   dl  -- delay：预计延误秒数
        #   f   -- from：事件起始路名
        #   t   -- to：事件结束路名
        #   r   -- roadNumbers：道路编号（字符串）
        #   l   -- length：受影响路段长度（米）
        #   p   -- point：事件位置坐标，{"x": 经度, "y": 纬度}
        #   ed  -- endDate：预计结束时间
        icon_cat    = poi.get("ic",  0)
        delay_level = poi.get("cs",  0)
        description = poi.get("d",   "（无描述）")
        delay_sec   = poi.get("dl",  None)
        road_from   = poi.get("f",   "")
        road_to     = poi.get("t",   "")
        road_number = poi.get("r",   "")
        length_m    = poi.get("l",   None)
        pos         = poi.get("p",   {})
        evt_lon     = pos.get("x",   None)
        evt_lat     = pos.get("y",   None)

        # 计算事件与查询中心点的直线距离（粗略估算）
        dist_str = "N/A"
        if evt_lon is not None and evt_lat is not None:
            dlat = (evt_lat - center_lat) * 111.0
            dlon = (evt_lon - center_lon) * 111.0 * math.cos(math.radians(center_lat))
            dist_km = math.sqrt(dlat**2 + dlon**2)
            dist_str = f"{dist_km:.2f} km"

        icon_cn  = icon_desc.get(icon_cat, f"类型{icon_cat}")
        level_cn = delay_level_desc.get(delay_level, str(delay_level))

        # 路段描述（from → to 或 road number）
        if road_from and road_to:
            road_desc = f"{road_from} → {road_to}"
        elif road_number:
            road_desc = road_number
        else:
            road_desc = "（路段不详）"

        # 受影响长度
        length_str = f"{length_m} m" if isinstance(length_m, (int, float)) else "N/A"

        # 延误时间
        delay_str = f"{delay_sec} 秒  ({seconds_to_hms(delay_sec)})" \
                    if isinstance(delay_sec, (int, float)) else "N/A"

        print(f"  │")
        print(f"  │  [{i}] ⑤ 事件类型     ：{icon_cn}（iconCategory={icon_cat}）")
        print(f"  │      ⑥ 延误等级     ：{level_cn}（等级 {delay_level}/4）")
        print(f"  │      ⑦ 事件描述     ：{description}")
        print(f"  │      ⑧ 预计延误时间 ：{delay_str}")
        print(f"  │      ⑨ 受影响路段   ：{road_desc}")
        print(f"  │         受影响长度   ：{length_str}")
        if evt_lon and evt_lat:
            print(f"  │         事件位置     ：经度 {evt_lon:.6f}, 纬度 {evt_lat:.6f}")
        print(f"  │         距查询中心   ：{dist_str}")

    print(f"  └{sep_inner}")


# ══════════════════════════════════════════════════════════════
#  主程序
# ══════════════════════════════════════════════════════════════

def main():
    sep = "═" * 56

    print(sep)
    print("  Azure Maps 交通数据查询脚本")
    print(sep)
    print(f"  查询坐标：经度 {POINT[0]},  纬度 {POINT[1]}")
    print(f"  事件查询半径：{INCIDENT_RADIUS_KM} km")
    print(sep)

    lon, lat = POINT

    # ── 步骤 1：路段交通流量 ──────────────────────────────────────
    print("\n[ 步骤 1/2 ]  查询路段交通流量")
    seg = get_traffic_flow_segment(lon, lat, "当前坐标")

    # ── 步骤 2：周边交通事件 ──────────────────────────────────────
    print("\n[ 步骤 2/2 ]  查询周边交通事件")
    incidents = get_traffic_incidents(lon, lat, INCIDENT_RADIUS_KM, "当前坐标")

    # ── 输出报告 ──────────────────────────────────────────────────
    print(f"\n\n{sep}")
    print("  查询结果")
    print(sep)

    print_segment_report(seg, "当前坐标")
    print_incidents_report(incidents, "当前坐标", lon, lat)

    print(f"\n{sep}\n")


if __name__ == "__main__":
    main()
