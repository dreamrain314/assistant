@echo off
REM 智能任务助理 Windows 启动脚本
cd /d "%~dp0"
echo 启动智能任务助理...
echo 访问地址: http://localhost:5000
python app.py
pause
