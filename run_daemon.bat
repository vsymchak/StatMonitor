@echo off
chcp 65001 > nul
title StatMonitor Daemon
cd /d "%~dp0"
echo ========================================================
echo  🚀 Запуск автономного демона StatMonitor (кожні 30 хв)
echo ========================================================
"C:\Users\Admin\AppData\Local\Programs\Python\Python312\python.exe" daemon.py --interval 30
pause
