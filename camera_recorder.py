#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
摄像头定时录制脚本
支持罗技 C1000e 4K (C1000S) 摄像头
依赖: pip install opencv-python
"""

import cv2
import time
import datetime
import os
import sys
import subprocess
import json
import ctypes
import queue
import threading

# ==================== 配置参数（按需修改） ====================

# 录制开始时间（北京时间，24小时制）
RECORD_HOUR   = 00
RECORD_MINUTE = 1
RECORD_SECOND = 0

# 录制时长（秒）
RECORD_DURATION = 30  # 1 分钟

# 视频保存目录（默认为本脚本所在文件夹）
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# 录制分辨率（同时作用于录制文件和预览窗口）
# 常用预设: 720p = 1280x720 | 1080p = 1920x1080 | 4K = 3840x2160
RECORD_WIDTH  = 1280
RECORD_HEIGHT = 720

# 强制指定摄像头索引（-1 表示自动选择；若自动选错可手动填 0/1/2/...）
FORCE_CAMERA_INDEX = 1

# ==============================================================

BEIJING_TZ = datetime.timezone(datetime.timedelta(hours=8))


def get_beijing_time() -> datetime.datetime:
    """返回当前北京时间（UTC+8）"""
    return datetime.datetime.now(tz=BEIJING_TZ)


# ---------------------------------------------------------------------------
# 1. 枚举摄像头
# ---------------------------------------------------------------------------

def _query_camera_names_via_powershell() -> list[str]:
    """
    用 PowerShell 查询 Windows PnP 摄像头设备名称列表。
    同时查询 Camera 类和 Image 类（罗技等 USB 摄像头有时归属后者），
    去重后按 InstanceId 排序返回，顺序与 DirectShow 枚举大致一致。
    """
    ps_cmd = (
        "$names = @(); "
        # Camera 类（多数摄像头）
        "Get-PnpDevice -Class Camera -Status OK -ErrorAction SilentlyContinue | "
        "ForEach-Object { $names += $_.FriendlyName }; "
        # Image 类（部分 USB 摄像头、扫描仪等；过滤掉扫描仪）
        "Get-PnpDevice -Class Image  -Status OK -ErrorAction SilentlyContinue | "
        "Where-Object { $_.FriendlyName -notmatch 'scanner|scan' } | "
        "ForEach-Object { if ($names -notcontains $_.FriendlyName) { $names += $_.FriendlyName } }; "
        "$names | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            raw = json.loads(result.stdout.strip())
            if isinstance(raw, str):
                return [raw]
            if isinstance(raw, list):
                return [str(x) for x in raw]
    except Exception as exc:
        print(f"  [警告] PowerShell 查询摄像头名称失败: {exc}")
    return []


def list_cameras() -> list[dict]:
    """
    枚举所有可用摄像头，返回摄像头信息列表。
    每项包含: index, name, width, height, fps
    """
    print("=" * 60)
    print("  正在扫描系统可用摄像头...")
    print("=" * 60)

    names = _query_camera_names_via_powershell()
    if names:
        print("\n[PowerShell] 检测到以下摄像头设备名称：")
        for i, n in enumerate(names):
            print(f"    {i}: {n}")
    else:
        print("\n[警告] 未能通过 PowerShell 获取摄像头名称，将仅显示索引。")

    print("\n[OpenCV] 逐一尝试摄像头索引（0~9）...")
    cameras = []
    for idx in range(10):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            continue
        ret, _ = cap.read()
        if not ret:
            cap.release()
            continue

        w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0 or fps > 120:
            fps = 30.0
        cap.release()

        label = names[idx] if idx < len(names) else f"Camera_{idx}"
        cameras.append({"index": idx, "name": label, "width": w, "height": h, "fps": fps})
        print(f"    索引 {idx}: [{label}]  {w}x{h} @ {fps:.1f}fps")

    print()
    if not cameras:
        print("错误：未检测到任何可用摄像头，请检查连接后重试。")
        sys.exit(1)

    print(f"共检测到 {len(cameras)} 个摄像头。")
    return cameras


# ---------------------------------------------------------------------------
# 2. 选择罗技摄像头
# ---------------------------------------------------------------------------

def select_logitech_camera(cameras: list[dict]) -> dict:
    """
    选择罗技摄像头，三级匹配策略：
      1. 名称中含 logitech / logi / c1000 / brio 等关键词（精确匹配）
      2. 排除已知内置摄像头（integrated / IR camera），取剩余外接设备中最后一个
         （外接 USB 摄像头在 DirectShow 枚举中通常排在内置摄像头之后）
      3. 均无匹配则取最后一个摄像头（外接设备一般索引最大）
    """
    logitech_kw  = ["logitech", "logi", "c1000", "c930", "c920", "brio", "c922", "c925"]
    builtin_kw   = ["integrated", "ir camera", "infrared", "ir "]

    # 策略 1：名称精确匹配
    for cam in cameras:
        if any(kw in cam["name"].lower() for kw in logitech_kw):
            print(f"\n[自动选择] 罗技摄像头（精确匹配）: 索引 {cam['index']} ── {cam['name']}")
            return cam

    # 策略 2：排除内置摄像头，取剩余最后一个（外接 USB）
    externals = [
        cam for cam in cameras
        if not any(kw in cam["name"].lower() for kw in builtin_kw)
    ]
    if externals:
        chosen = externals[-1]
        print(f"\n[自动选择] 未匹配到罗技关键词，已排除内置摄像头，"
              f"选择外接设备: 索引 {chosen['index']} ── {chosen['name']}")
        print("  → 若选择有误，请手动将 FORCE_CAMERA_INDEX 设为正确索引。")
        return chosen

    # 策略 3：全部兜底，取索引最大的
    fallback = cameras[-1]
    print(f"\n[警告] 无法区分摄像头类型，选择最后一个: 索引 {fallback['index']} ── {fallback['name']}")
    return fallback


# ---------------------------------------------------------------------------
# 3. 等待北京时间
# ---------------------------------------------------------------------------

def wait_until_record_time():
    """阻塞等待直到 RECORD_HOUR:RECORD_MINUTE:RECORD_SECOND（北京时间）"""
    target_str = f"{RECORD_HOUR:02d}:{RECORD_MINUTE:02d}:{RECORD_SECOND:02d}"
    print(f"\n等待录制时间 ── 北京时间 {target_str}")
    print("（程序正在计时，请勿关闭窗口。按 Ctrl+C 可取消。）\n")

    while True:
        now = get_beijing_time()
        target = now.replace(
            hour=RECORD_HOUR, minute=RECORD_MINUTE,
            second=RECORD_SECOND, microsecond=0
        )
        if now >= target:
            # 目标时间在今天已过 → 等到明天
            target += datetime.timedelta(days=1)

        diff = (target - now).total_seconds()

        if diff <= 0.5:
            break

        h = int(diff // 3600)
        m = int((diff % 3600) // 60)
        s = int(diff % 60)
        print(
            f"\r  当前北京时间: {now.strftime('%H:%M:%S')}  "
            f"距录制开始: {h:02d}h {m:02d}m {s:02d}s    ",
            end="", flush=True
        )

        sleep_sec = 10 if diff > 60 else 0.5
        time.sleep(sleep_sec)

    print(f"\n\n>>> 开始录制！北京时间: {get_beijing_time().strftime('%Y-%m-%d %H:%M:%S')}")


# ---------------------------------------------------------------------------
# 4. 录制 + 实时预览
# ---------------------------------------------------------------------------

def _put_text_shadow(img, text, pos, font, scale, color, thickness=2):
    """在画面上绘制带阴影的文字，提升可读性。"""
    x, y = pos
    cv2.putText(img, text, (x + 1, y + 1), font, scale, (0, 0, 0), thickness + 1, cv2.LINE_AA)
    cv2.putText(img, text, (x, y), font, scale, color, thickness, cv2.LINE_AA)


def record_with_preview(cam: dict):
    """打开摄像头，等待到录制时间后开始录制并实时预览。"""
    idx = cam["index"]

    # 生成输出文件路径
    ts = get_beijing_time().strftime("%Y%m%d_%H%M%S")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, f"recording_{ts}.mp4")

    print(f"\n录制参数汇总：")
    print(f"  摄像头    : {cam['name']} (索引 {idx})")
    print(f"  录制时长  : {RECORD_DURATION} 秒")
    print(f"  保存路径  : {output_path}")

    # ── 打开摄像头 ──────────────────────────────────────────────
    # 优先用设备名称打开（比索引更可靠，允许驱动正确初始化格式）
    cam_name = cam["name"]
    print(f"  尝试按名称打开: video={cam_name}")
    cap = cv2.VideoCapture(f"video={cam_name}", cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"  [提示] 按名称打开失败，回退到索引 {idx}...")
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"\n错误：无法打开摄像头，请检查连接。")
        sys.exit(1)

    # ★ MJPG 格式必须先设，再设分辨率；按名称打开后驱动才能接受格式切换
    cap.set(cv2.CAP_PROP_FOURCC,       cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  RECORD_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RECORD_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS,          30)
    cap.set(cv2.CAP_PROP_BUFFERSIZE,   1)

    actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc_str = "".join(
        chr((actual_fourcc >> (i * 8)) & 0xFF) for i in range(4)
    ).strip("\x00")
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0 or fps > 120:
        fps = 30.0

    print(f"  请求: {RECORD_WIDTH}x{RECORD_HEIGHT} MJPG @ 30fps")
    print(f"  实际: {actual_w}x{actual_h} {fourcc_str} @ {fps:.1f}fps")

    # ── VideoWriter（独立线程，避免磁盘 IO 阻塞采集帧） ─────────
    file_fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, file_fourcc, fps, (actual_w, actual_h))
    if not out.isOpened():
        print("\n错误：无法创建视频文件，请检查输出路径权限。")
        cap.release()
        sys.exit(1)

    write_q: queue.Queue = queue.Queue(maxsize=120)

    def _writer_loop():
        while True:
            item = write_q.get()
            if item is None:
                break
            out.write(item)
            write_q.task_done()

    writer_thread = threading.Thread(target=_writer_loop, daemon=True)
    writer_thread.start()

    # 预览窗口尺寸
    prev_w = actual_w
    prev_h = actual_h
    font   = cv2.FONT_HERSHEY_SIMPLEX

    print(f"\n录制中... 预览窗口已打开（按 [Q] 可提前停止）")
    print("-" * 60)

    start_ts    = time.time()
    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            print("\n[错误] 无法读取摄像头画面，录制终止。")
            break

        elapsed   = time.time() - start_ts
        remaining = RECORD_DURATION - elapsed

        if remaining <= 0:
            break

        # 写入队列（非阻塞，不影响采集速度）
        try:
            write_q.put_nowait(frame)
            frame_count += 1
        except queue.Full:
            pass  # 队列满时丢帧，优先保证预览流畅

        # ── 预览帧 OSD 叠加 ──────────────────────────────────────
        preview = frame.copy()

        overlay = preview.copy()
        cv2.rectangle(overlay, (0, 0), (prev_w, 50), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.45, preview, 0.55, 0, preview)

        overlay2 = preview.copy()
        cv2.rectangle(overlay2, (0, prev_h - 55), (prev_w, prev_h), (0, 0, 0), -1)
        cv2.addWeighted(overlay2, 0.45, preview, 0.55, 0, preview)

        cv2.circle(preview, (20, 25), 9, (0, 0, 220), -1)
        _put_text_shadow(preview, "REC", (36, 33), font, 0.75, (0, 0, 255))

        now_str = get_beijing_time().strftime("%Y-%m-%d  %H:%M:%S  (BJT)")
        _put_text_shadow(preview, now_str, (prev_w - 340, 33), font, 0.62, (255, 255, 255))

        bar_x1, bar_y1 = 10, prev_h - 12
        bar_x2, bar_y2 = prev_w - 10, prev_h - 4
        bar_fill = int((prev_w - 20) * min(elapsed / RECORD_DURATION, 1.0))
        cv2.rectangle(preview, (bar_x1, bar_y1), (bar_x2, bar_y2), (80, 80, 80), -1)
        cv2.rectangle(preview, (bar_x1, bar_y1), (bar_x1 + bar_fill, bar_y2), (50, 220, 50), -1)

        elapsed_str   = f"Elapsed: {int(elapsed):3d}s"
        remaining_str = f"Remaining: {int(remaining):3d}s"
        _put_text_shadow(preview, elapsed_str,   (10,           prev_h - 18), font, 0.58, (100, 255, 100))
        _put_text_shadow(preview, remaining_str, (prev_w - 200, prev_h - 18), font, 0.58, (100, 220, 255))
        _put_text_shadow(preview, f"{actual_w}x{actual_h} {fourcc_str}", (10, prev_h - 36), font, 0.50, (200, 200, 200))

        cv2.imshow("Camera Recording Preview  (press Q to stop)", preview)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), ord("Q")):
            print("\n[用户操作] 手动停止录制。")
            break

    # ── 等待写入线程完成并释放资源 ──────────────────────────────
    actual_duration = time.time() - start_ts
    write_q.put(None)
    writer_thread.join()
    cap.release()
    out.release()
    cv2.destroyAllWindows()

    # ── 录制完成提示 ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  录制完成！")
    print(f"  实际录制时长 : {actual_duration:.1f} 秒")
    print(f"  总帧数       : {frame_count}")
    print(f"  视频已保存至 : {output_path}")
    print("=" * 60)

    # Windows 系统弹窗提示
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            f"录制完成！\n\n"
            f"时长：{actual_duration:.0f} 秒 / {frame_count} 帧\n\n"
            f"文件已保存至：\n{output_path}",
            "录制完成",
            0x40  # MB_ICONINFORMATION
        )
    except Exception:
        pass  # 非 Windows 环境忽略


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    print("\n" + "=" * 60)
    print("  摄像头定时录制脚本  ──  Logitech C1000e 4K")
    print(f"  当前北京时间 : {get_beijing_time().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  计划开始时间 : {RECORD_HOUR:02d}:{RECORD_MINUTE:02d}:{RECORD_SECOND:02d}（北京时间）")
    print(f"  录制时长     : {RECORD_DURATION} 秒")
    print(f"  保存目录     : {OUTPUT_DIR}")
    print("=" * 60 + "\n")

    # 步骤 1：枚举摄像头
    cameras = list_cameras()

    # 步骤 2：选择罗技摄像头（支持强制指定索引）
    if FORCE_CAMERA_INDEX >= 0:
        matched = [c for c in cameras if c["index"] == FORCE_CAMERA_INDEX]
        if matched:
            selected = matched[0]
            print(f"\n[强制指定] 使用摄像头索引 {FORCE_CAMERA_INDEX}: {selected['name']}")
        else:
            print(f"\n[错误] FORCE_CAMERA_INDEX={FORCE_CAMERA_INDEX} 对应的摄像头不可用，将自动选择。")
            selected = select_logitech_camera(cameras)
    else:
        selected = select_logitech_camera(cameras)

    # 步骤 3：等待录制时间
    wait_until_record_time()

    # 步骤 4：录制 + 预览
    record_with_preview(selected)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[用户取消] 脚本已退出。")
        cv2.destroyAllWindows()
        sys.exit(0)
