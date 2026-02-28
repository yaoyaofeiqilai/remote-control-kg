@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1

cd /d "%~dp0"
title GitHub One-Click Deploy

if /I "%~1"=="--check-only" goto :check_only

set "REMOTE_URL=%~1"
set "COMMIT_MSG=%~2"
if "%COMMIT_MSG%"=="" set "COMMIT_MSG=deploy: %DATE% %TIME%"

where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] git is not installed or not in PATH.
    pause
    exit /b 1
)

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    echo [INFO] Initializing git repository...
    git init
    if errorlevel 1 goto :fail
)

if not "%REMOTE_URL%"=="" (
    git remote get-url origin >nul 2>&1
    if errorlevel 1 (
        git remote add origin "%REMOTE_URL%"
    ) else (
        git remote set-url origin "%REMOTE_URL%"
    )
)

git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No origin remote configured.
    echo Usage: deploy_github.bat https://github.com/USER/REPO.git "commit message"
    pause
    exit /b 1
)

echo [INFO] Staging changes...
git add -A

git diff --cached --quiet
if errorlevel 1 (
    echo [INFO] Creating commit...
    git commit -m "%COMMIT_MSG%"
    if errorlevel 1 goto :fail
) else (
    echo [INFO] Nothing new to commit. Pushing current HEAD...
)

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if not defined BRANCH (
    set "BRANCH=main"
    git checkout -b !BRANCH! >nul 2>&1
)

echo [INFO] Pushing to origin/!BRANCH! ...
git push -u origin !BRANCH!
if errorlevel 1 goto :fail

echo [OK] Deployment finished.
pause
exit /b 0

:fail
echo [ERROR] Deployment failed.
pause
exit /b 1

:check_only
where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] git is not installed or not in PATH.
    exit /b 1
)
echo [OK] deploy_github.bat is ready.
exit /b 0
