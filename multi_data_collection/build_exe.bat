@echo off
chcp 65001 >nul
setlocal

echo ============================================================
echo   EXE 打包脚本
echo ============================================================
echo.

:: ── 切换到脚本所在目录 ──────────────────────────────────────────────────────
cd /d "%~dp0"

:: ── 检查 Python ──────────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+ 并加入 PATH。
    pause & exit /b 1
)

:: ── 安装 / 升级依赖 ──────────────────────────────────────────────────────────
echo [1/3] 安装运行依赖...
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络或手动执行：
    echo        python -m pip install -r requirements.txt
    pause & exit /b 1
)

echo [2/3] 安装 PyInstaller...
python -m pip install pyinstaller --quiet
if errorlevel 1 (
    echo [错误] PyInstaller 安装失败。
    pause & exit /b 1
)

:: ── 打包 ─────────────────────────────────────────────────────────────────────
echo [3/3] 正在打包（可能需要 1~3 分钟）...
echo.

python -m PyInstaller ^
  --onefile ^
  --windowed ^
  --name "Data Collection" ^
  --hidden-import cv2 ^
  --hidden-import serial ^
  --hidden-import serial.tools ^
  --hidden-import serial.tools.list_ports ^
  --hidden-import pynmea2 ^
  --hidden-import requests ^
  --hidden-import dotenv ^
  --hidden-import python_dotenv ^
  --collect-all cv2 ^
  --exclude pyqt5 ^
  gui_app.py

if errorlevel 1 (
    echo.
    echo [错误] 打包失败，请查看上方错误信息。
    pause & exit /b 1
)

:: ── 完成 ─────────────────────────────────────────────────────────────────────
echo.
echo ============================================================
echo   打包成功！
echo ============================================================
echo.
echo   EXE 文件位于：dist\Data Collection.exe
echo.
echo   部署步骤：
echo     1. 将  dist\Data Collection.exe  复制到目标桌面
echo     2. 将  .env                   复制到同一目录
echo     3. 双击 EXE 即可启动
echo.
echo   注意：.env 文件（包含 AZURE_MAPS_KEY）必须与 EXE 在同一目录。
echo ============================================================
echo.
pause
