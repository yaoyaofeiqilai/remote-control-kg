@echo off
chcp 65001 >nul
echo ========================================
echo   手动安装脚本（逐个安装依赖）
echo ========================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python
    pause
    exit /b 1
)

echo 开始逐个安装依赖...
echo.

echo [1/8] 安装 Werkzeug...
python -m pip install Werkzeug==3.0.1
if errorlevel 1 echo [警告] Werkzeug 安装失败

echo [2/8] 安装 Flask...
python -m pip install Flask==3.0.0
if errorlevel 1 echo [警告] Flask 安装失败

echo [3/8] 安装 Flask-CORS...
python -m pip install Flask-CORS==4.0.0
if errorlevel 1 echo [警告] Flask-CORS 安装失败

echo [4/8] 安装 Flask-SocketIO...
python -m pip install Flask-SocketIO==5.3.6 python-socketio==5.9.0 python-engineio==4.8.0
if errorlevel 1 echo [警告] Flask-SocketIO 安装失败

echo [5/8] 安装 Pillow（图像处理）...
python -m pip install Pillow==10.4.0
if errorlevel 1 (
    echo [警告] 尝试安装最新版...
    python -m pip install Pillow
)
if errorlevel 1 echo [警告] Pillow 安装失败

echo [6/8] 安装 mss（屏幕捕获）...
python -m pip install mss==9.0.1
if errorlevel 1 python -m pip install mss
if errorlevel 1 echo [警告] mss 安装失败

echo [7/7] 安装 pyautogui（输入控制）...
python -m pip install pyautogui==0.9.54
if errorlevel 1 python -m pip install pyautogui
if errorlevel 1 echo [警告] pyautogui 安装失败

echo.
echo ========================================
echo   安装过程完成
echo ========================================
echo.
python check_install.py
pause
