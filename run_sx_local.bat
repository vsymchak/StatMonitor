@echo off
chcp 65001 >nul
cd /d "%~dp0"
title StatMonitor - Local SX Bet Worker

echo ====================================================================
echo   StatMonitor Local SX Bet Worker (Windows / Non-US IP)
echo ====================================================================
echo.

if not exist ".env" goto :no_env

set "PY_BIN="
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    "%LocalAppData%\Programs\Python\Python312\python.exe" -c "import psycopg2, requests, eth_account" >nul 2>&1
    if not errorlevel 1 set "PY_BIN=%LocalAppData%\Programs\Python\Python312\python.exe"
)
if not "%PY_BIN%"=="" goto :run_worker

python -c "import psycopg2, requests, eth_account" >nul 2>&1
if not errorlevel 1 set "PY_BIN=python"
if not "%PY_BIN%"=="" goto :run_worker

echo [ERROR] Python 3.12 with psycopg2, requests, eth_account was not found!
pause
exit /b 1

:no_env
echo [ERROR] File .env not found in %CD%
pause
exit /b 1

:run_worker
echo Using Python: %PY_BIN%
echo Checking SX Bet every 5 minutes (press Ctrl+C to stop)...
echo.
"%PY_BIN%" -u scripts\sx_local_worker.py --interval 300 %*
set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [EXIT %EXIT_CODE%] Stopped with error. Update SUPABASE_DB_URL password in .env!
    pause
)
exit /b %EXIT_CODE%
