@echo off
chcp 65001 >nul
echo ========================================
echo   修复 UAC 弹窗显示问题
echo ========================================
echo.
echo 说明：
echo Windows 默认将 UAC 弹窗显示在"安全桌面"上，
echo 这会导致远程控制时看到黑屏。
echo.
echo 此脚本将修改设置，让 UAC 弹窗显示在正常桌面上，
echo 这样你就能在平板看到并操作 UAC 弹窗了。
echo.
echo [!] 注意：这会降低一点点安全性，但方便远程控制
pause
echo.
echo [1/2] 修改 UAC 设置...
echo.

REM 方法1：通过注册表修改，让 UAC 不在安全桌面显示
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v "PromptOnSecureDesktop" /t REG_DWORD /d 0 /f

if errorlevel 1 (
    echo [错误] 需要管理员权限！
    echo 请右键点击此文件，选择"以管理员身份运行"
    pause
    exit /b 1
)

REM 方法2：设置 UAC 级别（可选，不降低太多安全性）
REM 值为：0=从不通知，1=仅当应用尝试更改时通知（不降低桌面），2=始终通知
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v "ConsentPromptBehaviorAdmin" /t REG_DWORD /d 1 /f

echo [2/2] 设置完成！
echo.
echo ========================================
echo 修改内容：
echo - UAC 弹窗将显示在正常桌面上（而非安全桌面）
echo - 你可以看到并点击"是"/"否"按钮
echo ========================================
echo.
echo [!] 需要重启电脑才能生效
echo.
pause
