"""
collect.py  —  多模态数据采集主脚本
=====================================
功能：
  1. 双摄像头稳定录制（分线程 + 队列缓冲），每 VIDEO_SAVE_INTERVAL_MINUTES 分钟自动分段
  2. GPS 后台持续读取，每 GPS_QUERY_INTERVAL 秒触发 Azure API 查询
  3. Azure 查询：Weather / Traffic Flow Segment / Traffic Incidents (半径可配置)
  4. 全部数据带北京时间戳，写入对应受试者目录

目录结构：
  data/
    facial_video/P{x}/    —— 面部视频  P{x}_1.mp4, P{x}_2.mp4, ...  及对应 _meta.json
    traffic_video/P{x}/   —— 交通视频  同上
    gps/P{x}/             —— GPS 读数  P{x}_gps.jsonl
    azure/P{x}/           —— Azure数据 P{x}_azure.jsonl

依赖：
  pip install opencv-python pyserial pynmea2 requests
"""

import sys
import os
import math
import json
import time
import queue
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

import cv2
import serial
import pynmea2
import requests

# 确保本目录在路径中，可 import config
sys.path.insert(0, str(Path(__file__).parent))
import config

# 强制 UTF-8 输出（避免 Windows 终端 GBK 乱码）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ─── 北京时间工具 ───────────────────────────────────────────────────────────
BEIJING_TZ = timezone(timedelta(hours=8))


def beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)


def beijing_now_str() -> str:
    return beijing_now().strftime("%Y-%m-%d %H:%M:%S")


# ─── 全局停止事件 ────────────────────────────────────────────────────────────
stop_event = threading.Event()

# ─── 摄像头串行开锁（Windows MSMF/DSHOW 不支持并发初始化）────────────────────
# 两个采集线程共用此锁，保证摄像头一个一个打开，避免设备占用冲突
_cam_open_lock = threading.Lock()


