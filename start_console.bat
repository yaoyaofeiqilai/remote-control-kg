@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

cd /d "%~dp0"
title 远程控制服务端控制台启动器

call :resolve_python
if errorlevel 1 (
    echo [错误] 未找到 Python 3.12 及以上版本。
    pause
    exit /b 1
)

echo [信息] 当前 Python 运行时：
call %PY_CMD% --version

echo [信息] 正在检查桌面控制台依赖...
call %PY_CMD% -c "import flask, flask_socketio, flask_cors, pyautogui, PIL, mss, numpy, sounddevice, pycaw, comtypes, aiortc, av, aiohttp, webview" >nul 2>&1
if errorlevel 1 (
    echo [警告] 检测到缺少依赖，正在根据 requirements.txt 安装...
    call %PY_CMD% -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败。
        pause
        exit /b 1
    )
)

echo [信息] 正在启动原生桌面控制台...
start "" /B %PYW_CMD% "%~dp0start_console.pyw"
exit /b 0

:resolve_python
set "PY_CMD="
set "PYW_CMD="

if exist "C:\Program Files\Python312\python.exe" (
    set "PY_CMD="C:\Program Files\Python312\python.exe""
    set "PYW_CMD="C:\Program Files\Python312\pythonw.exe""
    exit /b 0
)

if exist "C:\Python312\python.exe" (
    set "PY_CMD="C:\Python312\python.exe""
    set "PYW_CMD="C:\Python312\pythonw.exe""
    exit /b 0
)

python --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python"
)

pythonw --version >nul 2>&1
if not errorlevel 1 (
    set "PYW_CMD=pythonw"
)

if defined PY_CMD if defined PYW_CMD exit /b 0
exit /b 1
