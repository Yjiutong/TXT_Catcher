@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem 优先启动 dist 下的已打包版本；若没有则用 .venv 或系统 Python 跑源码。
if exist "dist\TXT_Catcher.exe" (
    echo 正在启动已打包版本 TXT_Catcher.exe ...
    start "" "dist\TXT_Catcher.exe"
    exit /b 0
)

if exist ".buildenv\Scripts\pythonw.exe" (
    echo 正在使用虚拟环境启动源码...
    start "" ".buildenv\Scripts\pythonw.exe" "app.py"
    exit /b 0
)

if exist ".venv\Scripts\pythonw.exe" (
    echo 正在使用虚拟环境启动源码...
    start "" ".venv\Scripts\pythonw.exe" "app.py"
    exit /b 0
)

echo 正在使用系统 Python 启动源码...
python app.py
if errorlevel 1 pause
