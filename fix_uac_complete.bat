@echo off
chcp 65001 >nul
title 修复 UAC 弹窗显示
echo ========================================
echo   修复 UAC 弹窗 - 完整方案
echo ========================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo [错误] 请以管理员身份运行！
    pause
    exit /b 1
)

echo [1/4] 修改 UAC 显示设置...
echo       让 UAC 弹窗显示在正常桌面上
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v PromptOnSecureDesktop /t REG_DWORD /d 0 /f >nul
if errorlevel 1 (
    echo [失败] 无法修改注册表
    pause
    exit /b 1
)
echo       [OK]

echo [2/4] 设置 UAC 提示方式...
echo       使用标准用户提示（不需要密码）
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v ConsentPromptBehaviorAdmin /t REG_DWORD /d 0 /f >nul
echo       [OK]

echo [3/4] 启用 UAC...
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v EnableLUA /t REG_DWORD /d 1 /f >nul
echo       [OK]

echo [4/4] 检查设置...
for /f "tokens=3" %%a in ('reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v PromptOnSecureDesktop 2^>nul ^| findstr PromptOnSecureDesktop') do (
    if "%%a"=="0x0" (
        echo       [OK] 设置已应用
    ) else (
        echo       [警告] 设置可能未生效
    )
)

echo.
echo ========================================
echo  设置完成！请重启电脑
echo ========================================
echo.
echo 重启后效果：
echo - UAC 弹窗显示在正常桌面（非安全桌面）
echo - DXGI 可以捕获 UAC 弹窗图像
echo - 可以远程点击"是"/"否"
echo.
echo [重要] 必须重启后才能生效！
echo.
pause
