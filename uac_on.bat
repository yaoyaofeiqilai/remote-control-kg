@echo off
chcp 65001 >nul
title 恢复 UAC
echo ========================================
echo      恢复 UAC 默认设置
echo ========================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo [错误] 请以管理员身份运行！
    pause
    exit /b 1
)

echo [1/2] 正在恢复 UAC...
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v EnableLUA /t REG_DWORD /d 1 /f >nul
if errorlevel 1 (
    echo [失败] 无法修改注册表
    pause
    exit /b 1
)

echo [2/2] 设置完成！
echo.
echo ========================================
echo  UAC 已恢复，重启电脑后生效
echo ========================================
echo.
pause
