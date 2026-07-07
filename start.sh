#!/bin/bash
# 智能任务助理 Linux/Mac 启动脚本
cd "$(dirname "$0")"
echo "启动智能任务助理..."
echo "访问地址: http://localhost:5000"
python app.py
