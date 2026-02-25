@echo off
chcp 65001 >nul
title 临时关闭 UAC
echo ========================================
echo      临时关闭 UAC（用于游戏）
echo ========================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo [错误] 请以管理员身份运行！
    pause
    exit /b 1
)

echo [1/2] 正在关闭 UAC...
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v EnableLUA /t REG_DWORD /d 0 /f >nul
if errorlevel 1 (
    echo [失败] 无法修改注册表
    pause
    exit /b 1
)

echo [2/2] 设置完成！
echo.
echo ========================================
echo  UAC 已关闭，重启电脑后生效
echo ========================================
echo.
echo 重启后：
echo - 平板可以看到所有弹窗
echo - 玩游戏时不会再有 UAC 中断
echo.
echo [重要] 游戏结束后请运行 uac_on.bat 恢复
echo.
pause
