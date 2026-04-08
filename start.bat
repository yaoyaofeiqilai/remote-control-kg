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

call :apply_runtime_env

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
if not defined RC_ARTIFACTS_DIR (
    set "RC_ARTIFACTS_DIR=artifacts"
)
if not defined RC_WEBRTC_AUDIO_OPUS_MAXAVERAGEBITRATE_BPS (
    set "RC_WEBRTC_AUDIO_OPUS_MAXAVERAGEBITRATE_BPS=200000"
)
if not defined RC_WEBRTC_BITRATE_SCALE (
    set "RC_WEBRTC_BITRATE_SCALE=2.2"
)
if not defined RC_WEBRTC_START_BITRATE_KBPS (
    set "RC_WEBRTC_START_BITRATE_KBPS=32000"
)
if not defined RC_WEBRTC_MIN_BITRATE_KBPS (
    set "RC_WEBRTC_MIN_BITRATE_KBPS=2000"
)
if not defined RC_WEBRTC_RUNTIME_BITRATE_MIN_SCALE (
    set "RC_WEBRTC_RUNTIME_BITRATE_MIN_SCALE=0.45"
)
if not defined RC_WEBRTC_AUDIO_TRANSPORT_BITRATE_CAP_SCALE (
    set "RC_WEBRTC_AUDIO_TRANSPORT_BITRATE_CAP_SCALE=0.90"
)
if not defined RC_WEBRTC_HIGHRES_MIN_BITRATE_BPS (
    set "RC_WEBRTC_HIGHRES_MIN_BITRATE_BPS=16000000"
)
if not defined RC_PAIR_ENABLED (
    set "RC_PAIR_ENABLED=1"
)
if not defined RC_PAIR_CODE (
    set "RC_PAIR_CODE=041013"
)
if not defined RC_PAIR_MAX_ATTEMPTS (
    set "RC_PAIR_MAX_ATTEMPTS=3"
)
if not defined RC_SERVER_AUTORESTART (
    set "RC_SERVER_AUTORESTART=1"
)
if not defined RC_SERVER_RESTART_DELAY_SEC (
    set "RC_SERVER_RESTART_DELAY_SEC=2"
)
if not exist "%RC_ARTIFACTS_DIR%" mkdir "%RC_ARTIFACTS_DIR%" >nul 2>&1
if not exist "%RC_ARTIFACTS_DIR%\\logs" mkdir "%RC_ARTIFACTS_DIR%\\logs" >nul 2>&1
if not exist "%RC_ARTIFACTS_DIR%\\samples" mkdir "%RC_ARTIFACTS_DIR%\\samples" >nul 2>&1
if not exist "%RC_ARTIFACTS_DIR%\\pids" mkdir "%RC_ARTIFACTS_DIR%\\pids" >nul 2>&1
set "SECURITY_FLAG=%RC_ARTIFACTS_DIR%\\security_shutdown.flag"
if exist "%SECURITY_FLAG%" del /f /q "%SECURITY_FLAG%" >nul 2>&1

set "EXIT_CODE=0"

:server_loop
call %PY_CMD% server.py --dxgi %*
set "EXIT_CODE=%ERRORLEVEL%"
if exist "%SECURITY_FLAG%" (
    set "EXIT_CODE=23"
    set "RC_SERVER_AUTORESTART=0"
    echo [SECURITY] Shutdown flag detected: %SECURITY_FLAG%
)
if not "%EXIT_CODE%"=="0" (
    echo [INFO] Server process exited with code %EXIT_CODE%.
)

if "%RC_SERVER_AUTORESTART%"=="1" (
    if not "%EXIT_CODE%"=="0" if not "%EXIT_CODE%"=="23" (
        echo [WARN] Server exited unexpectedly with code %EXIT_CODE%.
        echo [INFO] Restarting in %RC_SERVER_RESTART_DELAY_SEC%s... (set RC_SERVER_AUTORESTART=0 to disable)
        timeout /t %RC_SERVER_RESTART_DELAY_SEC% /nobreak >nul
        goto :server_loop
    )
)

if "%EXIT_CODE%"=="23" (
    echo [SECURITY] Pair code failed %RC_PAIR_MAX_ATTEMPTS% times. Server stopped and auto-restart is blocked.
) else if not "%EXIT_CODE%"=="0" (
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

:apply_runtime_env
set "RC_RUNTIME_ENV_CMD=%TEMP%\remote_control_runtime_env_%RANDOM%_%RANDOM%.cmd"
call %PY_CMD% tools\emit_runtime_env_cmd.py > "%RC_RUNTIME_ENV_CMD%" 2>nul
if errorlevel 1 (
    if exist "%RC_RUNTIME_ENV_CMD%" del /f /q "%RC_RUNTIME_ENV_CMD%" >nul 2>&1
    exit /b 1
)
if exist "%RC_RUNTIME_ENV_CMD%" (
    call "%RC_RUNTIME_ENV_CMD%"
    del /f /q "%RC_RUNTIME_ENV_CMD%" >nul 2>&1
)
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
