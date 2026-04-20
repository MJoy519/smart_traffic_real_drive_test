"""
gui_app.py  —  Smart Traffic 实车采集 图形界面
================================================
界面操作：
  口述指导   —— 显示发车前实验员口述指导内容
  受试者信息 —— 填写受试者基本信息 + 起点情绪自评，建立数据文件夹
  测试设备   —— 运行 test.py（GPS + 摄像头预览）
  开始采集   —— 运行 collect.py；实时计时；状态栏显示当前受试者
  途径点记录 —— 立即保存当前视频段，弹出途径点情绪自评窗口
  ⚙         —— 右上角设置：路径、分段、分辨率、摄像头、GPS、
               仅摄像头模式、Azure 密钥等（写入 settings.json）

线程安全要点：
  * stdout/stderr  通过 Queue 转发，主线程 after(50ms) 轮询写入 Text
  * stdin input()  _GUIStdin.readline() 拦截；after(0)+Event 让主线程弹框再返回
  * 采集停止       collect.stop_event.set()；下次启动前先 clear()
  * 所有 tkinter 操作均在主线程完成
"""

import os
import sys

# ══════════════════════════════════════════════════════════════════════════════
#  后端服务器模式
#  当 EXE / 脚本被以 --backend-mode 参数调用时（GUI 内部生成的子进程），
#  直接启动 FastAPI / uvicorn 并退出，不初始化 Tkinter。
# ══════════════════════════════════════════════════════════════════════════════
if "--backend-mode" in sys.argv:
    from pathlib import Path as _P

    # 解析 key=value 格式的命令行参数
    _kv: dict[str, str] = {}
    for _a in sys.argv[1:]:
        if "=" in _a:
            _k, _v = _a.split("=", 1)
            _kv[_k] = _v

    if _kv.get("--participant-id"):
        os.environ["PARTICIPANT_ID"]    = _kv["--participant-id"]
    if _kv.get("--data-root"):
        os.environ["DATA_ROOT"]         = _kv["--data-root"]
    if _kv.get("--frontend-dist"):
        os.environ["FRONTEND_DIST_DIR"] = _kv["--frontend-dist"]

    # 定位后端目录（frozen EXE → sys._MEIPASS，开发模式 → 脚本旁边）
    _meipass = getattr(sys, "_MEIPASS", None)
    _be_dir  = (_P(_meipass) if _meipass else _P(__file__).parent) / "google_interface" / "backend"

    sys.path.insert(0, str(_be_dir))
    os.chdir(str(_be_dir))

    import uvicorn  # noqa: E402
    uvicorn.run("main:app", host="127.0.0.1", port=17843, log_level="warning")
    sys.exit(0)

# ══════════════════════════════════════════════════════════════════════════════
#  正常 GUI 模式 —— 以下是原有导入
# ══════════════════════════════════════════════════════════════════════════════

import json
import subprocess
import queue
import threading
import time
import webbrowser
from datetime import datetime, timezone, timedelta
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ── 基础路径（兼容 PyInstaller --onefile / --onedir / 直接运行）──────────────
if getattr(sys, "frozen", False):
    _HERE = Path(sys.executable).parent
else:
    _HERE = Path(__file__).parent

os.chdir(_HERE)
sys.path.insert(0, str(_HERE))

# ══════════════════════════════════════════════════════════════════════════════
#  设置持久化（settings.json 保存在 exe / 脚本旁边）
# ══════════════════════════════════════════════════════════════════════════════

_SETTINGS_FILE = _HERE / "settings.json"

_DEFAULTS: dict = {
    "data_root":                    str(_HERE / "data"),
    "video_save_interval_minutes":  1,
    "gps_port":                     "COM7",
    "gps_query_interval":           10,
    "participant_id":               "P1",
    "facial_camera_index":          2,
    "traffic_camera_index":         1,
    "frame_width":                  1280,
    "frame_height":                 720,
    "incident_radius_km":           1.0,
    "test_cameras_only":            False,
    "gps_test_acquire_timeout_sec": 5,
    "gps_use_fixed_location":       True,
    "test_location_lon":            113.9640039313171,
    "test_location_lat":            22.586732532117953,
    "camera_only_mode":             True,   # True → 禁用 API 采集，仅摄像头录制
}


def _load_settings() -> dict:
    s = dict(_DEFAULTS)
    if _SETTINGS_FILE.exists():
        try:
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                s.update(json.load(f))
        except Exception:
            pass
    return s


def _save_settings(s: dict):
    try:
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[GUI] 设置保存失败: {e}")


# ── 导入业务模块（在路径和设置初始化之后）─────────────────────────────────────
import config  # load_dotenv() 在此处执行

# 将 settings.json 中的值应用到 config 模块
_settings = _load_settings()
config.DATA_ROOT                     = _settings["data_root"]
config.VIDEO_SAVE_INTERVAL_MINUTES   = int(_settings["video_save_interval_minutes"])
config.GPS_PORT                      = str(_settings["gps_port"])
config.GPS_QUERY_INTERVAL            = int(_settings["gps_query_interval"])
config.PARTICIPANT_ID                = ""   # 每次启动重置，由用户在"受试者信息"中填写
config.FACIAL_CAMERA_INDEX           = int(_settings["facial_camera_index"])
config.TRAFFIC_CAMERA_INDEX          = int(_settings["traffic_camera_index"])
config.FRAME_WIDTH                   = int(_settings["frame_width"])
config.FRAME_HEIGHT                  = int(_settings["frame_height"])
config.INCIDENT_RADIUS_KM            = float(_settings["incident_radius_km"])
config.TEST_CAMERAS                  = bool(_settings.get("test_cameras_only", False))
config.GPS_TEST_ACQUIRE_TIMEOUT_SEC  = int(_settings.get("gps_test_acquire_timeout_sec", 5))
config.TEST_MODE                     = bool(_settings.get("gps_use_fixed_location", True))
config.TEST_LOCATION_LON             = float(_settings.get("test_location_lon", 113.9640039313171))
config.TEST_LOCATION_LAT             = float(_settings.get("test_location_lat", 22.586732532117953))
config.CAMERA_ONLY_MODE              = bool(_settings.get("camera_only_mode", True))

# Azure 密钥：仅当 settings.json 里已有该键时覆盖（含空字符串）；否则沿用 .env
if "azure_maps_key" in _settings:
    _ak = _settings.get("azure_maps_key")
    if _ak is None:
        config.AZURE_MAPS_KEY = None
    else:
        _t = str(_ak).strip()
        config.AZURE_MAPS_KEY = _t if _t else None

import collect
import test as test_mod


def _snapshot_settings_dict() -> dict:
    """从当前 config 生成完整设置快照，用于写入 settings.json。"""
    return {
        "data_root":                    str(config.DATA_ROOT),
        "video_save_interval_minutes":  int(config.VIDEO_SAVE_INTERVAL_MINUTES),
        "gps_port":                     str(config.GPS_PORT),
        "gps_query_interval":           int(config.GPS_QUERY_INTERVAL),
        "participant_id":               str(config.PARTICIPANT_ID),
        "azure_maps_key":               str(config.AZURE_MAPS_KEY or ""),
        "facial_camera_index":          int(config.FACIAL_CAMERA_INDEX),
        "traffic_camera_index":         int(config.TRAFFIC_CAMERA_INDEX),
        "frame_width":                  int(config.FRAME_WIDTH),
        "frame_height":                 int(config.FRAME_HEIGHT),
        "incident_radius_km":           float(config.INCIDENT_RADIUS_KM),
        "test_cameras_only":            bool(config.TEST_CAMERAS),
        "gps_test_acquire_timeout_sec": int(config.GPS_TEST_ACQUIRE_TIMEOUT_SEC),
        "gps_use_fixed_location":       bool(config.TEST_MODE),
        "test_location_lon":            float(config.TEST_LOCATION_LON),
        "test_location_lat":            float(config.TEST_LOCATION_LAT),
        "camera_only_mode":             bool(config.CAMERA_ONLY_MODE),
    }


# ── 浅色主题 ──────────────────────────────────────────────────────────────────
C_BG       = "#f5f6fa"
C_CARD     = "#ffffff"
C_SURFACE  = "#e8ecf4"
C_BORDER   = "#d0d7e3"
C_ACCENT   = "#1a3a6b"
C_ACCENT_H = "#13285a"
C_GREEN    = "#2f9e44"
C_GREEN_BG = "#ebfbee"
C_RED      = "#c92a2a"
C_RED_BG   = "#fff5f5"
C_YELLOW   = "#e67700"
C_TEXT     = "#1a1a2e"
C_MUTED    = "#6c757d"
C_LOG_BG   = "#1c1c1c"
C_LOG_FG   = "#f0f0f0"
C_LOG_ERR  = "#cd6069"
C_LOG_OK   = "#4ec9b0"
C_LOG_WARN = "#c8a94f"
C_LOG_HEAD = "#9db4d4"

FONT_UI    = ("Microsoft YaHei UI", 10)
FONT_BOLD  = ("Microsoft YaHei UI", 11, "bold")
FONT_BIG   = ("Microsoft YaHei UI", 14, "bold")
FONT_MONO  = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)


# ══════════════════════════════════════════════════════════════════════════════
#  I/O 重定向
# ══════════════════════════════════════════════════════════════════════════════

class _LogQueue:
    def __init__(self, q: "queue.Queue[str]"):
        self._q = q

    def write(self, text: str):
        if text:
            self._q.put(text)

    def flush(self):
        pass

    def isatty(self):
        return False


