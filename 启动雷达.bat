@echo off
chcp 65001 >nul
title 全渠道趋势雷达 (Trend Radar)
echo 正在启动全渠道趋势雷达...
cd /d "%~dp0"

start /b python server.py
timeout /t 1 /nobreak >nul

echo 启动成功！正在打开浏览器...
start http://127.0.0.1:8989
exit
