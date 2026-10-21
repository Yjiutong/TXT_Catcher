@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo 正在打包 TXT_Catcher.exe ...

set "PY_CMD=python"
if exist ".buildenv\Scripts\python.exe" set "PY_CMD=.buildenv\Scripts\python.exe"
if not exist ".buildenv\Scripts\python.exe" (
    if exist ".venv\Scripts\python.exe" set "PY_CMD=.venv\Scripts\python.exe"
)

%PY_CMD% -m PyInstaller --clean --noconfirm TXT_Catcher.spec

if not exist "dist\TXT_Catcher.exe" (
    echo 打包失败：未生成 dist\TXT_Catcher.exe
    pause
    exit /b 1
)

echo.
echo 打包完成：dist\TXT_Catcher.exe
pause
