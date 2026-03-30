"""
gui_app.py  —  Smart Traffic 实车采集 图形界面
================================================
界面操作：
  修改编号  —— 输入数字，修改当前受试者序号
  测试设备  —— 运行 test.py（GPS + 摄像头预览）
  开始采集  —— 运行 collect.py；状态栏实时显示当前受试者
  ⚙        —— 右上角设置：数据路径、分段时长、GPS 串口/频率

线程安全要点：
  * stdout/stderr  通过 Queue 转发，主线程 after(50ms) 轮询写入 Text
  * stdin input()  _GUIStdin.readline() 拦截；after(0)+Event 让主线程弹框再返回
  * 采集停止       collect.stop_event.set()；下次启动前先 clear()
  * 所有 tkinter 操作均在主线程完成
"""

import json
import os
import sys
import queue
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ── 基础路径（兼容 PyInstaller --onefile / --onedir / 直接运行）──────────────
if getattr(sys, "frozen", False):
    _HERE = Path(sys.executable).parent   # exe 所在目录
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
config.DATA_ROOT                   = _settings["data_root"]
config.VIDEO_SAVE_INTERVAL_MINUTES = _settings["video_save_interval_minutes"]
config.GPS_PORT                    = _settings["gps_port"]
config.GPS_QUERY_INTERVAL          = _settings["gps_query_interval"]

import collect
import test as test_mod

# ── 浅色主题 ──────────────────────────────────────────────────────────────────
C_BG       = "#f5f6fa"   # 主背景
C_CARD     = "#ffffff"   # 卡片 / 状态栏
C_SURFACE  = "#e8ecf4"   # 按钮默认底色
C_BORDER   = "#d0d7e3"   # 细边框
C_ACCENT   = "#1a3a6b"   # 主色调（墨蓝）
C_ACCENT_H = "#13285a"   # 主色调 hover
C_GREEN    = "#2f9e44"   # 成功绿
C_GREEN_BG = "#ebfbee"   # 采集状态栏背景
C_RED      = "#c92a2a"   # 错误 / 停止红
C_RED_BG   = "#fff5f5"
C_YELLOW   = "#e67700"   # 警告黄
C_TEXT     = "#1a1a2e"   # 主文字
C_MUTED    = "#6c757d"   # 次要文字
C_LOG_BG   = "#1c1c1c"   # 日志区（深色背景）
C_LOG_FG   = "#f0f0f0"   # 默认日志文字（近白色）
C_LOG_ERR  = "#cd6069"   # 错误（柔和暗红）
C_LOG_OK   = "#4ec9b0"   # 成功（柔和青绿）
C_LOG_WARN = "#c8a94f"   # 警告（低饱和金黄）
C_LOG_HEAD = "#9db4d4"   # 分隔线（低饱和蓝灰）

