"""
test.py  —  采集前设备测试脚本
================================
在运行 collect.py 前，执行本脚本确认各设备工作正常：
  1. 摄像头测试：打开两路摄像头，显示实时预览，方便固定摄像头位置
  2. GPS 测试：连接串口，读取并显示若干次定位结果

操作：
  预览窗口中按 'q' 退出摄像头预览，进入 GPS 测试
  GPS 测试期间按 Ctrl+C 提前结束

依赖：
  pip install opencv-python pyserial pynmea2
"""

import sys
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

import cv2
import numpy as np
import serial
import pynmea2

sys.path.insert(0, str(Path(__file__).parent))
import config

# 强制 UTF-8 输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BEIJING_TZ = timezone(timedelta(hours=8))


def beijing_now_str() -> str:
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


# ══════════════════════════════════════════════════════════════════════════════
#  1. 摄像头测试
# ══════════════════════════════════════════════════════════════════════════════

# 每路预览的缩放尺寸（合并后窗口宽度 = PREVIEW_W × 2）
PREVIEW_W = 640
PREVIEW_H = 360
DIVIDER_W = 8    # 中间分割线宽度（像素）


def _draw_overlay(frame: np.ndarray, label: str, ts: str) -> np.ndarray:
    """在帧上绘制标签（左上角）和时间戳（左下角）。"""
    h, w = frame.shape[:2]
    # 半透明背景条（上方标签区）
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 48), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)
    # 标签
    cv2.putText(frame, label, (10, 33),
                cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 210, 255), 2, cv2.LINE_AA)
    # 时间戳（左下角）
    cv2.putText(frame, ts, (8, h - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 80), 2, cv2.LINE_AA)
    return frame


def _capture_worker(cap: cv2.VideoCapture, store: dict, key: str,
                    lock: threading.Lock, running_flag: list):
    """独立线程：持续读帧并更新 store[key]，running_flag[0] 为 False 时退出。"""
    while running_flag[0]:
        ret, frame = cap.read()
        if ret:
            with lock:
                store[key] = frame
        else:
            time.sleep(0.005)


