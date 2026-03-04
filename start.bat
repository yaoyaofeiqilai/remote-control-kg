@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1

cd /d "%~dp0"
title Remote Control Server Launcher

if /I "%~1"=="_elevated" (
    shift
    goto :launch
)

net session >nul 2>&1
if errorlevel 1 (
    echo [INFO] Requesting administrator privileges...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -ArgumentList '_elevated %*'"
    if errorlevel 1 (
        echo [ERROR] Elevation cancelled.
        pause
        exit /b 1
    )
    exit /b 0
)

:launch
set "CHECK_ONLY=0"
if /I "%~1"=="--check-only" (
    set "CHECK_ONLY=1"
    shift
)

call :resolve_python
if errorlevel 1 (
    echo [ERROR] Python 3.12+ was not found.
    pause
    exit /b 1
)

echo [INFO] Python runtime:
call %PY_CMD% --version

echo [INFO] Verifying dependencies...
call %PY_CMD% -c "import flask, flask_socketio, flask_cors, pyautogui, PIL, mss, numpy, sounddevice, pycaw, comtypes, aiortc, av, aiohttp" >nul 2>&1
if errorlevel 1 (
    echo [WARN] Missing dependencies. Installing from requirements.txt...
    call %PY_CMD% -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        pause
        exit /b 1
    )
)

if "%CHECK_ONLY%"=="1" (
    echo [OK] Runtime check passed.
    exit /b 0
)

call :cleanup_stale_server

echo [INFO] Starting server with DXGI mode...
if not defined RC_WEBRTC_H264_ENCODER_ORDER (
    set "RC_WEBRTC_H264_ENCODER_ORDER=h264_nvenc,h264_qsv,h264_mf,h264_amf,libx264"
)
if not defined RC_DXGI_OUTPUT_COLOR (
    set "RC_DXGI_OUTPUT_COLOR=RGB"
)
if not defined RC_AUDIO_ENABLED (
    set "RC_AUDIO_ENABLED=1"
)
if not defined RC_AUDIO_TRANSPORT_DEFAULT_ENABLED (
    set "RC_AUDIO_TRANSPORT_DEFAULT_ENABLED=1"
)
if not defined RC_WEBRTC_AUDIO_OPUS_MAXAVERAGEBITRATE_BPS (
    set "RC_WEBRTC_AUDIO_OPUS_MAXAVERAGEBITRATE_BPS=200000"
)
call %PY_CMD% server.py --dxgi %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo [ERROR] Server exited with code %EXIT_CODE%.
)

echo.
pause
exit /b %EXIT_CODE%

:cleanup_stale_server
set "KILLED_PIDS="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:"0.0.0.0:5000 .*LISTENING"') do (
    set "PROC_NAME="
    for /f "usebackq tokens=1 delims=," %%N in (`tasklist /FI "PID eq %%P" /FO CSV /NH`) do (
        set "PROC_NAME=%%~N"
    )
    if /I "!PROC_NAME!"=="python.exe" (
        taskkill /PID %%P /F >nul 2>&1
        if not errorlevel 1 set "KILLED_PIDS=!KILLED_PIDS! %%P"
    )
)
if defined KILLED_PIDS echo [INFO] Stopped stale server process(es):!KILLED_PIDS!
exit /b 0

:resolve_python
set "PY_CMD="

if exist "C:\Program Files\Python312\python.exe" (
    set "PY_CMD="C:\Program Files\Python312\python.exe""
    exit /b 0
)

if exist "C:\Python312\python.exe" (
    set "PY_CMD="C:\Python312\python.exe""
    exit /b 0
)

py -3.12 --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py -3.12"
    exit /b 0
)

python --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python"
    exit /b 0
)

exit /b 1
