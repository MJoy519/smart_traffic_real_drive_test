# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包规格文件
构建方式：--onedir（单目录），便于子进程自调用（路线导航后端模式）。

必须先在 google_interface/frontend 执行 npm run build 再打包。
"""
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas       = []
binaries    = []
hiddenimports = []

# ── cv2（OpenCV）────────────────────────────────────────────────────────────
tmp = collect_all('cv2')
datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]

# ── FastAPI / uvicorn 及其完整依赖 ───────────────────────────────────────────
for _pkg in (
    'uvicorn', 'fastapi', 'starlette',
    'pydantic', 'pydantic_core',
    'anyio', 'sniffio', 'h11',
    'httpx', 'httpcore',
    'aiofiles',         # StaticFiles 异步文件服务
    'googlemaps',
):
    tmp = collect_all(_pkg)
    datas += tmp[0]; binaries += tmp[1]; hiddenimports += tmp[2]

# ── 补充 uvicorn / starlette 可能遗漏的子模块 ────────────────────────────────
hiddenimports += [
    'uvicorn.lifespan.on',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.http.httptools_impl',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.protocols.websockets.wsproto_impl',
    'uvicorn.loops.asyncio',
    'uvicorn.loops.uvloop',
    'starlette.middleware.cors',
    'starlette.staticfiles',
    'starlette.routing',
    'pydantic.deprecated.class_validators',
    # 原有依赖
    'serial', 'serial.tools', 'serial.tools.list_ports',
    'pynmea2', 'requests', 'dotenv', 'python_dotenv',
]

# ── Google Interface：后端 Python 文件 ───────────────────────────────────────
# 包含 main.py / config.py / modules/ / routes/*.json
datas += [
    ('google_interface/backend', 'google_interface/backend'),
]

# ── Google Interface：前端已构建静态文件 ──────────────────────────────────────
# 需要先执行 npm run build 生成 dist/
datas += [
    ('google_interface/frontend/dist', 'google_interface/frontend/dist'),
]

# ════════════════════════════════════════════════════════════════════════════
a = Analysis(
    ['gui_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'wx'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# --onedir：EXE 单独一个文件，其余依赖在同目录，子进程自调用无需重新解压
exe = EXE(
    pyz,
    a.scripts,
    [],                        # 依赖文件由 COLLECT 统一放置，不打入 EXE
    exclude_binaries=True,
    name='Data Collection',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,             # --windowed：不显示控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Data Collection',    # 输出到 dist/Data Collection/
)