def test_cameras():
    """
    打开两路摄像头，在单窗口左右分屏显示实时预览。
    左侧：面部摄像头（Facial）  右侧：交通摄像头（Traffic）
    按 'q' 关闭预览并继续执行 GPS 测试。
    """
    step_label = "1/1" if config.TEST_CAMERAS else "2/2"
    print("\n" + "=" * 64)
    print(f"  [{step_label}] 摄像头测试 & 分屏预览")
    print("=" * 64)

    cam_defs = [
        (config.FACIAL_CAMERA_INDEX,  "Facial  (Camera 1)"),
        (config.TRAFFIC_CAMERA_INDEX, "Traffic (Camera 2)"),
    ]

    caps   = []   # [(cv2.VideoCapture, label), ...]
    failed = []

    for idx, label in cam_defs:
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)   # CAP_DSHOW 在 Windows 上响应更快
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  config.FRAME_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS,          config.FPS)
        # 预热：丢掉前几帧，让摄像头曝光稳定
        for _ in range(3):
            cap.read()

        if not cap.isOpened():
            print(f"  [FAIL] {label} (索引 {idx}) — 无法打开")
            failed.append(label)
            cap.release()
        else:
            w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            print(f"  [ OK ] {label} (索引 {idx}) — {w}×{h} @ {fps:.1f}fps")
            caps.append((cap, label))

    if not caps:
        print("\n  未检测到任何可用摄像头，跳过预览。")
        print("  请检查摄像头连接 / config.py 中的摄像头索引。")
        return

    # ── 双线程采集，避免 cap.read() 串行阻塞导致画面卡顿 ──────────────────
    latest      = {}          # key -> np.ndarray
    frame_lock  = threading.Lock()
    running_flag = [True]     # 用列表传引用，线程可修改

    threads = []
    for cap, label in caps:
        key = label
        t = threading.Thread(
            target=_capture_worker,
            args=(cap, latest, key, frame_lock, running_flag),
            daemon=True,
        )
        t.start()
        threads.append(t)

    # 为缺失摄像头准备占位灰图
    placeholder = np.full((PREVIEW_H, PREVIEW_W, 3), 40, dtype=np.uint8)
    cv2.putText(placeholder, "No Signal", (PREVIEW_W // 2 - 80, PREVIEW_H // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (120, 120, 120), 2, cv2.LINE_AA)

    win_title = "Camera Preview  |  Press Q / ESC to quit"
    cv2.namedWindow(win_title, cv2.WINDOW_NORMAL)

    print(f"\n  分屏预览窗口已打开（左: Facial  右: Traffic）")
    print("  调整好摄像头位置后，按 'q' 结束预览并结束测试。\n")

    facial_label  = cam_defs[0][1]
    traffic_label = cam_defs[1][1]

    while True:
        ts = beijing_now_str()

        with frame_lock:
            f_raw = latest.get(facial_label)
            t_raw = latest.get(traffic_label)

        # 调整两侧帧到统一预览尺寸
        if f_raw is not None:
            f_pre = cv2.resize(f_raw, (PREVIEW_W, PREVIEW_H))
            _draw_overlay(f_pre, "Facial", ts)
        else:
            f_pre = placeholder.copy()

        if t_raw is not None:
            t_pre = cv2.resize(t_raw, (PREVIEW_W, PREVIEW_H))
            _draw_overlay(t_pre, "Traffic", ts)
        else:
            t_pre = placeholder.copy()

        # 分割线（深灰色竖条）
        divider = np.full((PREVIEW_H, DIVIDER_W, 3), 60, dtype=np.uint8)

        combined = np.hstack([f_pre, divider, t_pre])

        # 底部状态栏
        bar = np.zeros((28, combined.shape[1], 3), dtype=np.uint8)
        status = (f"Facial: {'OK' if f_raw is not None else '--'}   "
                  f"Traffic: {'OK' if t_raw is not None else '--'}   "
                  f"Press Q / ESC to quit")
        cv2.putText(bar, status, (8, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1, cv2.LINE_AA)

        display = np.vstack([combined, bar])
        cv2.imshow(win_title, display)

        key = cv2.waitKey(30) & 0xFF   # 30ms ≈ 33fps 刷新率
        if key in (ord("q"), ord("Q"), 27):   # q / Q / ESC 均可退出
            break

    running_flag[0] = False
    for t in threads:
        t.join(timeout=2.0)
    for cap, _ in caps:
        cap.release()
    cv2.destroyAllWindows()
    print("  摄像头预览已关闭。")


# ══════════════════════════════════════════════════════════════════════════════
#  2. GPS 测试
# ══════════════════════════════════════════════════════════════════════════════

def test_gps(n_readings: int = 5, timeout_sec=None):
    if timeout_sec is None:
        timeout_sec = config.GPS_TEST_ACQUIRE_TIMEOUT_SEC
    """
    连接 GPS 串口，读取 n_readings 次有效定位并打印。
    超过 timeout_sec 秒未获得足够定位则超时退出。
    """
    print("\n" + "=" * 64)
    print("  [1/2] GPS 测试（BU-353N5）")
    print("=" * 64)
    print(f"  串口: {config.GPS_PORT}   波特率: {config.GPS_BAUDRATE}")

    VALID_TYPES = ("GPGGA", "GNGGA", "GPRMC", "GNRMC", "GPGLL", "GNGLL")

    try:
        ser = serial.Serial(
            port=config.GPS_PORT,
            baudrate=config.GPS_BAUDRATE,
            timeout=2,
        )
        print(f"  [ OK ] 串口 {config.GPS_PORT} 已打开")
        print(f"  等待卫星定位（最多 {timeout_sec} 秒，室内信号可能较弱）...\n")
    except serial.SerialException as e:
        print(f"  [FAIL] 无法打开串口 {config.GPS_PORT}: {e}")
        print("  请检查：GPS 是否已插入 / config.py 中 GPS_PORT 是否正确 / 驱动是否安装。")
        return

    count      = 0
    start_time = time.time()
    waiting_shown = False

    try:
        while count < n_readings and (time.time() - start_time) < timeout_sec:
            raw = ser.readline()
            if not raw:
                if not waiting_shown:
                    print("  等待卫星信号中...", end="", flush=True)
                    waiting_shown = True
                else:
                    print(".", end="", flush=True)
                continue

            try:
                line = raw.decode("ascii", errors="replace").strip()
            except Exception:
                continue

            if not any(line.startswith(f"${t}") for t in VALID_TYPES):
                continue

            try:
                msg = pynmea2.parse(line)
            except pynmea2.ParseError:
                continue

            if not hasattr(msg, "latitude") or not hasattr(msg, "longitude"):
                continue
            if msg.latitude == 0.0 and msg.longitude == 0.0:
                if not waiting_shown:
                    print("  等待卫星信号中...", end="", flush=True)
                    waiting_shown = True
                else:
                    print(".", end="", flush=True)
                continue

            # 收到有效定位
            if waiting_shown:
                print()   # 换行
                waiting_shown = False

            count += 1
            ts     = beijing_now_str()
            extras = []
            alt  = getattr(msg, "altitude",       None)
            sats = getattr(msg, "num_sats",        None)
            hdop = getattr(msg, "horizontal_dil",  None)
            if alt  is not None: extras.append(f"海拔 {alt} m")
            if sats is not None: extras.append(f"卫星数 {sats}")
            if hdop is not None: extras.append(f"HDOP {hdop}")

            extras_str = "  " + " | ".join(extras) if extras else ""
            print(
                f"  [{count:02d}/{n_readings}] {ts}  "
                f"纬度 {msg.latitude:.6f}°  经度 {msg.longitude:.6f}°"
                f"  ({msg.sentence_type}){extras_str}"
            )

    except KeyboardInterrupt:
        if waiting_shown:
            print()
        print("\n  用户中断 GPS 测试。")
    finally:
        if ser.is_open:
            ser.close()
        print(f"\n  串口 {config.GPS_PORT} 已关闭。")

    print()
    if count == 0:
        print("  [FAIL] 未收到任何有效定位数据。")
        print("         建议：将 GPS 移至室外或窗边，等待冷启动（约 1~3 分钟）。")
    elif count < n_readings:
        print(f"  [WARN] 超时，仅获取 {count}/{n_readings} 次定位。")
    else:
        print(f"  [ OK ] GPS 测试通过，共获取 {count} 次定位。")


# ══════════════════════════════════════════════════════════════════════════════
#  主程序
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 64)
    print("  多模态采集系统 — 采集前设备检测")
    print(f"  {beijing_now_str()}")
    if config.TEST_CAMERAS:
        print("  模式: 仅摄像头测试（config.TEST_CAMERAS = True）")
    else:
        print("  模式: GPS + 摄像头完整测试（config.TEST_CAMERAS = False）")
    print("=" * 64)
    print(f"\n  受试者: {config.PARTICIPANT_ID}")
    print(f"  面部摄像头索引: {config.FACIAL_CAMERA_INDEX}")
    print(f"  交通摄像头索引: {config.TRAFFIC_CAMERA_INDEX}")
    print(f"  录制分辨率: {config.FRAME_WIDTH}×{config.FRAME_HEIGHT} @ {config.FPS}fps")
    if not config.TEST_CAMERAS:
        print(f"  GPS 串口: {config.GPS_PORT}  ({config.GPS_BAUDRATE} baud)")
    print(f"  视频分段: 每 {config.VIDEO_SAVE_INTERVAL_MINUTES} 分钟")
    print(f"  API 查询间隔: {config.GPS_QUERY_INTERVAL} 秒")
    print(f"  事件查询半径: {config.INCIDENT_RADIUS_KM} km")

    # 1. GPS 测试（TEST_CAMERAS = True 时跳过）
    if not config.TEST_CAMERAS:
        test_gps(n_readings=5)

        # GPS 测试结束后询问是否继续摄像头测试
        print()
        while True:
            ans = input("  是否继续进行摄像头测试？[y/n] ").strip().lower()
            if ans in ("y", "n"):
                break
            print("  请输入 y 或 n。")
        if ans == "n":
            print("\n  已跳过摄像头测试，程序退出。")
            print("=" * 64)
            return

    # 2. 摄像头预览
    test_cameras()

    print()
    print("=" * 64)
    print("  设备检测完成！")
    if config.TEST_CAMERAS:
        print("  摄像头测试通过后，可在系统设置中关闭「仅测摄像头」以再测 GPS，")
        print("  或直接运行 collect.py 开始正式采集。")
    else:
        print("  运行 collect.py 开始正式采集。")
    print("=" * 64)


if __name__ == "__main__":
    main()
