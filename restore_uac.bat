@echo off
chcp 65001 >nul
echo ========================================
echo   恢复 UAC 默认设置
echo ========================================
echo.
echo 此脚本将恢复 Windows UAC 默认设置
pause
echo.
echo 恢复中...

reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v "PromptOnSecureDesktop" /t REG_DWORD /d 1 /f
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v "ConsentPromptBehaviorAdmin" /t REG_DWORD /d 2 /f

if errorlevel 1 (
    echo [错误] 需要管理员权限！
    pause
    exit /b 1
)

echo.
echo ========================================
echo UAC 默认设置已恢复！
echo ========================================
echo [!] 需要重启电脑才能生效
echo.
pause
