@echo off
chcp 65001 >nul
cd /d %~dp0
echo 正在启动 TXT_Catcher...
python app.py
pause