class _GUIStdin:
    """
    拦截 test.py 中的 input() 调用。
    readline() 在后台线程调用 → after(0) 请求主线程弹框 → Event 等待结果。
    """

    def __init__(self):
        self._result: str = "n"
        self._ready = threading.Event()
        self._app: "App | None" = None

    def readline(self) -> str:
        self._ready.clear()
        self._result = "n"
        if self._app is not None:
            self._app.after(0, self._app._stdin_ask_camera)
        self._ready.wait(timeout=300)
        return self._result + "\n"

    def isatty(self):
        return False


_gui_stdin = _GUIStdin()


# ══════════════════════════════════════════════════════════════════════════════
#  主窗口
# ══════════════════════════════════════════════════════════════════════════════

class App(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Smart Traffic 实车采集")
        self.geometry("920x720")
        self.minsize(760, 540)
        self.configure(bg=C_BG)

        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._task: str | None = None       # None | "test" | "collect"
        self._bg_thread: threading.Thread | None = None

        # 计时相关
        self._collect_start_dt: datetime | None = None
        self._timer_job: str | None = None
        self._collect_elapsed_secs: int = 0

        # 受试者数据目录（"受试者信息"保存后设置）
        self._participant_dir: Path | None = None

        # 途径点计数（GUI 侧追踪，与 collect._waypoint_count 同步）
        self._waypoint_count: int = 0

        # 路线选择子进程（后端 uvicorn + 前端 vite dev server）
        self._route_backend:  "subprocess.Popen | None" = None
        self._route_frontend: "subprocess.Popen | None" = None

        _gui_stdin._app = self
        sys.stdout = _LogQueue(self._log_q)
        sys.stderr = _LogQueue(self._log_q)
        sys.stdin  = _gui_stdin

        self._build_ui()
        self._poll_log()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 界面布局 ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── 顶部标题行 ────────────────────────────────────────────────────────
        title_row = tk.Frame(self, bg=C_BG, pady=14)
        title_row.pack(fill="x", padx=24)

        tk.Label(
            title_row,
            text="Smart Traffic 实车采集",
            font=("Microsoft YaHei UI", 15, "bold"),
            bg=C_BG, fg=C_TEXT,
        ).pack(side="left")

        self._btn_settings = tk.Button(
            title_row, text="⚙",
            font=("Microsoft YaHei UI", 14),
            bg=C_BG, fg=C_MUTED,
            relief="flat", cursor="hand2",
            bd=0, highlightthickness=0,
            padx=6, pady=0,
            activebackground=C_SURFACE,
            activeforeground=C_ACCENT,
            command=self._open_settings,
        )
        self._btn_settings.pack(side="right")

        # ── 受试者状态栏 ──────────────────────────────────────────────────────
        self._status_bar = tk.Frame(self, bg=C_CARD, pady=10,
                                    highlightbackground=C_BORDER,
                                    highlightthickness=1)
        self._status_bar.pack(fill="x", padx=24, pady=(0, 6))

        # 左侧：受试者信息
        left_frame = tk.Frame(self._status_bar, bg=C_CARD)
        left_frame.pack(side="left", fill="y", padx=(18, 0))

        tk.Label(
            left_frame, text="当前受试者：",
            font=FONT_UI, bg=C_CARD, fg=C_MUTED,
        ).pack(side="left")

        self._lbl_pid = tk.Label(
            left_frame, text=config.PARTICIPANT_ID,
            font=FONT_BIG, bg=C_CARD, fg=C_ACCENT,
        )
        self._lbl_pid.pack(side="left", padx=(4, 0))

        self._btn_subject_info = tk.Button(
            left_frame, text="受试者信息",
            font=FONT_SMALL,
            bg=C_SURFACE, fg=C_MUTED,
            relief="flat", cursor="hand2",
            bd=0, highlightthickness=0,
            padx=10, pady=4,
            activebackground=C_BORDER,
            activeforeground=C_TEXT,
            command=self._open_subject_info,
        )
        self._btn_subject_info.pack(side="left", padx=(10, 0))

        # 中间：采集状态
        self._lbl_collecting = tk.Label(
            self._status_bar, text="",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg=C_CARD, fg=C_GREEN,
        )
        self._lbl_collecting.pack(side="left", padx=(20, 0))

        # 右侧：计时信息（采集开始时间 + 已采集时长）
        right_frame = tk.Frame(self._status_bar, bg=C_CARD)
        right_frame.pack(side="right", fill="y", padx=(0, 18))

        self._lbl_start_time = tk.Label(
            right_frame, text="",
            font=FONT_SMALL, bg=C_CARD, fg=C_MUTED,
        )
        self._lbl_start_time.pack(side="left")

        self._lbl_elapsed = tk.Label(
            right_frame, text="",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg=C_CARD, fg=C_ACCENT,
        )
        self._lbl_elapsed.pack(side="left", padx=(4, 0))

        # ── 操作按钮区 ────────────────────────────────────────────────────────
        btn_row = tk.Frame(self, bg=C_BG)
        btn_row.pack(fill="x", padx=24, pady=(0, 12))

        _bkw = dict(
            font=FONT_BOLD, relief="flat", cursor="hand2",
            padx=20, pady=11, bd=0, highlightthickness=0,
        )

        # 口述指导
        self._btn_verbal = tk.Button(
            btn_row, text="口述指导",
            bg=C_SURFACE, fg=C_TEXT,
            activebackground=C_ACCENT, activeforeground="white",
            command=self._open_verbal_guide, **_bkw,
        )
        self._btn_verbal.pack(side="left", padx=(0, 8))

        # 测试设备
        self._btn_test = tk.Button(
            btn_row, text="测试设备",
            bg=C_SURFACE, fg=C_TEXT,
            activebackground=C_ACCENT, activeforeground="white",
            command=self._start_test, **_bkw,
        )
        self._btn_test.pack(side="left", padx=(0, 8))

        # 路线选择
        self._btn_route = tk.Button(
            btn_row, text="路线选择",
            bg=C_SURFACE, fg=C_TEXT,
            activebackground=C_ACCENT, activeforeground="white",
            command=self._open_route_selection, **_bkw,
        )
        self._btn_route.pack(side="left", padx=(0, 8))

        # 开始采集
        self._btn_collect = tk.Button(
            btn_row, text="开始采集",
            bg=C_ACCENT, fg="white",
            activebackground=C_ACCENT_H, activeforeground="white",
            command=self._toggle_collect, **_bkw,
        )
        self._btn_collect.pack(side="left", padx=(0, 8))

        # 途径点记录（采集中才启用）
        self._btn_waypoint = tk.Button(
            btn_row, text="途径点记录",
            bg=C_SURFACE, fg=C_MUTED,
            activebackground=C_YELLOW, activeforeground="white",
            command=self._trigger_waypoint,
            state="disabled", **_bkw,
        )
        self._btn_waypoint.pack(side="left", padx=(0, 8))

        # 清空日志（右侧）
        tk.Button(
            btn_row, text="清空日志",
            bg=C_SURFACE, fg=C_MUTED,
            font=FONT_UI, relief="flat", cursor="hand2",
            activebackground=C_BORDER, activeforeground=C_TEXT,
            padx=14, pady=11, highlightthickness=0,
            command=self._clear_log,
        ).pack(side="right")

        # ── 日志区 ────────────────────────────────────────────────────────────
        log_outer = tk.Frame(self, bg=C_BG)
        log_outer.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        tk.Label(
            log_outer, text="运行日志",
            font=("Microsoft YaHei UI", 9),
            bg=C_BG, fg=C_MUTED,
        ).pack(anchor="w", pady=(0, 4))

        log_inner = tk.Frame(log_outer, bg=C_LOG_BG, bd=0)
        log_inner.pack(fill="both", expand=True)

        self._log_text = tk.Text(
            log_inner, bg=C_LOG_BG, fg=C_LOG_FG,
            font=FONT_MONO, relief="flat", bd=8,
            state="disabled", wrap="char",
            insertbackground=C_LOG_FG,
            selectbackground=C_ACCENT,
        )
        sb = ttk.Scrollbar(log_inner, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log_text.pack(fill="both", expand=True)

        self._log_text.tag_configure("err",  foreground=C_LOG_ERR)
        self._log_text.tag_configure("ok",   foreground=C_LOG_OK)
        self._log_text.tag_configure("warn", foreground=C_LOG_WARN)
        self._log_text.tag_configure("head", foreground=C_LOG_HEAD)

    # ── 日志 ──────────────────────────────────────────────────────────────────

    def _append_log(self, text: str):
        self._log_text.configure(state="normal")
        tl = text.lower()
        if any(k in tl for k in ("error", "[fail]", "错误", "失败", "无法", "异常")):
            tag = "err"
        elif any(k in tl for k in ("[ ok ]", "已打开", "成功", "通过", "已保存", "已就绪")):
            tag = "ok"
        elif any(k in tl for k in ("warn", "[warn]", "警告")):
            tag = "warn"
        elif text.strip().startswith("="):
            tag = "head"
        else:
            tag = ""
        self._log_text.insert("end", text, tag)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _clear_log(self):
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def _poll_log(self):
        try:
            while True:
                self._append_log(self._log_q.get_nowait())
        except queue.Empty:
            pass
        self.after(50, self._poll_log)

    # ── 口述指导 ──────────────────────────────────────────────────────────────

    def _open_verbal_guide(self):
        dlg = tk.Toplevel(self)
        dlg.title("口述指导内容")
        dlg.configure(bg=C_CARD)
        dlg.resizable(True, True)
        dlg.grab_set()
        dlg.transient(self)
        self._center_child(dlg, 740, 560)

        tk.Label(dlg, text="发车前实验员口述", font=FONT_BOLD,
                 bg=C_CARD, fg=C_ACCENT).pack(pady=(16, 10))

        txt_frame = tk.Frame(dlg, bg=C_CARD)
        txt_frame.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        txt = tk.Text(
            txt_frame,
            font=("Microsoft YaHei UI", 10),
            bg="#f8f9ff", fg=C_TEXT,
            relief="flat", bd=0,
            wrap="word", padx=14, pady=12,
            highlightthickness=1,
            highlightbackground=C_BORDER,
        )
        sb_txt = ttk.Scrollbar(txt_frame, command=txt.yview)
        txt.configure(yscrollcommand=sb_txt.set)
        sb_txt.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)

        guide_lines = [
            ('bold', '【实验员逐句朗读以下内容】\n\n'),
            ('normal', '"在接下来的驾驶中，我会在起点、途中三个路段、终点各询问一次您的状态。一共 5 次。"\n\n'),
            ('normal', '"请您全程不用看我，不用思考太久，凭第一直觉直接回答数字。"\n\n'),
            ('normal', '"我会依次问您三个词：\'情绪？\'、\'激动度？\'、\'疲劳度？\'。每个问题您只需回答一个 -3 到 3 之间的数字。"\n\n'),
            ('normal', '"数字的含义是："\n\n'),
            ('label', '  情绪：\n'),
            ('indent', '    -3  非常烦躁  ←→  +3  非常开心，0 是没感觉。\n\n'),
            ('label', '  激动度：\n'),
            ('indent', '    -3  非常平静放松  ←→  +3  非常紧张激动，0 是正常开车。\n\n'),
            ('label', '  疲劳度：\n'),
            ('indent', '    -3  精力极其充沛  ←→  +3  困得必须停车，0 是开始有点无聊。\n\n'),
            ('bold', '"准备好了，我们出发。"'),
        ]

        txt.tag_configure("bold",   font=("Microsoft YaHei UI", 10, "bold"), foreground=C_ACCENT)
        txt.tag_configure("normal", font=("Microsoft YaHei UI", 10))
        txt.tag_configure("label",  font=("Microsoft YaHei UI", 10, "bold"), foreground=C_TEXT)
        txt.tag_configure("indent", font=("Microsoft YaHei UI", 10), foreground=C_MUTED)

        for style, content in guide_lines:
            txt.insert("end", content, style)

        txt.configure(state="disabled")

        tk.Button(
            dlg, text="关闭",
            bg=C_ACCENT, fg="white",
            font=FONT_BOLD, relief="flat", cursor="hand2",
            padx=28, pady=8,
            activebackground=C_ACCENT_H, highlightthickness=0,
            command=dlg.destroy,
        ).pack(pady=(4, 16))

    # ── 受试者信息 ────────────────────────────────────────────────────────────

    def _open_subject_info(self):
        if self._task == "collect":
            messagebox.showwarning("提示", "采集进行中，请先停止采集再修改信息。", parent=self)
            return
        if self._task == "test":
            messagebox.showwarning("提示", "测试进行中，请等待完成后再修改信息。", parent=self)
            return

        # ── 扫描已有受试者文件夹 ──────────────────────────────────────────────
        subjects_root = Path(config.DATA_ROOT) / "subjects"
        existing_pids = []
        if subjects_root.exists():
            existing_pids = sorted([
                d.name for d in subjects_root.iterdir()
                if d.is_dir() and (d / "participant_info.json").exists()
            ])

        # 可变状态容器（加载受试者后更新，供回调引用）
        state = {"start": {}, "end": {}, "waypoints": []}

        dlg = tk.Toplevel(self)
        dlg.title("受试者信息")
        dlg.configure(bg=C_CARD)
        dlg.resizable(True, True)
        dlg.grab_set()
        dlg.transient(self)
        self._center_child(dlg, 780, 640)

        # ── 整体滚动容器 ──────────────────────────────────────────────────────
        canvas  = tk.Canvas(dlg, bg=C_CARD, highlightthickness=0)
        vscroll = ttk.Scrollbar(dlg, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=C_CARD)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _fit_width(e):
            canvas.itemconfig(inner_id, width=e.width)

        def _update_scroll(e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        canvas.bind("<Configure>", _fit_width)
        inner.bind("<Configure>", _update_scroll)

        def _on_wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_wheel)
        dlg.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        PAD = 28
        lbl_kw  = dict(bg=C_CARD, fg=C_TEXT, font=FONT_UI, anchor="w")
        entry_kw = dict(
            relief="flat", bd=0, bg=C_SURFACE, fg=C_TEXT, font=FONT_UI,
            highlightthickness=1, highlightbackground=C_BORDER, highlightcolor=C_ACCENT,
        )
        spin_kw = dict(
            relief="flat", bd=0, bg=C_SURFACE, fg=C_TEXT, font=FONT_UI,
            buttonbackground=C_SURFACE,
            highlightthickness=1, highlightbackground=C_BORDER, highlightcolor=C_ACCENT,
        )

        tk.Label(inner, text="受试者信息", font=FONT_BIG,
                 bg=C_CARD, fg=C_TEXT).pack(pady=(16, 6))

        # ── 基本信息（默认空状态，日期取今天）─────────────────────────────────
        frm_basic = tk.Frame(inner, bg=C_CARD)
        frm_basic.pack(fill="x", padx=PAD)

        row0 = tk.Frame(frm_basic, bg=C_CARD)
        row0.pack(fill="x", pady=4)
        tk.Label(row0, text="测试编号：", **lbl_kw, width=9).pack(side="left")
        # 本次会话已保存过受试者时预填编号；首次启动（仅来自settings.json）保持空
        pid_var    = tk.StringVar(value=config.PARTICIPANT_ID if self._participant_dir is not None else "")
        history_on = tk.BooleanVar(value=False)

        # 固定位置容器，Entry 和 Combobox 在其中切换，容器本身不移动
        pid_slot = tk.Frame(row0, bg=C_CARD)
        pid_slot.pack(side="left")

        pid_entry = tk.Entry(pid_slot, textvariable=pid_var, width=12, **entry_kw)
        pid_entry.pack()

        load_var    = tk.StringVar(value="")
        load_values = existing_pids if existing_pids else []
        load_cb = ttk.Combobox(pid_slot, textvariable=load_var,
                               values=load_values, state="readonly", width=12,
                               font=FONT_UI)

        def _reset_fields():
            """取消历史勾选时，重置所有字段为空/默认值。"""
            pid_var.set("")
            load_var.set("")
            month_var.set(str(now.month))
            day_var.set(str(now.day))
            weather_var.set("晴")
            exp_var.set("")
            state["start"]     = {}
            state["end"]       = {}
            state["waypoints"] = []
            emo_var.set(0)
            aro_var.set(0)
            fat_var.set(0)
            refresh_waypoints()

        def _toggle_history():
            if history_on.get() and existing_pids:
                pid_entry.pack_forget()
                load_cb.pack()
            else:
                load_cb.pack_forget()
                pid_entry.pack()
                _reset_fields()

        tk.Checkbutton(
            row0, text="历史", variable=history_on,
            command=_toggle_history,
            bg=C_CARD, fg=C_TEXT, font=FONT_UI,
            activebackground=C_CARD, selectcolor=C_SURFACE,
        ).pack(side="left", padx=(6, 0))

        tk.Label(row0, text="   日期：2026年", **lbl_kw).pack(side="left")

        now = datetime.now()
        month_var = tk.StringVar(value=str(now.month))
        day_var   = tk.StringVar(value=str(now.day))
        tk.Spinbox(row0, from_=1, to=12, textvariable=month_var, width=3, **spin_kw).pack(side="left")
        tk.Label(row0, text="月", **lbl_kw).pack(side="left")
        tk.Spinbox(row0, from_=1, to=31, textvariable=day_var, width=3, **spin_kw).pack(side="left")
        tk.Label(row0, text="日", **lbl_kw).pack(side="left")

        row1 = tk.Frame(frm_basic, bg=C_CARD)
        row1.pack(fill="x", pady=4)
        tk.Label(row1, text="天气：", **lbl_kw, width=9).pack(side="left")
        weather_var = tk.StringVar(value="晴")
        for w_opt in ("晴", "多云", "阴", "雨"):
            tk.Radiobutton(
                row1, text=w_opt, variable=weather_var, value=w_opt,
                bg=C_CARD, fg=C_TEXT, font=FONT_UI,
                activebackground=C_CARD, selectcolor=C_SURFACE,
            ).pack(side="left", padx=(0, 6))
        tk.Label(row1, text="  实验员：", **lbl_kw).pack(side="left")
        exp_var = tk.StringVar(value="")
        tk.Entry(row1, textvariable=exp_var, width=10, **entry_kw).pack(side="left")

        # ── 情绪自评表 ────────────────────────────────────────────────────────
        tk.Frame(inner, bg=C_BORDER, height=1).pack(fill="x", padx=PAD, pady=(10, 6))
        tk.Label(inner, text="情绪自评记录", font=FONT_BOLD,
                 bg=C_CARD, fg=C_ACCENT).pack(anchor="w", padx=PAD, pady=(0, 4))

        tbl = tk.Frame(inner, bg=C_CARD)
        tbl.pack(fill="x", padx=PAD)

        HDR_BG = "#eef1f8"
        hdr = tk.Frame(tbl, bg=HDR_BG, pady=4)
        hdr.pack(fill="x")
        tk.Label(hdr, text="", width=10, bg=HDR_BG).pack(side="left", padx=(4, 8))
        for col_name in ("情绪（-3 ~ +3）", "激动度（-3 ~ +3）", "疲劳度（-3 ~ +3）"):
            tk.Label(hdr, text=col_name, bg=HDR_BG, fg=C_TEXT,
                     font=("Microsoft YaHei UI", 9, "bold"), anchor="center", width=22).pack(side="left", padx=10)

        # ── 单一操作行：左侧选类型，右侧三个7点选择器 ────────────────────────
        rating_row = tk.Frame(tbl, bg=C_CARD, pady=6)
        rating_row.pack(fill="x")

        type_frame = tk.Frame(rating_row, bg=C_CARD)
        type_frame.pack(side="left", padx=(4, 8))
        record_type_var = tk.StringVar(value="起始点")
        for rtype in ("起始点", "终点"):
            tk.Radiobutton(
                type_frame, text=rtype, variable=record_type_var, value=rtype,
                bg=C_CARD, fg=C_TEXT, font=FONT_UI,
                activebackground=C_CARD, selectcolor=C_SURFACE,
            ).pack(anchor="w")

        emo_frm, emo_var = self._make_7pt_selector(rating_row, C_CARD, 0)
        emo_frm.pack(side="left", padx=10)
        aro_frm, aro_var = self._make_7pt_selector(rating_row, C_CARD, 0)
        aro_frm.pack(side="left", padx=10)
        fat_frm, fat_var = self._make_7pt_selector(rating_row, C_CARD, 0)
        fat_frm.pack(side="left", padx=10)

        def on_type_change(*_):
            d = state["start"] if record_type_var.get() == "起始点" else state["end"]
            emo_var.set(d.get("emotion", 0))
            aro_var.set(d.get("arousal", 0))
            fat_var.set(d.get("fatigue", 0))

        record_type_var.trace_add("write", on_type_change)

        # ── 途径点记录（只读展示，可刷新）───────────────────────────────────
        tk.Frame(inner, bg=C_BORDER, height=1).pack(fill="x", padx=PAD, pady=(8, 4))
        tk.Label(
            inner, text="途径点记录",
            font=("Microsoft YaHei UI", 9, "bold"), bg=C_CARD, fg=C_TEXT,
        ).pack(anchor="w", padx=PAD, pady=(0, 4))

        wp_frame = tk.Frame(inner, bg="#f8f9ff",
                            highlightbackground=C_BORDER, highlightthickness=1)
        wp_frame.pack(fill="x", padx=PAD, pady=(0, 4))

        def _sign(v):
            return f"+{v}" if v > 0 else str(v)

        def refresh_waypoints():
            for w in wp_frame.winfo_children():
                w.destroy()
            waypoints = state["waypoints"]
            if waypoints:
                for wp in waypoints:
                    wp_id = wp.get("waypoint_id", "?")
                    ts    = wp.get("timestamp", "")
                    txt = (
                        f"  途径点 {wp_id}   "
                        f"情绪 {_sign(wp.get('emotion', 0))}   "
                        f"激动度 {_sign(wp.get('arousal', 0))}   "
                        f"疲劳度 {_sign(wp.get('fatigue', 0))}   "
                        f"{ts}"
                    )
                    tk.Label(wp_frame, text=txt, font=FONT_SMALL,
                             bg="#f8f9ff", fg=C_TEXT, anchor="w",
                             pady=4).pack(fill="x")
            else:
                tk.Label(wp_frame, text="  （暂无途径点记录）",
                         font=FONT_SMALL, bg="#f8f9ff", fg=C_MUTED,
                         pady=6).pack(fill="x")

        refresh_waypoints()

        # ── 加载受试者回调 ────────────────────────────────────────────────────
        def on_load_subject(e=None):
            sel = load_var.get()
            if not sel or sel.startswith("（"):
                return
            sel_dir = subjects_root / sel
            info, sr = {}, {}
            try:
                with open(sel_dir / "participant_info.json", "r", encoding="utf-8") as f:
                    info = json.load(f)
            except Exception:
                pass
            try:
                with open(sel_dir / "self_report.json", "r", encoding="utf-8") as f:
                    sr = json.load(f)
            except Exception:
                pass

            # 更新基本信息字段
            pid_var.set(info.get("participant_id", sel))
            _date_str = info.get("date", "")
            try:
                _parts = _date_str.replace("年", "|").replace("月", "|").replace("日", "").split("|")
                month_var.set(str(int(_parts[1])) if len(_parts) > 1 else str(now.month))
                day_var.set(str(int(_parts[2]))   if len(_parts) > 2 else str(now.day))
            except Exception:
                month_var.set(str(now.month))
                day_var.set(str(now.day))
            weather_var.set(info.get("weather", "晴"))
            exp_var.set(info.get("experimenter", ""))

            # 更新情绪自评状态
            state["start"]     = sr.get("start",     {})
            state["end"]       = sr.get("end",       {})
            state["waypoints"] = sr.get("waypoints", [])

            # 按当前记录类型回填选择器
            on_type_change()
            refresh_waypoints()

        load_cb.bind("<<ComboboxSelected>>", on_load_subject)

        # ── 若本次会话已保存过受试者，自动加载其数据（首次启动不触发）────────
        _cur_pid = config.PARTICIPANT_ID if self._participant_dir is not None else ""
        if _cur_pid:
            _cur_dir = subjects_root / _cur_pid
            if _cur_dir.exists():
                _info, _sr = {}, {}
                try:
                    with open(_cur_dir / "participant_info.json", "r", encoding="utf-8") as _f:
                        _info = json.load(_f)
                except Exception:
                    pass
                try:
                    with open(_cur_dir / "self_report.json", "r", encoding="utf-8") as _f:
                        _sr = json.load(_f)
                except Exception:
                    pass
                # 回填日期
                _date_str = _info.get("date", "")
                try:
                    _parts = _date_str.replace("年", "|").replace("月", "|").replace("日", "").split("|")
                    month_var.set(str(int(_parts[1])) if len(_parts) > 1 else str(now.month))
                    day_var.set(str(int(_parts[2]))   if len(_parts) > 2 else str(now.day))
                except Exception:
                    pass
                weather_var.set(_info.get("weather", "晴"))
                exp_var.set(_info.get("experimenter", ""))
                # 回填情绪自评状态
                state["start"]     = _sr.get("start",     {})
                state["end"]       = _sr.get("end",       {})
                state["waypoints"] = _sr.get("waypoints", [])
                on_type_change()
                refresh_waypoints()

        # ── 保存 / 取消 ───────────────────────────────────────────────────────
        tk.Frame(inner, bg=C_BORDER, height=1).pack(fill="x", padx=PAD, pady=(12, 8))

        btn_frm = tk.Frame(inner, bg=C_CARD)
        btn_frm.pack(pady=(0, 20))

        def on_save():
            pid_new = pid_var.get().strip()
            if not pid_new:
                messagebox.showwarning("格式错误", "测试编号不能为空。", parent=dlg)
                return
            try:
                month = int(month_var.get())
                day   = int(day_var.get())
                if not (1 <= month <= 12 and 1 <= day <= 31):
                    raise ValueError
            except (ValueError, TypeError):
                messagebox.showwarning("格式错误", "请输入有效的月份（1-12）和日期（1-31）。", parent=dlg)
                return

            config.PARTICIPANT_ID = pid_new
            self._lbl_pid.configure(text=pid_new)
            _save_settings(_snapshot_settings_dict())

            subj_dir = Path(config.DATA_ROOT) / "subjects" / pid_new
            subj_dir.mkdir(parents=True, exist_ok=True)
            self._participant_dir = subj_dir

            info = {
                "participant_id": pid_new,
                "date":           f"2026年{month}月{day}日",
                "weather":        weather_var.get(),
                "experimenter":   exp_var.get().strip(),
                "updated_at":     self._now(),
            }
            with open(subj_dir / "participant_info.json", "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=2)

            sr_path = subj_dir / "self_report.json"
            if sr_path.exists():
                with open(sr_path, "r", encoding="utf-8") as f:
                    sr_data = json.load(f)
            else:
                sr_data = {"participant_id": pid_new, "waypoints": []}

            sr_data["participant_id"] = pid_new
            # 仅保存当前选中类型（另一类型数据在文件中保持不变）
            sr_key = "start" if record_type_var.get() == "起始点" else "end"
            sr_data[sr_key] = {
                "emotion":   emo_var.get(),
                "arousal":   aro_var.get(),
                "fatigue":   fat_var.get(),
                "timestamp": self._now(),
            }
            with open(sr_path, "w", encoding="utf-8") as f:
                json.dump(sr_data, f, ensure_ascii=False, indent=2)

            dlg.destroy()
            messagebox.showinfo("已保存", "受试者信息已保存。", parent=self)

        tk.Button(
            btn_frm, text="保存", command=on_save,
            bg=C_ACCENT, fg="white",
            font=FONT_BOLD, relief="flat", cursor="hand2",
            padx=32, pady=8,
            activebackground=C_ACCENT_H, highlightthickness=0,
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            btn_frm, text="取消", command=dlg.destroy,
            bg=C_SURFACE, fg=C_MUTED,
            font=FONT_BOLD, relief="flat", cursor="hand2",
            padx=20, pady=8, highlightthickness=0,
            activebackground=C_BORDER,
        ).pack(side="left")

    # ── 设置面板 ──────────────────────────────────────────────────────────────

    def _open_settings(self):
        if self._task == "collect":
            messagebox.showwarning("提示", "采集进行中，请先停止采集再修改设置。", parent=self)
            return

        dlg = tk.Toplevel(self)
        dlg.title("系统设置")
        dlg.configure(bg=C_CARD)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self)
        self._center_child(dlg, 800, 740)

        tk.Label(dlg, text="系统设置", font=FONT_BIG,
                 bg=C_CARD, fg=C_TEXT).pack(pady=(14, 8))

        frm = tk.Frame(dlg, bg=C_CARD)
        frm.pack(fill="both", expand=True, padx=24, pady=(0, 4))

        lbl_kw   = dict(bg=C_CARD, fg=C_TEXT, font=FONT_UI, anchor="w")
        entry_kw = dict(
            relief="flat", bd=0,
            bg=C_SURFACE, fg=C_TEXT, font=FONT_UI,
            highlightthickness=1,
            highlightbackground=C_BORDER,
            highlightcolor=C_ACCENT,
        )

        def add_row(parent, row, label, widget_factory):
            tk.Label(parent, text=label, width=18, **lbl_kw).grid(
                row=row, column=0, sticky="nw", pady=5)
            widget_factory(parent, row)

        def spin_kw():
            return dict(
                relief="flat", bd=0,
                bg=C_SURFACE, fg=C_TEXT, font=FONT_UI,
                buttonbackground=C_SURFACE,
                highlightthickness=1,
                highlightbackground=C_BORDER,
                highlightcolor=C_ACCENT,
                width=8,
            )

        # 0. 数据存储路径
        data_var = tk.StringVar(value=config.DATA_ROOT)

        def make_data_row(p, r):
            tk.Entry(p, textvariable=data_var, width=42, **entry_kw).grid(
                row=r, column=1, sticky="ew", padx=(0, 6))
            tk.Button(
                p, text="浏览", font=FONT_SMALL,
                bg=C_SURFACE, fg=C_MUTED, relief="flat", cursor="hand2",
                padx=8, pady=4, highlightthickness=0,
                activebackground=C_BORDER,
                command=lambda: _browse_dir(data_var),
            ).grid(row=r, column=2)

        def _browse_dir(var):
            d = filedialog.askdirectory(parent=dlg, title="选择数据存储目录",
                                        initialdir=var.get())
            if d:
                var.set(d)

        add_row(frm, 0, "数据存储路径：", make_data_row)

        # 1. 视频分段时长
        video_var = tk.StringVar(value=str(config.VIDEO_SAVE_INTERVAL_MINUTES))

        def make_video_row(p, r):
            tk.Spinbox(p, from_=1, to=120, textvariable=video_var, **spin_kw()).grid(
                row=r, column=1, sticky="w")
            tk.Label(p, text="分钟/段", **lbl_kw).grid(row=r, column=2, sticky="w", padx=4)

        add_row(frm, 1, "视频分段时长：", make_video_row)

        # 2. 视频分辨率
        _RES_OPTIONS = (
            ("360p（640×360）",   640,  360),
            ("720p（1280×720）",  1280, 720),
            ("1080p（1920×1080）", 1920, 1080),
        )

        def _res_label_from_config() -> str:
            w, h = config.FRAME_WIDTH, config.FRAME_HEIGHT
            for lbl, ww, hh in _RES_OPTIONS:
                if (ww, hh) == (w, h):
                    return lbl
            return "720p（1280×720）"

        res_var = tk.StringVar(value=_res_label_from_config())

        def make_res_row(p, r):
            sub = tk.Frame(p, bg=C_CARD)
            sub.grid(row=r, column=1, columnspan=2, sticky="w")
            ttk.Combobox(
                sub, textvariable=res_var,
                values=[x[0] for x in _RES_OPTIONS],
                state="readonly", width=22, font=FONT_UI,
            ).pack(side="left")

        add_row(frm, 2, "视频分辨率：", make_res_row)

        # 3 / 4. 摄像头索引
        facial_var  = tk.StringVar(value=str(config.FACIAL_CAMERA_INDEX))
        traffic_var = tk.StringVar(value=str(config.TRAFFIC_CAMERA_INDEX))

        def make_facial_row(p, r):
            tk.Spinbox(p, from_=0, to=15, textvariable=facial_var, **spin_kw()).grid(
                row=r, column=1, sticky="w")
            tk.Label(p, text="默认为0", **lbl_kw).grid(row=r, column=2, sticky="w", padx=4)

        def make_traffic_row(p, r):
            tk.Spinbox(p, from_=0, to=15, textvariable=traffic_var, **spin_kw()).grid(
                row=r, column=1, sticky="w")
            tk.Label(p, text="默认为1", **lbl_kw).grid(row=r, column=2, sticky="w", padx=4)

        add_row(frm, 3, "面部摄像头索引：", make_facial_row)
        add_row(frm, 4, "交通摄像头索引：", make_traffic_row)

        # 5. GPS 串口号
        port_var = tk.StringVar(value=config.GPS_PORT)

        def make_port_row(p, r):
            tk.Entry(p, textvariable=port_var, width=12, **entry_kw).grid(
                row=r, column=1, sticky="w")

        add_row(frm, 5, "GPS 串口号：", make_port_row)

        # 6. 数据采集间隔
        gps_var = tk.StringVar(value=str(config.GPS_QUERY_INTERVAL))

        def make_gps_row(p, r):
            tk.Spinbox(p, from_=5, to=600, textvariable=gps_var, **spin_kw()).grid(
                row=r, column=1, sticky="w")
            tk.Label(p, text="秒/次", **lbl_kw).grid(row=r, column=2, sticky="w", padx=4)

        add_row(frm, 6, "数据采集间隔：", make_gps_row)

        # 7. 采集定位模式
        _LOC_LABELS = ("GPS 硬件实时定位", "固定经纬度（调试用）")
        loc_mode_var = tk.StringVar(
            value=_LOC_LABELS[1] if config.TEST_MODE else _LOC_LABELS[0]
        )
        lon_var = tk.StringVar(value=str(config.TEST_LOCATION_LON))
        lat_var = tk.StringVar(value=str(config.TEST_LOCATION_LAT))

        def make_loc_mode_row(p, r):
            sub = tk.Frame(p, bg=C_CARD)
            sub.grid(row=r, column=1, columnspan=2, sticky="w")
            ttk.Combobox(
                sub, textvariable=loc_mode_var,
                values=list(_LOC_LABELS),
                state="readonly", width=24, font=FONT_UI,
            ).pack(side="left")

        add_row(frm, 7, "采集定位模式：", make_loc_mode_row)

        _lonlat_entries = []

        def make_lon_row(p, r):
            e = tk.Entry(p, textvariable=lon_var, width=20, **entry_kw)
            e.grid(row=r, column=1, sticky="w")
            _lonlat_entries.append(e)
            tk.Label(p, text="度（东经为正）", **lbl_kw).grid(row=r, column=2, sticky="w", padx=4)

        def make_lat_row(p, r):
            e = tk.Entry(p, textvariable=lat_var, width=20, **entry_kw)
            e.grid(row=r, column=1, sticky="w")
            _lonlat_entries.append(e)
            tk.Label(p, text="度（北纬为正）", **lbl_kw).grid(row=r, column=2, sticky="w", padx=4)

        add_row(frm, 8, "固定点经度：", make_lon_row)
        add_row(frm, 9, "固定点纬度：", make_lat_row)

        def _sync_lonlat_entries(*_):
            fixed = loc_mode_var.get() == _LOC_LABELS[1]
            st = "normal" if fixed else "disabled"
            for w in _lonlat_entries:
                w.configure(state=st)

        loc_mode_var.trace_add("write", _sync_lonlat_entries)
        dlg.after(50, _sync_lonlat_entries)

        # 10. 设备测试
        test_only_var    = tk.BooleanVar(value=bool(config.TEST_CAMERAS))
        gps_test_to_var  = tk.StringVar(value=str(config.GPS_TEST_ACQUIRE_TIMEOUT_SEC))

        def make_test_only_row(p, r):
            tk.Checkbutton(
                p, text="仅测摄像头（跳过 GPS 串口测试）",
                variable=test_only_var,
                bg=C_CARD, fg=C_TEXT, activebackground=C_CARD,
                selectcolor=C_SURFACE, font=FONT_UI, anchor="w",
            ).grid(row=r, column=1, columnspan=2, sticky="w")

        def make_gps_test_to_row(p, r):
            tk.Spinbox(p, from_=3, to=600, textvariable=gps_test_to_var, **spin_kw()).grid(
                row=r, column=1, sticky="w")
            tk.Label(p, text="秒", **lbl_kw).grid(row=r, column=2, sticky="w", padx=4)

        add_row(frm, 10, "设备测试：",        make_test_only_row)
        add_row(frm, 11, "GPS 测试定位超时：", make_gps_test_to_row)

        # 12. 交通事件查询半径
        radius_var = tk.StringVar(value=str(config.INCIDENT_RADIUS_KM))

        def make_radius_row(p, r):
            tk.Entry(p, textvariable=radius_var, width=10, **entry_kw).grid(
                row=r, column=1, sticky="w")
            tk.Label(p, text="km", **lbl_kw).grid(row=r, column=2, sticky="w", padx=4)

        add_row(frm, 12, "交通事件查询半径：", make_radius_row)

        # 13. Azure API 密钥
        api_var = tk.StringVar(value=str(config.AZURE_MAPS_KEY or ""))

        def make_api_row(p, r):
            tk.Entry(
                p, textvariable=api_var, width=42, show="*", **entry_kw,
            ).grid(row=r, column=1, columnspan=2, sticky="ew")

        add_row(frm, 13, "Azure API 密钥：", make_api_row)

        # 14. 仅摄像头模式（禁用 API 采集）
        cam_only_var = tk.BooleanVar(value=bool(config.CAMERA_ONLY_MODE))

        def make_cam_only_row(p, r):
            tk.Checkbutton(
                p,
                text="仅摄像头采集（勾选后禁用 GPS / Azure API，调试与正式采集均生效）",
                variable=cam_only_var,
                bg=C_CARD, fg=C_TEXT, activebackground=C_CARD,
                selectcolor=C_SURFACE, font=FONT_UI, anchor="w",
            ).grid(row=r, column=1, columnspan=2, sticky="w")

        add_row(frm, 14, "采集模式：", make_cam_only_row)

        frm.columnconfigure(1, weight=1)

        # ── 保存 / 取消 ───────────────────────────────────────────────────────
        btn_row = tk.Frame(dlg, bg=C_CARD)
        btn_row.pack(pady=(12, 16))

        def on_save():
            video_val = video_var.get().strip()
            gps_val   = gps_var.get().strip()
            if not video_val.isdigit() or int(video_val) < 1:
                messagebox.showwarning("格式错误", "视频分段时长须为正整数（分钟）。", parent=dlg)
                return
            if not gps_val.isdigit() or int(gps_val) < 1:
                messagebox.showwarning("格式错误", "数据采集间隔须为正整数（秒）。", parent=dlg)
                return
            sel = res_var.get().strip()
            fw = fh = None
            for lbl, ww, hh in _RES_OPTIONS:
                if lbl == sel:
                    fw, fh = ww, hh
                    break
            if fw is None:
                messagebox.showwarning("格式错误", "请选择视频分辨率（360p / 720p / 1080p）。", parent=dlg)
                return
            try:
                fi = int(facial_var.get().strip())
                ti = int(traffic_var.get().strip())
            except ValueError:
                messagebox.showwarning("格式错误", "摄像头索引须为整数。", parent=dlg)
                return
            if not (0 <= fi <= 15 and 0 <= ti <= 15):
                messagebox.showwarning("格式错误", "摄像头索引范围 0–15。", parent=dlg)
                return
            try:
                ir = float(str(radius_var.get().strip()).replace(",", "."))
            except ValueError:
                messagebox.showwarning("格式错误", "交通事件查询半径须为数字（km）。", parent=dlg)
                return
            if not (0.1 <= ir <= 200.0):
                messagebox.showwarning("格式错误", "查询半径建议 0.1–200 km。", parent=dlg)
                return

            port = port_var.get().strip()
            if not port:
                messagebox.showwarning("格式错误", "GPS 串口号不能为空。", parent=dlg)
                return
            data_path = data_var.get().strip()
            if not data_path:
                messagebox.showwarning("格式错误", "数据存储路径不能为空。", parent=dlg)
                return

            api_raw = api_var.get().strip()
            config.AZURE_MAPS_KEY = api_raw if api_raw else None

            use_fixed = loc_mode_var.get() == _LOC_LABELS[1]
            config.TEST_MODE = use_fixed
            try:
                tlon = float(str(lon_var.get().strip()).replace(",", "."))
                tlat = float(str(lat_var.get().strip()).replace(",", "."))
            except ValueError:
                messagebox.showwarning("格式错误", "固定点经度、纬度须为数字。", parent=dlg)
                return
            if use_fixed:
                if not (-180.0 <= tlon <= 180.0 and -90.0 <= tlat <= 90.0):
                    messagebox.showwarning("格式错误", "经度 ∈ [-180,180]，纬度 ∈ [-90,90]。", parent=dlg)
                    return
            config.TEST_LOCATION_LON = tlon
            config.TEST_LOCATION_LAT = tlat

            config.TEST_CAMERAS = bool(test_only_var.get())
            gto = gps_test_to_var.get().strip()
            if not gto.isdigit() or int(gto) < 3:
                messagebox.showwarning("格式错误", "GPS 测试定位超时须为不小于 3 的整数（秒）。", parent=dlg)
                return
            config.GPS_TEST_ACQUIRE_TIMEOUT_SEC = int(gto)

            config.DATA_ROOT                   = data_path
            config.VIDEO_SAVE_INTERVAL_MINUTES = int(video_val)
            config.GPS_PORT                    = port
            config.GPS_QUERY_INTERVAL          = int(gps_val)
            config.FACIAL_CAMERA_INDEX         = fi
            config.TRAFFIC_CAMERA_INDEX        = ti
            config.FRAME_WIDTH                 = fw
            config.FRAME_HEIGHT                = fh
            config.INCIDENT_RADIUS_KM          = ir
            config.CAMERA_ONLY_MODE            = bool(cam_only_var.get())

            _save_settings(_snapshot_settings_dict())
            dlg.destroy()
            messagebox.showinfo(
                "已保存",
                "设置已写入与程序同目录的 settings.json，下次打开将自动加载。",
                parent=self,
            )

        tk.Button(
            btn_row, text="保存", command=on_save,
            bg=C_ACCENT, fg="white",
            font=FONT_BOLD, relief="flat", cursor="hand2",
            padx=28, pady=8,
            activebackground=C_ACCENT_H, highlightthickness=0,
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            btn_row, text="取消", command=dlg.destroy,
            bg=C_SURFACE, fg=C_MUTED,
            font=FONT_BOLD, relief="flat", cursor="hand2",
            padx=20, pady=8, highlightthickness=0,
            activebackground=C_BORDER,
        ).pack(side="left")

    # ── 计时器 ────────────────────────────────────────────────────────────────

    def _start_collect_timer(self):
        tz_bj = timezone(timedelta(hours=8))
        self._collect_start_dt     = datetime.now(tz_bj)
        self._collect_elapsed_secs = 0
        start_str = self._collect_start_dt.strftime("%H:%M:%S")
        self._lbl_start_time.configure(text=f"开始于 {start_str}  |  ")
        self._lbl_elapsed.configure(text="00:00:00")
        self._timer_job = self.after(1000, self._tick_timer)

    def _tick_timer(self):
        self._collect_elapsed_secs += 1
        h = self._collect_elapsed_secs // 3600
        m = (self._collect_elapsed_secs % 3600) // 60
        s = self._collect_elapsed_secs % 60
        self._lbl_elapsed.configure(text=f"{h:02d}:{m:02d}:{s:02d}")
        self._timer_job = self.after(1000, self._tick_timer)

    def _stop_collect_timer(self):
        if self._timer_job:
            self.after_cancel(self._timer_job)
            self._timer_job = None

        # 保存采集时间到受试者文件夹
        if self._participant_dir and self._collect_start_dt:
            tz_bj  = timezone(timedelta(hours=8))
            end_dt = datetime.now(tz_bj)
            meta = {
                "start_time":       self._collect_start_dt.strftime("%H:%M:%S"),
                "end_time":         end_dt.strftime("%H:%M:%S"),
                "duration_seconds": self._collect_elapsed_secs,
                "duration_str":     self._lbl_elapsed.cget("text"),
                "date":             self._collect_start_dt.strftime("%Y-%m-%d"),
            }
            try:
                ct_path = self._participant_dir / "collection_time.json"
                # 读取已有记录（兼容旧格式：单对象或列表）
                records = []
                if ct_path.exists():
                    try:
                        with open(ct_path, "r", encoding="utf-8") as f:
                            existing = json.load(f)
                        if isinstance(existing, list):
                            records = existing
                        elif isinstance(existing, dict):
                            records = [existing]
                    except Exception:
                        records = []
                records.append(meta)
                with open(ct_path, "w", encoding="utf-8") as f:
                    json.dump(records, f, ensure_ascii=False, indent=2)
                print(f"[GUI] 采集时长已保存（共 {len(records)} 条）→ {ct_path}\n")
            except Exception as e:
                print(f"[GUI] 采集时长保存失败: {e}\n")

        self._lbl_start_time.configure(text="")
        self._lbl_elapsed.configure(text="")
        self._collect_start_dt = None

    # ── 途径点记录 ────────────────────────────────────────────────────────────

    def _trigger_waypoint(self):
        if self._task != "collect":
            return

        self._waypoint_count += 1
        wp = self._waypoint_count

        # 通知 collect.py 立即保存当前视频段（途径点编号待填写后才打印）
        collect.trigger_waypoint()
        self._append_log(
            f"\n[GUI] ● 视频分段已保存，新段开始录制。\n"
        )

        # 稍后弹出自评窗口（让日志先刷新）
        self.after(150, lambda: self._open_waypoint_dialog(wp))

    def _open_waypoint_dialog(self, waypoint_id: int):
        dlg = tk.Toplevel(self)
        dlg.title(f"途径点 {waypoint_id} — 情绪自评")
        dlg.configure(bg=C_CARD)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self)
        self._center_child(dlg, 620, 340)

        tk.Label(dlg, text="途径点情绪自评", font=FONT_BIG,
                 bg=C_CARD, fg=C_ACCENT).pack(pady=(16, 4))

        # 途径点编号行（防误触：默认锁定）
        wp_row = tk.Frame(dlg, bg=C_CARD)
        wp_row.pack(pady=(0, 6))

        tk.Label(wp_row, text="途径点编号：",
                 font=FONT_UI, bg=C_CARD, fg=C_TEXT).pack(side="left")

        wp_id_var = tk.IntVar(value=waypoint_id)
        wp_spin = tk.Spinbox(
            wp_row, from_=1, to=99, textvariable=wp_id_var,
            relief="flat", bd=0, bg=C_SURFACE, fg=C_ACCENT,
            font=("Microsoft YaHei UI", 12, "bold"),
            buttonbackground=C_SURFACE,
            highlightthickness=1, highlightbackground=C_BORDER,
            highlightcolor=C_ACCENT, width=4,
            state="disabled",
        )
        wp_spin.pack(side="left", padx=4)

        _unlock_ref = [None]

        def toggle_wp_lock():
            if wp_spin.cget("state") == "disabled":
                wp_spin.configure(state="normal")
                _unlock_ref[0].configure(text="锁定编号", fg=C_RED)
            else:
                wp_spin.configure(state="disabled")
                _unlock_ref[0].configure(text="修改编号", fg=C_MUTED)

        unlock_btn = tk.Button(
            wp_row, text="修改编号",
            font=FONT_SMALL, bg=C_SURFACE, fg=C_MUTED,
            relief="flat", cursor="hand2",
            padx=8, pady=3, highlightthickness=0,
            activebackground=C_BORDER,
            command=toggle_wp_lock,
        )
        unlock_btn.pack(side="left", padx=(6, 0))
        _unlock_ref[0] = unlock_btn

        tk.Frame(dlg, bg=C_BORDER, height=1).pack(fill="x", padx=24, pady=(6, 8))

        frm = tk.Frame(dlg, bg=C_CARD)
        frm.pack(padx=24)

        lbl_kw = dict(bg=C_CARD, fg=C_TEXT, font=FONT_UI, anchor="w")

        def make_wp_7pt(parent, label):
            r = tk.Frame(parent, bg=C_CARD)
            r.pack(fill="x", pady=5)
            tk.Label(r, text=f"{label}：", **lbl_kw, width=8).pack(side="left")
            sel_frm, var = self._make_7pt_selector(r, C_CARD, 0)
            sel_frm.pack(side="left")
            return var

        emo_var = make_wp_7pt(frm, "情绪")
        aro_var = make_wp_7pt(frm, "激动度")
        fat_var = make_wp_7pt(frm, "疲劳度")

        tk.Frame(dlg, bg=C_BORDER, height=1).pack(fill="x", padx=24, pady=(8, 0))

        btn_row = tk.Frame(dlg, bg=C_CARD)
        btn_row.pack(pady=14)

        def on_wp_save():
            actual_wp_id = int(wp_id_var.get())

            # 若尚未建立受试者目录，自动创建
            if self._participant_dir is None:
                pid = config.PARTICIPANT_ID
                self._participant_dir = Path(config.DATA_ROOT) / "subjects" / pid
                self._participant_dir.mkdir(parents=True, exist_ok=True)

            sr_path = self._participant_dir / "self_report.json"
            if sr_path.exists():
                with open(sr_path, "r", encoding="utf-8") as f:
                    sr_data = json.load(f)
            else:
                sr_data = {"participant_id": config.PARTICIPANT_ID, "waypoints": []}

            if "waypoints" not in sr_data:
                sr_data["waypoints"] = []

            emo = emo_var.get()
            aro = aro_var.get()
            fat = fat_var.get()

            others = [w for w in sr_data["waypoints"]
                      if w.get("waypoint_id") != actual_wp_id]
            others.append({
                "waypoint_id": actual_wp_id,
                "emotion":     emo,
                "arousal":     aro,
                "fatigue":     fat,
                "timestamp":   self._now(),
            })
            others.sort(key=lambda x: x.get("waypoint_id", 0))
            sr_data["waypoints"] = others

            with open(sr_path, "w", encoding="utf-8") as f:
                json.dump(sr_data, f, ensure_ascii=False, indent=2)

            # 在视频分段 JSONL 中为刚结束的那段标注途径点编号
            self._mark_last_segment(actual_wp_id)

            def _sign(v):
                return f"+{v}" if v > 0 else str(v)

            self._append_log(
                f"[GUI] 途径点 {actual_wp_id} — 视频已标注，自评已保存"
                f"  情绪={_sign(emo)}  激动度={_sign(aro)}  疲劳度={_sign(fat)}\n"
            )
            dlg.destroy()

        tk.Button(
            btn_row, text="保存", command=on_wp_save,
            bg=C_ACCENT, fg="white",
            font=FONT_BOLD, relief="flat", cursor="hand2",
            padx=28, pady=8,
            activebackground=C_ACCENT_H, highlightthickness=0,
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            btn_row, text="取消", command=dlg.destroy,
            bg=C_SURFACE, fg=C_MUTED,
            font=FONT_BOLD, relief="flat", cursor="hand2",
            padx=20, pady=8, highlightthickness=0,
            activebackground=C_BORDER,
        ).pack(side="left")

    # ── 测试 ──────────────────────────────────────────────────────────────────

    def _start_test(self):
        if self._task:
            messagebox.showwarning("提示", "请等待当前任务完成后再操作。", parent=self)
            return

        self._task = "test"
        self._update_buttons("test")
        self._append_log(
            f"\n{'=' * 60}\n  开始设备测试    {self._now()}\n{'=' * 60}\n"
        )

        def _run():
            try:
                test_mod.main()
            except Exception as exc:
                self._log_q.put(f"\n[GUI] 测试过程出现异常: {exc}\n")
            finally:
                self.after(0, self._on_task_done)

        self._bg_thread = threading.Thread(target=_run, daemon=True, name="test_thread")
        self._bg_thread.start()

    # ── 采集（开始 / 停止切换）────────────────────────────────────────────────

    def _toggle_collect(self):
        if self._task == "test":
            messagebox.showwarning("提示", "测试进行中，请等待结束后再采集。", parent=self)
            return

        if self._task == "collect":
            self._append_log("\n[GUI] 正在发送停止信号，等待视频写入完成...\n")
            collect.stop_event.set()
            self._btn_collect.configure(state="disabled", text="正在停止...")
        else:
            # 重置途径点计数和 collect 侧计数器
            self._waypoint_count = 0
            collect._waypoint_count = 0

            collect.stop_event.clear()
            self._task = "collect"
            pid = config.PARTICIPANT_ID
            self._update_buttons("collect")
            self._lbl_collecting.configure(
                text=f"  \u25cf  正在采集第 {pid} 号受试者数据",
                bg=C_CARD, fg=C_RED,
            )
            self._append_log(
                f"\n{'=' * 60}\n"
                f"  开始采集    受试者: {pid}    {self._now()}\n"
                f"{'=' * 60}\n"
            )
            # 摄像头就绪后再启动计时器，避免计时早于实际录制开始
            collect.cameras_ready_event.clear()

            def _wait_cameras_then_timer():
                collect.cameras_ready_event.wait(timeout=30.0)
                if self._task == "collect":
                    self.after(0, self._start_collect_timer)

            threading.Thread(
                target=_wait_cameras_then_timer,
                daemon=True, name="timer_wait_thread"
            ).start()

            def _run():
                try:
                    collect.main()
                except Exception as exc:
                    self._log_q.put(f"\n[GUI] 采集过程出现异常: {exc}\n")
                finally:
                    self.after(0, self._on_task_done)

            self._bg_thread = threading.Thread(
                target=_run, daemon=True, name="collect_thread"
            )
            self._bg_thread.start()

    # ── 任务结束 ──────────────────────────────────────────────────────────────

    def _on_task_done(self):
        prev = self._task
        self._task = None
        self._lbl_collecting.configure(text="", bg=C_CARD)
        self._update_buttons("idle")
        label = "采集" if prev == "collect" else "测试"
        if prev == "collect":
            self._stop_collect_timer()
            # 为最后一段视频标注 endpoint
            self._mark_last_segment("endpoint")
            self._append_log(f"\n[GUI] {label}已结束    {self._now()}\n")
            # 提醒记录终点情绪自评
            self.after(300, lambda: messagebox.showinfo(
                "采集结束",
                "视频录制已停止。\n\n请记得在「受试者信息」中记录终点的情绪自评！",
                parent=self,
            ))
        else:
            self._append_log(f"\n[GUI] {label}已结束    {self._now()}\n")

    # ── 按钮状态 ──────────────────────────────────────────────────────────────

    def _update_buttons(self, state: str):
        if state == "idle":
            self._btn_settings.configure(state="normal")
            self._btn_subject_info.configure(state="normal")
            self._btn_verbal.configure(state="normal")
            self._btn_test.configure(
                state="normal", text="测试设备",
                bg=C_SURFACE, fg=C_TEXT,
            )
            self._btn_route.configure(
                state="normal", text="路线选择",
                bg=C_SURFACE, fg=C_TEXT,
            )
            self._btn_collect.configure(
                state="normal", text="开始采集",
                bg=C_ACCENT, fg="white",
            )
            self._btn_waypoint.configure(state="disabled", bg=C_SURFACE, fg=C_MUTED)

        elif state == "test":
            self._btn_settings.configure(state="normal")
            self._btn_subject_info.configure(state="disabled")
            self._btn_verbal.configure(state="normal")
            self._btn_test.configure(
                state="disabled", text="测试中...",
                bg=C_BORDER, fg=C_MUTED,
            )
            self._btn_route.configure(state="disabled")
            self._btn_collect.configure(state="disabled")
            self._btn_waypoint.configure(state="disabled")

        elif state == "collect":
            self._btn_settings.configure(state="disabled")
            self._btn_subject_info.configure(state="disabled")
            self._btn_verbal.configure(state="normal")
            self._btn_test.configure(state="disabled")
            self._btn_route.configure(state="disabled")
            self._btn_collect.configure(
                state="normal", text="停止采集",
                bg=C_RED, fg="white",
                activebackground="#a52020",
            )
            self._btn_waypoint.configure(
                state="normal",
                bg=C_YELLOW, fg="white",
                activebackground="#c45e00",
            )

    # ── test.py input() 拦截（主线程执行）────────────────────────────────────

    def _stdin_ask_camera(self):
        ans = messagebox.askyesno(
            "摄像头测试",
            "GPS 测试已完成。\n\n是否继续进行摄像头测试？",
            parent=self,
        )
        _gui_stdin._result = "y" if ans else "n"
        _gui_stdin._ready.set()

    # ── 关闭处理 ──────────────────────────────────────────────────────────────

    def _on_close(self):
        if self._task == "collect":
            if not messagebox.askyesno(
                "确认退出",
                "采集正在进行中！\n\n"
                "退出将停止采集，系统会等待视频写入完成后关闭。\n\n确定退出吗？",
                parent=self,
            ):
                return
            collect.stop_event.set()
        elif self._task == "test":
            if not messagebox.askyesno(
                "确认退出", "测试正在进行中，确定要退出吗？", parent=self,
            ):
                return
        self._stop_route_servers()
        self.destroy()

    # ── 路线选择（Google Maps 界面）────────────────────────────────────────────

    def _open_route_selection(self):
        """打开路线选择网页界面；若受试者信息未填写则拦截。"""
        if not config.PARTICIPANT_ID:
            messagebox.showwarning(
                "提示", "请先填写受试者信息。", parent=self,
            )
            return
        self._start_route_servers()

    @staticmethod
    def _is_port_in_use(port: int) -> bool:
        """检测本地端口是否已被占用。"""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) == 0

    def _start_route_servers(self):
        """
        启动路线导航服务并在浏览器中打开界面。

        打包后（frozen EXE）：
          以 --backend-mode 重新调用自身 EXE，uvicorn 同时提供 API 与静态前端文件，
          浏览器打开 http://localhost:17843/

        开发模式（dist/ 已构建）：
          同样以 --backend-mode 调用 gui_app.py，后端提供静态文件，
          浏览器打开 http://localhost:17843/

        开发模式（dist/ 尚未构建）：
          额外启动 npm run dev，浏览器打开 http://localhost:5173/
        """
        self._stop_route_servers()

        _no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        # ── 确定前端 dist 目录 ────────────────────────────────────────────────
        _meipass = getattr(sys, "_MEIPASS", None)
        if _meipass:
            frontend_dist = Path(_meipass) / "google_interface" / "frontend" / "dist"
        else:
            frontend_dist = _HERE / "google_interface" / "frontend" / "dist"

        # ── 若端口已有服务，直接复用（避免重复启动/端口冲突）──────────────
        if self._is_port_in_use(17843):
            self._append_log(
                f"[GUI] 检测到路线服务已运行，直接复用"
                f"（受试者: {config.PARTICIPANT_ID}）\n"
            )
            _open_url = f"http://localhost:17843/?t={int(time.time())}"
            def _open_reuse():
                time.sleep(0.5)
                webbrowser.open(_open_url)
                self._log_q.put("[GUI] 已在浏览器中打开路线选择界面\n")
            threading.Thread(target=_open_reuse, daemon=True, name="route_browser_thread").start()
            return

        # ── 构造后端启动命令 ──────────────────────────────────────────────────
        # frozen EXE：直接调用自身；开发模式：python gui_app.py
        if getattr(sys, "frozen", False):
            entry = [sys.executable]
        else:
            entry = [sys.executable, str(_HERE / "gui_app.py")]

        cmd = entry + [
            "--backend-mode",
            f"--participant-id={config.PARTICIPANT_ID}",
            f"--data-root={config.DATA_ROOT}",
            f"--frontend-dist={frontend_dist}",
        ]

        _backend_env = os.environ.copy()
        _backend_env["ROUTE_VERSION"] = getattr(config, "ROUTE_VERSION", "new")

        try:
            self._route_backend = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_no_window,
                env=_backend_env,
            )
            self._append_log(
                f"[GUI] 路线导航服务已启动（受试者: {config.PARTICIPANT_ID}）\n"
            )
        except Exception as exc:
            self._append_log(f"[GUI] 路线导航服务启动失败: {exc}\n")
            messagebox.showerror(
                "启动失败",
                f"无法启动路线导航服务：\n{exc}",
                parent=self,
            )
            return

        # ── 开发模式且 dist/ 尚未构建 → 同时启动 npm dev server ─────────────
        if not getattr(sys, "frozen", False) and not frontend_dist.exists():
            npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
            frontend_dir = _HERE / "google_interface" / "frontend"
            try:
                self._route_frontend = subprocess.Popen(
                    [npm_cmd, "run", "dev"],
                    cwd=str(frontend_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=_no_window,
                )
                self._append_log("[GUI] 开发模式：前端 dev server 已启动（localhost:5173）\n")
                _open_url   = f"http://localhost:5173/?t={int(time.time())}"
                _open_delay = 3
            except Exception as exc:
                self._append_log(f"[GUI] 前端 dev server 启动失败: {exc}\n")
                _open_url   = f"http://localhost:17843/?t={int(time.time())}"
                _open_delay = 2
        else:
            _open_url   = f"http://localhost:17843/?t={int(time.time())}"
            _open_delay = 2

        # ── 延迟后打开浏览器（先确认后端已就绪）─────────────────────────────
        def _open():
            deadline = time.time() + 10
            while time.time() < deadline:
                if self._is_port_in_use(17843):
                    break
                time.sleep(0.3)
            else:
                self._log_q.put("[GUI] 路线服务启动超时，请重试\n")
                return
            time.sleep(0.3)
            webbrowser.open(_open_url)
            self._log_q.put("[GUI] 已在浏览器中打开路线选择界面\n")

        threading.Thread(target=_open, daemon=True, name="route_browser_thread").start()

    def _stop_route_servers(self):
        """终止路线选择的后端与前端子进程。"""
        for attr in ("_route_backend", "_route_frontend"):
            proc: "subprocess.Popen | None" = getattr(self, attr, None)
            if proc is not None:
                try:
                    proc.terminate()
                except Exception:
                    pass
                setattr(self, attr, None)

    # ── 工具 ──────────────────────────────────────────────────────────────────

    def _mark_last_segment(self, waypoint_label):
        """
        将途径点编号（整数）或 'endpoint' 写入两路摄像头 segments.jsonl 的最后一条记录。
        在途径点自评保存后、以及采集结束后各调用一次。
        """
        pid  = config.PARTICIPANT_ID
        root = Path(config.DATA_ROOT)
        for cam in ("facial_video", "traffic_video"):
            jsonl_path = root / "subjects" / pid / cam / f"{pid}_segments.jsonl"
            if not jsonl_path.exists():
                continue
            try:
                with open(jsonl_path, "r", encoding="utf-8") as f:
                    lines = [ln.rstrip() for ln in f if ln.strip()]
                if not lines:
                    continue
                last_rec = json.loads(lines[-1])
                last_rec["waypoint_id"] = waypoint_label
                lines[-1] = json.dumps(last_rec, ensure_ascii=False)
                with open(jsonl_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
            except Exception as e:
                print(f"[GUI] 标注 {cam} 分段失败: {e}\n")

    @staticmethod
    def _make_7pt_selector(parent, bg_color: str, initial_value: int = 0):
        """
        创建水平排列的7点量表选择器（-3 到 +3），使用按钮式单选控件。
        返回 (frame, IntVar)。
        """
        var = tk.IntVar(value=initial_value)
        frame = tk.Frame(parent, bg=bg_color)
        for val in range(-3, 4):
            lbl = str(val) if val <= 0 else f"+{val}"
            tk.Radiobutton(
                frame, text=lbl, variable=var, value=val,
                bg=C_SURFACE, fg=C_TEXT,
                selectcolor="#4dabf7",       # 亮天蓝，深色文字对比度 ≈ 6:1
                activebackground=C_ACCENT,   # 悬停时深蓝背景
                activeforeground="white",    # 悬停时白色文字
                font=("Microsoft YaHei UI", 9, "bold"),
                indicatoron=False,
                width=2,
                relief="groove",
                bd=1,
                cursor="hand2",
            ).pack(side="left", padx=1)
        return frame, var

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")

    def _center_child(self, win: tk.Toplevel, w: int, h: int):
        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width()  - w) // 2
        y = self.winfo_y() + (self.winfo_height() - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")


# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = App()
    app.mainloop()