# ─── 目录初始化 ──────────────────────────────────────────────────────────────
def setup_dirs(pid: str) -> dict:
    """为受试者创建各类数据目录，返回路径字典。"""
    root = Path(__file__).parent / config.DATA_ROOT
    dirs = {
        "facial":  root / "facial_video" / pid,
        "traffic": root / "traffic_video" / pid,
        "gps":     root / "gps"           / pid,
        "azure":   root / "azure"          / pid,
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


# ══════════════════════════════════════════════════════════════════════════════
#  摄像头录制模块
#  - CameraWorker 为单个摄像头封装两条线程：采集线程 + 写入线程
#  - 采集线程将 (frame, timestamp) 放入有界队列（Queue），队满丢帧以保证实时性
#  - 写入线程从队列取帧写入 VideoWriter，每 VIDEO_SAVE_INTERVAL_MINUTES 分钟分段
# ══════════════════════════════════════════════════════════════════════════════

class CameraWorker:
    """单摄像头录制工作器（采集 + 写入双线程）。"""

    # 队列最大帧数：约 20 秒缓冲（30fps × 20s）
    QUEUE_MAXSIZE = 600

    def __init__(self, cam_index: int, save_dir: Path, pid: str, label: str):
        self.cam_index    = cam_index
        self.save_dir     = save_dir
        self.pid          = pid
        self.label        = label       # "面部摄像头" / "交通摄像头"
        self.frame_queue: queue.Queue = queue.Queue(maxsize=self.QUEUE_MAXSIZE)
        self._cap_thread   = None
        self._write_thread = None
        # 摄像头就绪信号：_capture_loop 打开成功或失败后 set()
        self._ready_event = threading.Event()
        self.opened = False             # 打开成功则 True
        # 所有分段元数据汇总到同一个 JSONL 文件（断点续录时追加）
        self.seg_log_path = save_dir / f"{pid}_segments.jsonl"

    # ── 断点续录：扫描已有视频，返回下一个可用编号 ────────────────────────────

    @staticmethod
    def _next_segment_num(save_dir: Path, pid: str) -> int:
        """
        扫描 save_dir 中已存在的 {pid}_N.mp4 文件，返回 max(N)+1。
        目录为空或没有匹配文件时返回 1（从头开始）。
        """
        import re
        pattern = re.compile(rf"^{re.escape(pid)}_(\d+)\.mp4$")
        max_num = 0
        for f in save_dir.iterdir():
            m = pattern.match(f.name)
            if m:
                max_num = max(max_num, int(m.group(1)))
        return max_num + 1

    # ── 分段日志：追加写入受试者的统一 segments.jsonl ─────────────────────────

    def _append_segment_log(self, record: dict):
        """将一段视频的元数据追加到 {pid}_segments.jsonl（一行一个 JSON 对象）。"""
        try:
            with open(self.seg_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[{self.label}] 分段日志写入失败: {e}")

    # ── 启动 / 等待 ──────────────────────────────────────────────────────────

    def start(self):
        self._cap_thread = threading.Thread(
            target=self._capture_loop,
            name=f"{self.label}_cap",
            daemon=True,
        )
        self._write_thread = threading.Thread(
            target=self._write_loop,
            name=f"{self.label}_write",
            daemon=True,
        )
        self._cap_thread.start()
        self._write_thread.start()

    def join(self, timeout: float = 60.0):
        """等待写入线程退出（最多 timeout 秒）。"""
        if self._write_thread:
            self._write_thread.join(timeout=timeout)

    # ── 采集线程 ─────────────────────────────────────────────────────────────

    def _capture_loop(self):
        # ── 串行打开摄像头（持锁期间其他摄像头等待，避免 MSMF/DSHOW 冲突）──────
        with _cam_open_lock:
            cap = cv2.VideoCapture(self.cam_index, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  config.FRAME_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
            cap.set(cv2.CAP_PROP_FPS,          config.FPS)
            # 让驱动稳定后再判断是否成功（DSHOW 有时需要短暂等待）
            time.sleep(0.5)
            ok = cap.isOpened()

        if not ok:
            print(f"[{self.label}] 错误: 无法打开摄像头 (索引 {self.cam_index})")
            self.opened = False
            self._ready_event.set()   # 通知主线程：本摄像头已处理完（失败）
            # 不调 stop_event.set()，让另一个摄像头继续独立运行
            return

        actual_w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        print(f"[{self.label}] 摄像头 {self.cam_index} 已打开  "
              f"{actual_w}×{actual_h} @ {actual_fps:.1f}fps")
        self.opened = True
        self._ready_event.set()   # 通知主线程：本摄像头已就绪

        fail_count = 0
        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                fail_count += 1
                if fail_count > 50:
                    print(f"[{self.label}] 连续读帧失败，停止采集")
                    stop_event.set()
                    break
                time.sleep(0.02)
                continue
            fail_count = 0

            ts = beijing_now()
            # 左上角时间戳水印（最小字体，绿色）
            cv2.putText(
                frame,
                ts.strftime("%Y-%m-%d %H:%M:%S"),
                (4, 14),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )

            try:
                self.frame_queue.put_nowait((frame, ts))
            except queue.Full:
                pass  # 队列满时丢弃当前帧，保证录制不卡顿

        cap.release()
        print(f"[{self.label}] 摄像头已释放")

    # ── 写入线程 ─────────────────────────────────────────────────────────────

    def _write_loop(self):
        interval_secs = config.VIDEO_SAVE_INTERVAL_MINUTES * 60

        # 断点续录：从已有视频的下一个编号开始
        seg_num   = self._next_segment_num(self.save_dir, self.pid)
        if seg_num > 1:
            print(f"[{self.label}] 检测到已有 {seg_num - 1} 段视频，从第 {seg_num} 段继续录制")

        writer    = None
        meta      = {}    # 当前段运行时状态（不落盘，完成后写入 segments.jsonl）
        seg_start = 0.0

        # ── 内部辅助：保存当前段 → 开启下一段 ──────────────────────────────
        def open_new_segment():
            nonlocal writer, meta, seg_start

            # 保存并关闭上一段
            if writer is not None:
                writer.release()
                writer = None      # 清除引用，防止后续 isOpened() 返回未定义状态
                seg_record = {
                    "segment":     seg_num - 1,
                    "video_file":  meta["video_file"],
                    "start_time":  meta["start_time"],
                    "end_time":    beijing_now_str(),
                    "frame_count": meta["frame_count"],
                }
                self._append_segment_log(seg_record)
                print(f"[{self.label}] 段 {seg_num - 1} 已保存 → {meta['video_file']}")

            # 创建新段视频文件
            filename = f"{self.pid}_{seg_num}.mp4"
            vid_path = str(self.save_dir / filename)

            fourcc     = cv2.VideoWriter_fourcc(*"mp4v")
            new_writer = cv2.VideoWriter(
                vid_path, fourcc, float(config.FPS),
                (config.FRAME_WIDTH, config.FRAME_HEIGHT),
            )
            if not new_writer.isOpened():
                print(f"[{self.label}] 错误: 无法创建视频文件 {vid_path}")
                stop_event.set()
                return

            writer    = new_writer
            meta      = {
                "video_file":  filename,
                "participant": self.pid,
                "camera":      self.label,
                "start_time":  beijing_now_str(),
                "frame_count": 0,
            }
            seg_start = time.time()
            print(f"[{self.label}] 开始录制段 {seg_num}: {filename}  ({meta['start_time']})")

        open_new_segment()  # 启动首段

        while not stop_event.is_set() or not self.frame_queue.empty():
            try:
                # ts 已在采集线程 cap.read() 后立即取得并烧入帧像素，此处无需重复存储
                frame, _ = self.frame_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if writer is None or not writer.isOpened():
                continue

            writer.write(frame)
            meta["frame_count"] = meta.get("frame_count", 0) + 1

            # 检查是否到达分段时间
            if time.time() - seg_start >= interval_secs:
                seg_num += 1
                open_new_segment()

        # 程序退出时保存最后一段
        if writer is not None:
            writer.release()
            if meta:
                seg_record = {
                    "segment":     seg_num,
                    "video_file":  meta["video_file"],
                    "start_time":  meta["start_time"],
                    "end_time":    beijing_now_str(),
                    "frame_count": meta["frame_count"],
                }
                self._append_segment_log(seg_record)
                print(f"[{self.label}] 最终段 {seg_num} 已保存 → {meta['video_file']}")

        print(f"[{self.label}] 写入线程结束")


# ══════════════════════════════════════════════════════════════════════════════
#  GPS 读取模块
#  - 后台线程持续解析 NMEA 语句，更新 _latest
#  - 其他模块通过 get_latest() 线程安全地读取最新定位
#  - 串口断开后自动重连
# ══════════════════════════════════════════════════════════════════════════════

class GpsWorker:
    """BU-353N5 GPS 后台读取器。"""

    def __init__(self):
        self._lock   = threading.Lock()
        self._latest = None   # dict | None
        self._thread = None

    def start(self):
        self._thread = threading.Thread(
            target=self._read_loop, name="gps_read", daemon=True
        )
        self._thread.start()

    def get_latest(self) -> dict | None:
        """线程安全地获取最新定位信息，无定位时返回 None。"""
        with self._lock:
            return dict(self._latest) if self._latest else None

    # ── 串口读取主循环（含自动重连）────────────────────────────────────────

    def _read_loop(self):
        print(f"[GPS] 连接串口 {config.GPS_PORT}（{config.GPS_BAUDRATE} baud）...")
        while not stop_event.is_set():
            try:
                ser = serial.Serial(
                    port=config.GPS_PORT,
                    baudrate=config.GPS_BAUDRATE,
                    timeout=config.GPS_TIMEOUT,
                )
                print(f"[GPS] 串口已打开，等待卫星信号...")
                self._run_serial(ser)
            except serial.SerialException as e:
                print(f"[GPS] 串口错误: {e}，5 秒后重连...")
                time.sleep(5)

    def _run_serial(self, ser: serial.Serial):
        VALID_TYPES = ("GPGGA", "GNGGA", "GPRMC", "GNRMC", "GPGLL", "GNGLL")
        try:
            while not stop_event.is_set():
                try:
                    raw = ser.readline()
                except serial.SerialException as e:
                    print(f"[GPS] 读取中断: {e}")
                    return

                if not raw:
                    continue

                try:
                    line = raw.decode("ascii", errors="replace").strip()
                except Exception:
                    continue

                if not any(line.startswith(f"${t}") for t in VALID_TYPES):
                    continue

                pos = self._parse_nmea(line)
                if pos:
                    with self._lock:
                        self._latest = pos
        finally:
            if ser.is_open:
                ser.close()
            print("[GPS] 串口已关闭")

    @staticmethod
    def _parse_nmea(line: str) -> dict | None:
        try:
            msg = pynmea2.parse(line)
        except pynmea2.ParseError:
            return None
        if not hasattr(msg, "latitude") or not hasattr(msg, "longitude"):
            return None
        if msg.latitude == 0.0 and msg.longitude == 0.0:
            return None
        return {
            "lat":        msg.latitude,
            "lon":        msg.longitude,
            "sentence":   msg.sentence_type,
            "gps_time":   str(getattr(msg, "timestamp", "")),
            "altitude_m": getattr(msg, "altitude",       None),
            "satellites": getattr(msg, "num_sats",        None),
            "hdop":       getattr(msg, "horizontal_dil",  None),
            "speed_kn":   getattr(msg, "spd_over_grnd",  None),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  Azure API 查询工具函数
# ══════════════════════════════════════════════════════════════════════════════

def _safe_get(d: dict, *keys, default=None):
    """安全递归取嵌套字典值，不存在时返回 default。"""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d


def _build_bbox(lat: float, lon: float, radius_km: float) -> tuple:
    """以 (lat, lon) 为中心构建 (min_lat, min_lon, max_lat, max_lon) 边界框。"""
    lat_off = radius_km / 111.0
    lon_off = radius_km / (111.0 * math.cos(math.radians(lat)))
    return (lat - lat_off, lon - lon_off, lat + lat_off, lon + lon_off)


def query_weather(lat: float, lon: float) -> dict:
    """查询 Azure Maps 当前天气条件，返回原始 result 字典。"""
    params = {
        "api-version":      "1.1",
        "query":            f"{lat},{lon}",
        "subscription-key": config.AZURE_MAPS_KEY,
        "unit":             "metric",
    }
    try:
        resp = requests.get(
            config.WEATHER_API_URL, params=params, timeout=config.REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return results[0] if results else {}
    except Exception as e:
        return {"error": str(e)}


def query_traffic_flow(lat: float, lon: float) -> dict:
    """
    查询所在路段实时交通流量（flowSegmentData）。
    从高到低尝试多个 zoom 级别，直至获取到有效数据。
    """
    for zoom in (15, 12, 10, 8, 6):
        params = {
            "api-version":      "1.0",
            "style":            "absolute",
            "zoom":             zoom,
            "query":            f"{lat},{lon}",
            "subscription-key": config.AZURE_MAPS_KEY,
        }
        try:
            resp = requests.get(
                config.TRAFFIC_FLOW_SEGMENT_URL, params=params,
                timeout=config.REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                data = resp.json()
                if "flowSegmentData" in data:
                    return data["flowSegmentData"]
            elif resp.status_code == 400:
                continue  # 该 zoom 无路段，降级重试
        except Exception as e:
            return {"error": str(e)}
    return {"error": "no_coverage_at_any_zoom"}


def query_traffic_incidents(lat: float, lon: float) -> list:
    """
    查询半径 INCIDENT_RADIUS_KM 内的交通事件列表（原始 poi 列表）。
    先获取 trafficmodelid，再查询事件详情。
    """
    bbox = _build_bbox(lat, lon, config.INCIDENT_RADIUS_KM)
    min_lat, min_lon, max_lat, max_lon = bbox
    bb_str = f"{min_lat},{min_lon},{max_lat},{max_lon}"

    # Step 1：获取 trafficmodelid
    lat_c = (min_lat + max_lat) / 2
    lon_c = (min_lon + max_lon) / 2
    lat_h = (max_lat - min_lat) * 1.5
    lon_h = (max_lon - min_lon) * 1.5
    ov_str = f"{lat_c - lat_h},{lon_c - lon_h},{lat_c + lat_h},{lon_c + lon_h}"

    params_vp = {
        "api-version":      "1.0",
        "boundingbox":      bb_str,
        "boundingZoom":     11,
        "overviewBox":      ov_str,
        "overviewZoom":     9,
        "subscription-key": config.AZURE_MAPS_KEY,
    }
    try:
        resp = requests.get(
            config.TRAFFIC_INCIDENT_VIEWPORT, params=params_vp,
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        model_id = _safe_get(
            resp.json(), "viewpResp", "trafficState", "@trafficModelId"
        )
        if model_id is None:
            return []
    except Exception as e:
        return [{"error": f"viewport: {e}"}]

    # Step 2：查询事件详情
    params_det = {
        "api-version":      "1.0",
        "boundingbox":      bb_str,
        "boundingZoom":     11,
        "trafficmodelid":   model_id,
        "subscription-key": config.AZURE_MAPS_KEY,
        "style":            "s1",
    }
    try:
        resp = requests.get(
            config.TRAFFIC_INCIDENT_DETAIL, params=params_det,
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("tm", {}).get("poi", [])
    except Exception as e:
        return [{"error": f"incident_detail: {e}"}]


# ══════════════════════════════════════════════════════════════════════════════
#  Azure API 轮询模块
#  每 GPS_QUERY_INTERVAL 秒：
#    1. 从 GpsWorker 读取最新经纬度
#    2. 保存 GPS 读数到 gps/ 目录
#    3. 并发查询 Weather / Traffic Flow / Traffic Incidents
#    4. 将结果（含时间戳）追加写入 azure/ 目录 JSONL 文件
# ══════════════════════════════════════════════════════════════════════════════

class AzureApiWorker:
    """定时查询 GPS + Azure API，写入 JSONL 文件。"""

    def __init__(
        self,
        gps_worker: GpsWorker,
        gps_dir: Path,
        azure_dir: Path,
        pid: str,
    ):
        self.gps_worker  = gps_worker
        self.gps_path    = gps_dir   / f"{pid}_gps.jsonl"
        self.azure_path  = azure_dir / f"{pid}_azure.jsonl"
        self._thread     = None

    def start(self):
        self._thread = threading.Thread(
            target=self._poll_loop, name="api_poll", daemon=True
        )
        self._thread.start()

    def join(self, timeout: float = 30.0):
        if self._thread:
            self._thread.join(timeout=timeout)

    def _poll_loop(self):
        print(f"[API] 轮询启动（间隔 {config.GPS_QUERY_INTERVAL}s）")
        next_call = time.time()

        while not stop_event.is_set():
            now = time.time()
            if now < next_call:
                time.sleep(0.3)
                continue
            next_call = now + config.GPS_QUERY_INTERVAL

            # ── 读取 GPS ──────────────────────────────────────────────────
            gps = self.gps_worker.get_latest()
            if gps is None:
                print(f"[GPS] {beijing_now_str()}  尚无定位，等待卫星信号...")
                continue

            ts  = beijing_now_str()
            lat = gps["lat"]
            lon = gps["lon"]

            # 保存 GPS 读数
            gps_record = {"timestamp": ts, **gps}
            self._append_jsonl(self.gps_path, gps_record)
            print(f"[GPS] {ts}  纬度 {lat:.6f}°  经度 {lon:.6f}°")

            # ── 并发调用三个 Azure API ────────────────────────────────────
            results = {}

            def call_weather():
                results["weather"] = query_weather(lat, lon)

            def call_flow():
                results["traffic_flow"] = query_traffic_flow(lat, lon)

            def call_incidents():
                results["traffic_incidents"] = query_traffic_incidents(lat, lon)

            threads = [
                threading.Thread(target=call_weather,   daemon=True),
                threading.Thread(target=call_flow,      daemon=True),
                threading.Thread(target=call_incidents, daemon=True),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=config.REQUEST_TIMEOUT + 5)

            # ── 写入 Azure JSONL ──────────────────────────────────────────
            azure_record = {
                "timestamp":          ts,
                "latitude":           lat,
                "longitude":          lon,
                "weather":            results.get("weather",            {}),
                "traffic_flow":       results.get("traffic_flow",       {}),
                "traffic_incidents":  results.get("traffic_incidents",  []),
            }
            self._append_jsonl(self.azure_path, azure_record)
            print(f"[API] {ts}  数据已写入  "
                  f"(天气字段: {'OK' if 'error' not in results.get('weather', {}) else 'ERR'}  "
                  f"交通流: {'OK' if 'error' not in results.get('traffic_flow', {}) else 'ERR'}  "
                  f"事件数: {len(results.get('traffic_incidents', []))})")

        print("[API] 轮询线程结束")

    @staticmethod
    def _append_jsonl(path: Path, record: dict):
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            print(f"[API] 写入失败 {path.name}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  主程序
# ══════════════════════════════════════════════════════════════════════════════

def main():
    pid = config.PARTICIPANT_ID

    print("=" * 64)
    print(f"  多模态数据采集系统")
    print(f"  受试者: {pid}    开始时间: {beijing_now_str()}")
    print("=" * 64)

    # ── 初始化受试者数据目录 ──────────────────────────────────────────────────
    dirs = setup_dirs(pid)
    print(f"  数据目录: {(Path(__file__).parent / config.DATA_ROOT).resolve()}")
    print()

    # ── 启动双摄像头录制 ──────────────────────────────────────────────────────
    facial_cam  = CameraWorker(
        config.FACIAL_CAMERA_INDEX,  dirs["facial"],  pid, "面部摄像头"
    )
    traffic_cam = CameraWorker(
        config.TRAFFIC_CAMERA_INDEX, dirs["traffic"], pid, "交通摄像头"
    )
    facial_cam.start()
    traffic_cam.start()

    # ── 等待两路摄像头各自完成初始化（最多 15 秒）────────────────────────────
    # 使用 _ready_event 而非固定 sleep，确保串行打开完成后再判断
    print("[主程序] 等待摄像头初始化...")
    facial_cam._ready_event.wait(timeout=15.0)
    traffic_cam._ready_event.wait(timeout=15.0)

    cam_ok = []
    for cam in (facial_cam, traffic_cam):
        if cam.opened:
            cam_ok.append(cam.label)
        else:
            print(f"[主程序] 警告: {cam.label} 打开失败，该路视频将不会录制。")

    if not cam_ok:
        print("[主程序] 两路摄像头均无法打开，程序退出。")
        stop_event.set()
        return

    print(f"[主程序] 已就绪的摄像头: {', '.join(cam_ok)}")

    # ── 启动 GPS 读取 ─────────────────────────────────────────────────────────
    gps_worker = GpsWorker()
    gps_worker.start()

    print(f"\n[主程序] 等待 GPS 首次定位（最多 60 秒）...")
    for _ in range(60):
        if gps_worker.get_latest():
            pos = gps_worker.get_latest()
            print(f"[主程序] GPS 定位成功  纬度 {pos['lat']:.6f}°  经度 {pos['lon']:.6f}°")
            break
        if stop_event.is_set():
            break
        time.sleep(1.0)
    else:
        print("[主程序] 警告: 60 秒内未获得 GPS 定位，将在有信号后自动开始 API 查询。")

    # ── 启动 Azure API 轮询 ───────────────────────────────────────────────────
    api_worker = AzureApiWorker(gps_worker, dirs["gps"], dirs["azure"], pid)
    api_worker.start()

    print(f"\n[主程序] 所有模块已启动，按 Ctrl+C 停止采集。\n")
    print(f"  面部视频  → {dirs['facial']}")
    print(f"  交通视频  → {dirs['traffic']}")
    print(f"  GPS 数据  → {dirs['gps']}")
    print(f"  Azure数据 → {dirs['azure']}")
    print()

    # ── 主线程等待中断 ────────────────────────────────────────────────────────
    try:
        while not stop_event.is_set():
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[主程序] 收到 Ctrl+C，正在停止所有模块...")

    stop_event.set()

    # ── 等待各线程退出 ────────────────────────────────────────────────────────
    print("[主程序] 等待视频写入完成（最多 60 秒）...")
    facial_cam.join(timeout=60.0)
    traffic_cam.join(timeout=60.0)
    api_worker.join(timeout=30.0)

    print()
    print("=" * 64)
    print(f"  采集结束    结束时间: {beijing_now_str()}")
    print(f"  数据已保存至: {(Path(__file__).parent / config.DATA_ROOT).resolve()}")
    print("=" * 64)


if __name__ == "__main__":
    main()
