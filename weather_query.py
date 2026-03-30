"""
weather_query.py
================
功能：
  1. 自动获取本机当前所在的经纬度（基于 IP 地理定位）
  2. 调用 Azure Maps Weather API 获取当前天气状况
  3. 输出天气概况、云量（%）、风速（km/h）等关键信息

依赖库：
  - requests  （用于发送 HTTP 请求）

安装依赖：
  pip install requests
"""

import requests
import sys
import json
from datetime import datetime

# 强制将标准输出设为 UTF-8，避免 Windows 终端 GBK 编码导致的 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ─────────────────────────────────────────────
#  全局配置
# ─────────────────────────────────────────────
import os
# Azure Maps 共享主密钥（Primary Key）
AZURE_MAPS_KEY = os.environ.get("AZURE_MAPS_KEY")

# Azure Maps Weather API 端点
# api-version=1.1 是当前稳定版本
WEATHER_API_URL = "https://atlas.microsoft.com/weather/currentConditions/json"

# IP 地理定位服务（无需注册，免费使用，精度到城市级别）
# 返回字段示例：{"ip":"...","city":"...","loc":"39.9042,116.4074",...}
IP_GEO_URL = "https://ipinfo.io/json"

# 请求超时时间（秒）
REQUEST_TIMEOUT = 10


# ─────────────────────────────────────────────
#  第一步：获取本机当前经纬度
# ─────────────────────────────────────────────

