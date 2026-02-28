@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

cd /d "%~dp0"
title Remote Control Server (Admin)

net session >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~dp0start.bat' -Verb RunAs -ArgumentList '_elevated %*'"
    if errorlevel 1 (
        echo [ERROR] Elevation cancelled.
        pause
        exit /b 1
    )
    exit /b 0
)

call "%~dp0start.bat" _elevated %*
exit /b %ERRORLEVEL%
