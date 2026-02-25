@echo off
chcp 65001 >nul
title 远程控制服务端（管理员模式 - 支持UAC捕获）
echo ========================================
echo  远程控制服务端 - 管理员模式
echo  （支持捕获 UAC 弹窗）
echo ========================================
echo.

REM 切换到脚本所在目录
cd /d "%~dp0"

REM 检查是否以管理员身份运行
net session >nul 2>&1
if errorlevel 1 (
    echo [错误] 请以管理员身份运行此脚本！
    echo.
    echo 操作步骤：
    echo 1. 右键点击此文件
echo 2. 选择"以管理员身份运行"
    echo.
    pause
    exit /b 1
)

REM 优先使用官方 Python 3.12
if exist "C:\Program Files\Python312\python.exe" (
    set PYTHON="C:\Program Files\Python312\python.exe"
) else (
    set PYTHON=python
)

echo [✓] 管理员权限已获取
echo [✓] Python: %PYTHON%
echo.
echo [1/3] 检查依赖...
%PYTHON% -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo [警告] 依赖安装可能有问题，继续尝试启动...
)

echo [2/3] 启动服务端（DXGI模式）...
echo.
echo ========================================

%PYTHON% server.py --dxgi

pause