FONT_UI    = ("Microsoft YaHei UI", 10)
FONT_BOLD  = ("Microsoft YaHei UI", 11, "bold")
FONT_BIG   = ("Microsoft YaHei UI", 14, "bold")
FONT_MONO  = ("Microsoft YaHei UI", 10)


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
        self.geometry("860x680")
        self.minsize(700, 520)
        self.configure(bg=C_BG)

        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._task: str | None = None       # None | "test" | "collect"
        self._bg_thread: threading.Thread | None = None

        _gui_stdin._app = self
        sys.stdout = _LogQueue(self._log_q)
        sys.stderr = _LogQueue(self._log_q)
        sys.stdin  = _gui_stdin

        self._build_ui()
        self._poll_log()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 界面布局 ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── 顶部标题行（标题左 + 设置按钮右）────────────────────────────────
        title_row = tk.Frame(self, bg=C_BG, pady=14)
        title_row.pack(fill="x", padx=24)

        tk.Label(
            title_row,
            text="Smart Traffic 实车采集",
            font=("Microsoft YaHei UI", 15, "bold"),
            bg=C_BG, fg=C_TEXT,
        ).pack(side="left")

        # 右上角设置按钮（⚙）
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
        self._status_bar = tk.Frame(self, bg=C_CARD, pady=13,
                                    highlightbackground=C_BORDER,
                                    highlightthickness=1)
        self._status_bar.pack(fill="x", padx=24, pady=(0, 10))

        tk.Label(
            self._status_bar, text="当前受试者：",
            font=FONT_UI, bg=C_CARD, fg=C_MUTED,
        ).pack(side="left", padx=(18, 0))

        self._lbl_pid = tk.Label(
            self._status_bar, text=config.PARTICIPANT_ID,
            font=FONT_BIG, bg=C_CARD, fg=C_ACCENT,
        )
        self._lbl_pid.pack(side="left", padx=(4, 0))

        # "修改编号"小按钮
        self._btn_change_pid = tk.Button(
            self._status_bar, text="修改编号",
            font=("Microsoft YaHei UI", 9),
            bg=C_SURFACE, fg=C_MUTED,
            relief="flat", cursor="hand2",
            bd=0, highlightthickness=0,
            padx=10, pady=4,
            activebackground=C_BORDER,
            activeforeground=C_TEXT,
            command=self._change_pid,
        )
        self._btn_change_pid.pack(side="left", padx=(10, 0))

        # 采集时右侧显示醒目状态
        self._lbl_collecting = tk.Label(
            self._status_bar, text="",
            font=("Microsoft YaHei UI", 12, "bold"),
            bg=C_CARD, fg=C_GREEN,
        )
        self._lbl_collecting.pack(side="left", padx=(28, 0))

        # ── 操作按钮区 ────────────────────────────────────────────────────────
        btn_row = tk.Frame(self, bg=C_BG)
        btn_row.pack(fill="x", padx=24, pady=(0, 12))

        _bkw = dict(
            font=FONT_BOLD, relief="flat", cursor="hand2",
            padx=28, pady=11, bd=0, highlightthickness=0,
        )

        self._btn_test = tk.Button(
            btn_row, text="测试设备",
            bg=C_SURFACE, fg=C_TEXT,
            activebackground=C_ACCENT, activeforeground="white",
            command=self._start_test, **_bkw,
        )
        self._btn_test.pack(side="left", padx=(0, 8))

        self._btn_collect = tk.Button(
            btn_row, text="开始采集",
            bg=C_ACCENT, fg="white",
            activebackground=C_ACCENT_H, activeforeground="white",
            command=self._toggle_collect, **_bkw,
        )
        self._btn_collect.pack(side="left", padx=(0, 8))

        tk.Button(
            btn_row, text="清空日志",
            bg=C_SURFACE, fg=C_MUTED,
            font=FONT_UI, relief="flat", cursor="hand2",
            activebackground=C_BORDER, activeforeground=C_TEXT,
            padx=14, pady=11, highlightthickness=0,
            command=self._clear_log,
        ).pack(side="right")

        # ── 日志区（深色背景保持可读性）──────────────────────────────────────
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

    # ── 修改受试者编号 ────────────────────────────────────────────────────────

    def _change_pid(self):
        if self._task == "collect":
            messagebox.showwarning("提示", "采集进行中，请先停止采集再修改编号。", parent=self)
            return
        if self._task == "test":
            messagebox.showwarning("提示", "测试进行中，请等待完成后再修改编号。", parent=self)
            return

        dlg = tk.Toplevel(self)
        dlg.title("修改受试者编号")
        dlg.configure(bg=C_CARD)
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self)
        self._center_child(dlg, 300, 170)

        tk.Label(dlg, text="请输入受试者编号（正整数）：",
                 font=FONT_UI, bg=C_CARD, fg=C_TEXT,
                 ).pack(pady=(22, 8))

        entry_var = tk.StringVar()
        # 取当前编号中的数字部分作为默认值
        cur = config.PARTICIPANT_ID.lstrip("P")
        entry_var.set(cur if cur.isdigit() else "1")

        entry = tk.Entry(
            dlg, textvariable=entry_var,
            font=("Microsoft YaHei UI", 13, "bold"),
            justify="center", width=8,
            relief="flat", bd=0,
            bg=C_SURFACE, fg=C_ACCENT,
            insertbackground=C_ACCENT,
            highlightthickness=1,
            highlightbackground=C_BORDER,
            highlightcolor=C_ACCENT,
        )
        entry.pack(pady=(0, 14))
        entry.select_range(0, "end")
        entry.focus_set()

        def on_confirm(event=None):
            val = entry_var.get().strip()
            if not val.isdigit() or int(val) <= 0:
                messagebox.showwarning("格式错误", "请输入一个正整数，例如 1、2、3。",
                                       parent=dlg)
                return
            config.PARTICIPANT_ID = f"P{val}"
            self._lbl_pid.configure(text=config.PARTICIPANT_ID)
            dlg.destroy()

        entry.bind("<Return>", on_confirm)

        tk.Button(
            dlg, text="确认", command=on_confirm,
            bg=C_ACCENT, fg="white",
            font=FONT_BOLD, relief="flat", cursor="hand2",
            padx=32, pady=8,
            activebackground=C_ACCENT_H, highlightthickness=0,
        ).pack()

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
        self._center_child(dlg, 500, 320)

        # 标题
        tk.Label(dlg, text="系统设置", font=FONT_BIG,
                 bg=C_CARD, fg=C_TEXT).pack(pady=(18, 12))

        frm = tk.Frame(dlg, bg=C_CARD)
        frm.pack(fill="x", padx=30)

        lbl_kw  = dict(bg=C_CARD, fg=C_TEXT,  font=FONT_UI, anchor="w")
        entry_kw = dict(
            relief="flat", bd=0,
            bg=C_SURFACE, fg=C_TEXT,
            font=FONT_UI,
            highlightthickness=1,
            highlightbackground=C_BORDER,
            highlightcolor=C_ACCENT,
        )

        # ── 行辅助 ───────────────────────────────────────────────────────────
        def add_row(parent, row, label, widget_factory):
            tk.Label(parent, text=label, width=20, **lbl_kw).grid(
                row=row, column=0, sticky="w", pady=6)
            widget_factory(parent, row)

        # 1. 数据存储路径
        data_var = tk.StringVar(value=config.DATA_ROOT)

        def make_data_row(p, r):
            path_entry = tk.Entry(p, textvariable=data_var, width=28, **entry_kw)
            path_entry.grid(row=r, column=1, sticky="ew", padx=(0, 6))
            tk.Button(
                p, text="浏览", font=("Microsoft YaHei UI", 9),
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

        # 2. 视频分段时长
        video_var = tk.StringVar(value=str(config.VIDEO_SAVE_INTERVAL_MINUTES))

        def make_video_row(p, r):
            sb = tk.Spinbox(
                p, from_=1, to=60, width=8,
                textvariable=video_var,
                relief="flat", bd=0,
                bg=C_SURFACE, fg=C_TEXT,
                font=FONT_UI,
                buttonbackground=C_SURFACE,
                highlightthickness=1,
                highlightbackground=C_BORDER,
                highlightcolor=C_ACCENT,
            )
            sb.grid(row=r, column=1, sticky="w")
            tk.Label(p, text="分钟/段", **lbl_kw).grid(row=r, column=2, sticky="w", padx=4)

        add_row(frm, 1, "视频分段时长：", make_video_row)

        # 3. GPS 串口号
        port_var = tk.StringVar(value=config.GPS_PORT)

        def make_port_row(p, r):
            tk.Entry(p, textvariable=port_var, width=10, **entry_kw).grid(
                row=r, column=1, sticky="w")

        add_row(frm, 2, "GPS 串口号：", make_port_row)

        # 4. GPS 采集间隔
        gps_var = tk.StringVar(value=str(config.GPS_QUERY_INTERVAL))

        def make_gps_row(p, r):
            sb = tk.Spinbox(
                p, from_=5, to=300, width=8,
                textvariable=gps_var,
                relief="flat", bd=0,
                bg=C_SURFACE, fg=C_TEXT,
                font=FONT_UI,
                buttonbackground=C_SURFACE,
                highlightthickness=1,
                highlightbackground=C_BORDER,
                highlightcolor=C_ACCENT,
            )
            sb.grid(row=r, column=1, sticky="w")
            tk.Label(p, text="秒/次", **lbl_kw).grid(row=r, column=2, sticky="w", padx=4)

        add_row(frm, 3, "GPS 采集间隔：", make_gps_row)

        frm.columnconfigure(1, weight=1)

        # ── 保存 / 取消 ───────────────────────────────────────────────────────
        btn_row = tk.Frame(dlg, bg=C_CARD)
        btn_row.pack(pady=(16, 18))

        def on_save():
            # 校验
            video_val = video_var.get().strip()
            gps_val   = gps_var.get().strip()
            if not video_val.isdigit() or int(video_val) < 1:
                messagebox.showwarning("格式错误", "视频分段时长须为正整数（分钟）。", parent=dlg)
                return
            if not gps_val.isdigit() or int(gps_val) < 1:
                messagebox.showwarning("格式错误", "GPS 采集间隔须为正整数（秒）。", parent=dlg)
                return
            port = port_var.get().strip()
            if not port:
                messagebox.showwarning("格式错误", "GPS 串口号不能为空。", parent=dlg)
                return
            data_path = data_var.get().strip()
            if not data_path:
                messagebox.showwarning("格式错误", "数据存储路径不能为空。", parent=dlg)
                return

            # 应用到 config
            config.DATA_ROOT                   = data_path
            config.VIDEO_SAVE_INTERVAL_MINUTES = int(video_val)
            config.GPS_PORT                    = port
            config.GPS_QUERY_INTERVAL          = int(gps_val)

            # 持久化
            _save_settings({
                "data_root":                    data_path,
                "video_save_interval_minutes":  int(video_val),
                "gps_port":                     port,
                "gps_query_interval":           int(gps_val),
            })
            dlg.destroy()
            messagebox.showinfo("已保存", "设置已保存，下次采集时生效。", parent=self)

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

        self._bg_thread = threading.Thread(
            target=_run, daemon=True, name="test_thread"
        )
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
        self._append_log(f"\n[GUI] {label}已结束    {self._now()}\n")

    # ── 按钮状态 ──────────────────────────────────────────────────────────────

    def _update_buttons(self, state: str):
        if state == "idle":
            self._btn_settings.configure(state="normal")
            self._btn_change_pid.configure(state="normal")
            self._btn_test.configure(
                state="normal", text="测试设备",
                bg=C_SURFACE, fg=C_TEXT,
            )
            self._btn_collect.configure(
                state="normal", text="开始采集",
                bg=C_ACCENT, fg="white",
            )
        elif state == "test":
            self._btn_settings.configure(state="normal")
            self._btn_change_pid.configure(state="disabled")
            self._btn_test.configure(
                state="disabled", text="测试中...",
                bg=C_BORDER, fg=C_MUTED,
            )
            self._btn_collect.configure(state="disabled")
        elif state == "collect":
            self._btn_settings.configure(state="disabled")
            self._btn_change_pid.configure(state="disabled")
            self._btn_test.configure(state="disabled")
            self._btn_collect.configure(
                state="normal", text="停止采集",
                bg=C_RED, fg="white",
                activebackground="#a52020",
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
        self.destroy()

    # ── 工具 ──────────────────────────────────────────────────────────────────

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
