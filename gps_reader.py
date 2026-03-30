"""
BU-353N5 GPS 定位器数据读取脚本
串口: COM7 | 波特率: 4800 | 数据位: 8
"""

import serial
import pynmea2
import time
from datetime import datetime


# ─── 串口配置 ──────────────────────────────────────────────
PORT      = "COM7"
BAUD_RATE = 4800
DATA_BITS = 8
PARITY    = serial.PARITY_NONE
STOP_BITS = serial.STOPBITS_ONE
TIMEOUT   = 1  # 秒


def parse_nmea_sentence(raw_line: str):
    """
    解析一条 NMEA 语句，返回经纬度信息字典；
    若该语句不含定位信息则返回 None。
    """
    try:
        msg = pynmea2.parse(raw_line)
    except pynmea2.ParseError:
        return None

    # GGA / RMC / GLL 均含经纬度
    if not hasattr(msg, "latitude") or not hasattr(msg, "longitude"):
        return None

    # 纬度或经度为 0.0 通常表示尚未定位
    if msg.latitude == 0.0 and msg.longitude == 0.0:
        return None

    result = {
        "sentence_type": msg.sentence_type,
        "latitude":      msg.latitude,
        "longitude":     msg.longitude,
        "lat_dir":       getattr(msg, "lat_dir",  ""),
        "lon_dir":       getattr(msg, "lon_dir",  ""),
        "timestamp":     getattr(msg, "timestamp", None),
    }

    # RMC / GGA 额外字段
    if hasattr(msg, "spd_over_grnd"):          # RMC: 速度（节）
        result["speed_knots"] = msg.spd_over_grnd
    if hasattr(msg, "true_course"):            # RMC: 航向
        result["course"] = msg.true_course
    if hasattr(msg, "altitude"):               # GGA: 海拔
        result["altitude_m"] = msg.altitude
    if hasattr(msg, "num_sats"):               # GGA: 卫星数
        result["satellites"] = msg.num_sats
    if hasattr(msg, "horizontal_dil"):         # GGA: HDOP
        result["hdop"] = msg.horizontal_dil

    return result


def print_location(info: dict):
    """格式化打印定位信息。"""
    now = datetime.now().strftime("%H:%M:%S")
    ts  = info["timestamp"] if info["timestamp"] else "N/A"
    print(f"\n[{now}] ── {info['sentence_type']} ─────────────────────")
    print(f"  纬度   : {info['latitude']:.6f}° {info['lat_dir']}")
    print(f"  经度   : {info['longitude']:.6f}° {info['lon_dir']}")
    if "altitude_m"  in info: print(f"  海拔   : {info['altitude_m']} m")
    if "speed_knots" in info: print(f"  速度   : {info['speed_knots']} 节")
    if "course"      in info: print(f"  航向   : {info['course']}°")
    if "satellites"  in info: print(f"  卫星数 : {info['satellites']}")
    if "hdop"        in info: print(f"  HDOP   : {info['hdop']}")
    print(f"  GPS时间: {ts}")


def read_gps(port=PORT, baudrate=BAUD_RATE, show_raw=False):
    """
    持续读取 GPS 数据并打印经纬度。

    参数:
        port      : 串口号，如 'COM7'
        baudrate  : 波特率，BU-353N5 默认 4800
        show_raw  : 是否同时打印原始 NMEA 语句（调试用）
    """
    print(f"正在连接 {port}（波特率 {baudrate}）…")
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=DATA_BITS,
            parity=PARITY,
            stopbits=STOP_BITS,
            timeout=TIMEOUT,
        )
    except serial.SerialException as e:
        print(f"[错误] 无法打开串口 {port}: {e}")
        return

    print(f"已连接 {port}。等待 GPS 信号，按 Ctrl+C 退出…\n")
    waiting_dot_count = 0

    try:
        while True:
            try:
                raw = ser.readline()
            except serial.SerialException as e:
                print(f"[错误] 读取串口失败: {e}")
                time.sleep(1)
                continue

            if not raw:
                # 超时未收到数据
                waiting_dot_count += 1
                if waiting_dot_count % 5 == 0:
                    print("等待卫星信号中…")
                continue

            try:
                line = raw.decode("ascii", errors="replace").strip()
            except Exception:
                continue

            if show_raw and line.startswith("$"):
                print(f"  RAW: {line}")

            # 只处理含定位信息的语句类型
            if not any(line.startswith(f"${t}") for t in
                       ("GPGGA", "GNGGA", "GPRMC", "GNRMC", "GPGLL", "GNGLL")):
                continue

            info = parse_nmea_sentence(line)
            if info:
                waiting_dot_count = 0
                print_location(info)

    except KeyboardInterrupt:
        print("\n\n用户中断，程序退出。")
    finally:
        if ser.is_open:
            ser.close()
            print(f"串口 {port} 已关闭。")


# ─── 入口 ──────────────────────────────────────────────────
if __name__ == "__main__":
    # 将 show_raw 改为 True 可查看所有原始 NMEA 语句（调试用）
    read_gps(show_raw=False)
