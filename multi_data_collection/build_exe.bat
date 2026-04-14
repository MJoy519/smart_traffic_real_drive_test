@echo off
chcp 65001 >nul
echo.
echo Launching build script via PowerShell ...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1"
echo.
if errorlevel 1 (
    echo BUILD FAILED  --  see errors above.
) else (
    echo BUILD FINISHED.
)
echo.
pause