def get_current_location() -> tuple[float, float, str]:
    """
    通过 ipinfo.io 的 IP 地理定位服务获取本机大致位置。

    原理：
        ipinfo.io 根据出口 IP 地址反查所在城市的经纬度。
        精度通常在城市级别（误差数公里），适合获取天气信息。

    返回：
        (latitude, longitude, city_name)
        latitude  -- 纬度，浮点数，正值为北纬
        longitude -- 经度，浮点数，正值为东经
        city_name -- 城市名称字符串，用于显示

    异常：
        若网络请求失败，打印错误并退出程序。
    """
    print("▶ 正在通过 IP 定位获取当前经纬度 ...")

    try:
        response = requests.get(IP_GEO_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()          # 若 HTTP 状态码非 2xx，抛出异常
    except requests.RequestException as e:
        print(f"  [错误] 无法连接到 IP 定位服务：{e}")
        sys.exit(1)

    data = response.json()

    # "loc" 字段格式为 "纬度,经度"，例如 "39.9042,116.4074"
    if "loc" not in data:
        print("  [错误] IP 定位服务返回数据中不包含位置信息。")
        sys.exit(1)

    lat_str, lon_str = data["loc"].split(",")
    latitude  = float(lat_str)
    longitude = float(lon_str)

    # 拼接城市 + 国家显示名称（字段可能为空，使用 get 提供默认值）
    city    = data.get("city",    "未知城市")
    region  = data.get("region",  "")
    country = data.get("country", "")
    city_name = f"{city}, {region}, {country}".strip(", ")

    print(f"  ✔ 当前位置：{city_name}")
    print(f"  ✔ 经纬度：纬度 {latitude:.4f}°，经度 {longitude:.4f}°")
    return latitude, longitude, city_name


# ─────────────────────────────────────────────
#  第二步：调用 Azure Maps Weather API
# ─────────────────────────────────────────────

def get_weather(latitude: float, longitude: float) -> dict:
    """
    调用 Azure Maps "Get Current Weather Conditions" 接口。

    API 文档：
        https://learn.microsoft.com/zh-cn/rest/api/maps/weather/get-current-conditions

    请求参数说明：
        api-version      -- API 版本，固定 "1.1"
        query            -- 经纬度，格式 "lat,lon"
        subscription-key -- Azure Maps 共享主密钥
        unit             -- 单位制；"metric" 表示公制（℃、km/h）

    返回：
        解析后的 JSON 字典（results 列表的第一个元素）

    异常：
        若请求失败，打印错误并退出程序。
    """
    print("\n▶ 正在查询 Azure Maps 实时天气 ...")

    params = {
        "api-version":      "1.1",
        "query":            f"{latitude},{longitude}",   # 格式：纬度,经度
        "subscription-key": AZURE_MAPS_KEY,
        "unit":             "metric",                    # 公制单位
    }

    try:
        response = requests.get(
            WEATHER_API_URL,
            params=params,
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        # HTTP 错误（如 401 未授权、403 禁止等）
        print(f"  [HTTP 错误] {e}")
        print(f"  响应内容：{response.text}")
        sys.exit(1)
    except requests.RequestException as e:
        # 网络层错误（DNS 失败、连接超时等）
        print(f"  [网络错误] {e}")
        sys.exit(1)

    data = response.json()

    # API 返回的顶层结构为 {"results": [...]}
    # results 是一个列表，通常只有一个元素（当前时刻的天气）
    if "results" not in data or len(data["results"]) == 0:
        print("  [错误] API 返回数据为空，请检查密钥或坐标是否有效。")
        print(f"  原始响应：{json.dumps(data, ensure_ascii=False, indent=2)}")
        sys.exit(1)

    return data["results"][0]


# ─────────────────────────────────────────────
#  第三步：解析并打印天气信息
# ─────────────────────────────────────────────

def print_weather_report(weather: dict, city_name: str, lat: float, lon: float) -> None:
    """
    从 Azure Maps Weather API 返回的字典中提取关键字段并格式化输出。

    主要字段说明（来自 API 文档）：
        dateTime              -- 观测时间（ISO 8601）
        phrase                -- 天气描述短语，如 "Partly cloudy"
        temperature.value     -- 气温（℃）
        realFeelTemperature   -- 体感温度（℃）
        relativeHumidity      -- 相对湿度（%）
        cloudCover            -- 云量（0–100%）
        wind.direction.degrees-- 风向（角度，0=正北，顺时针）
        wind.direction.localizedDescription -- 风向描述，如 "NW"
        wind.speed.value      -- 风速（km/h，使用 metric 单位时）
        windGust.speed.value  -- 阵风风速（km/h）
        visibility.value      -- 能见度（km）
        uvIndex               -- 紫外线指数
        precipitationSummary.past1Hours.value -- 过去 1 小时降水量（mm）

    参数：
        weather   -- API 返回的单条天气字典
        city_name -- 城市名称（用于标题显示）
        lat, lon  -- 经纬度（用于标题显示）
    """

    # ── 辅助函数：安全取嵌套字段，避免 KeyError ──────────────────────
    def safe_get(d: dict, *keys, default="N/A"):
        """递归获取嵌套字典的值，任意层级不存在时返回 default。"""
        for key in keys:
            if not isinstance(d, dict):
                return default
            d = d.get(key, None)
            if d is None:
                return default
        return d

    # ── 解析各字段 ────────────────────────────────────────────────────

    # 观测时间（UTC），转为本地可读格式
    raw_time = safe_get(weather, "dateTime", default="")
    try:
        obs_time = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        obs_time_str = obs_time.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, AttributeError):
        obs_time_str = raw_time or "N/A"

    phrase          = safe_get(weather, "phrase")                            # 天气描述
    temperature     = safe_get(weather, "temperature", "value")              # 气温 ℃
    feel_temp       = safe_get(weather, "realFeelTemperature", "value")      # 体感温度 ℃
    humidity        = safe_get(weather, "relativeHumidity")                  # 相对湿度 %
    cloud_cover     = safe_get(weather, "cloudCover")                        # 云量 %
    wind_dir_deg    = safe_get(weather, "wind", "direction", "degrees")      # 风向角度
    wind_dir_desc   = safe_get(weather, "wind", "direction", "localizedDescription")  # 风向
    wind_speed      = safe_get(weather, "wind", "speed", "value")            # 风速 km/h
    gust_speed      = safe_get(weather, "windGust", "speed", "value")        # 阵风 km/h
    visibility      = safe_get(weather, "visibility", "value")               # 能见度 km
    uv_index        = safe_get(weather, "uvIndex")                           # 紫外线指数
    precip_1h       = safe_get(weather, "precipitationSummary",
                                "past1Hours", "value")                        # 1h 降水量 mm

    # ── 云量等级描述 ──────────────────────────────────────────────────
    def cloud_level(pct) -> str:
        """将云量百分比映射为中文等级描述。"""
        if not isinstance(pct, (int, float)):
            return ""
        if pct <= 10:  return "晴空（≤10%）"
        if pct <= 30:  return "少云（11-30%）"
        if pct <= 60:  return "多云（31-60%）"
        if pct <= 80:  return "阴天（61-80%）"
        return         "浓云/阴（>80%）"

    # ── 风速等级（蒲福风级简化版）────────────────────────────────────
    def wind_level(kmh) -> str:
        """将 km/h 风速映射为蒲福风级描述。"""
        if not isinstance(kmh, (int, float)):
            return ""
        if kmh < 1:    return "静风（0级）"
        if kmh < 6:    return "软风（1级）"
        if kmh < 12:   return "轻风（2级）"
        if kmh < 20:   return "微风（3级）"
        if kmh < 29:   return "和风（4级）"
        if kmh < 39:   return "清风（5级）"
        if kmh < 50:   return "强风（6级）"
        if kmh < 62:   return "疾风（7级）"
        if kmh < 75:   return "大风（8级）"
        if kmh < 89:   return "烈风（9级）"
        if kmh < 103:  return "狂风（10级）"
        if kmh < 117:  return "暴风（11级）"
        return         "飓风（12级及以上）"

    # ── 打印报告 ──────────────────────────────────────────────────────
    separator = "═" * 52

    print(f"\n{separator}")
    print(f"  Azure Maps 实时天气报告")
    print(separator)
    print(f"  地点：{city_name}")
    print(f"  坐标：{lat:.4f}°N, {lon:.4f}°E")
    print(f"  观测时间：{obs_time_str}")
    print(separator)

    print(f"\n  【天气概况】")
    print(f"    天气描述    ：{phrase}")
    print(f"    气温        ：{temperature} ℃")
    print(f"    体感温度    ：{feel_temp} ℃")
    print(f"    相对湿度    ：{humidity} %")

    print(f"\n  【云量信息】")
    print(f"    云量        ：{cloud_cover} %  →  {cloud_level(cloud_cover)}")

    print(f"\n  【风速信息】")
    print(f"    风向        ：{wind_dir_desc}（{wind_dir_deg}°）")
    print(f"    风速        ：{wind_speed} km/h  →  {wind_level(wind_speed)}")
    print(f"    阵风风速    ：{gust_speed} km/h")

    print(f"\n  【其他信息】")
    print(f"    能见度      ：{visibility} km")
    print(f"    紫外线指数  ：{uv_index}")
    print(f"    过去1h降水量：{precip_1h} mm")

    print(f"\n{separator}\n")


# ─────────────────────────────────────────────
#  主程序入口
# ─────────────────────────────────────────────

def main():
    print("=" * 52)
    print("  Azure Maps 天气查询脚本")
    print("=" * 52)

    # 步骤 1：获取本机经纬度
    latitude, longitude, city_name = get_current_location()

    # 步骤 2：调用 Azure Maps Weather API
    weather_data = get_weather(latitude, longitude)
    print(weather_data)
    # 步骤 3：解析并打印天气报告
    print_weather_report(weather_data, city_name, latitude, longitude)


if __name__ == "__main__":
    main()
