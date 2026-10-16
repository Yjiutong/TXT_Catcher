@echo off
chcp 65001 >nul
cd /d %~dp0
echo 正在打包 TXT_Catcher.exe ...
py -3.14 -m PyInstaller --noconsole --onefile --clean --name TXT_Catcher app.py
echo.
echo 打包完成：dist\TXT_Catcher.exe
pause
