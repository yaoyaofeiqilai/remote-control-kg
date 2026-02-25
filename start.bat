@echo off
chcp 65001 >nul
title 远程控制服务端
echo ========================================
echo      远程控制服务端启动器
echo ========================================
echo.

REM 切换到脚本所在目录
cd /d "%~dp0"

REM 优先使用官方 Python 3.12
if exist "C:\Program Files\Python312\python.exe" (
    set PYTHON="C:\Program Files\Python312\python.exe"
) else (
    set PYTHON=python
)

REM 检查 Python
%PYTHON% --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

echo [1/3] 使用 Python:
%PYTHON% --version

echo [2/3] 检查依赖...
%PYTHON% -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo [警告] 依赖安装可能有问题，继续尝试启动...
)

echo [3/3] 启动服务端...
echo.

%PYTHON% server.py

pause
