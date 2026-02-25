@echo off
chcp 65001 >nul
echo ========================================
echo      远程控制服务端 - 安装脚本
echo ========================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python！
    echo.
    echo 请访问以下地址下载并安装 Python 3.8 或更高版本：
    echo https://www.python.org/downloads/
    echo.
    echo 安装时请务必勾选 "Add Python to PATH"
    pause
    exit /b 1
)

echo [✓] Python 已安装
python --version
echo.

echo [1/4] 升级 pip...
python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo [警告] pip 升级失败，尝试继续...
)

echo.
echo [2/4] 安装依赖（这可能需要几分钟）...
python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败
    echo.
    echo 可能的解决方案：
    echo 1. 检查网络连接
    echo 2. 尝试使用国内镜像源：
    echo    python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo 3. 尝试逐个安装：
    echo    python -m pip install Flask Flask-SocketIO pyautogui Pillow mss
    pause
    exit /b 1
)

echo.
echo [3/4] 验证安装...
python check_install.py
if errorlevel 1 (
    echo.
    echo [警告] 验证未完全通过，但可能仍能运行
)

echo.
echo [4/4] 检查防火墙设置...
echo 请确保 Windows 防火墙允许 Python 通过（端口 5000）
echo.

echo ========================================
echo      安装完成！
echo ========================================
echo.
echo 使用方法：
echo   1. 双击 start.bat 启动服务端
echo   2. 在平板上打开浏览器
echo   3. 输入服务端显示的 IP 地址
echo.
pause
