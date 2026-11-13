@echo off
setlocal
cd /d "%~dp0"

echo ===================================================
echo   LAPTOP AI - Personal Agentic Runtime Launcher
echo ===================================================
echo Starting LAPTOP AI on local ThinkPad...
echo.

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0start_laptop_ai.ps1"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Launcher failed with exit code %ERRORLEVEL%.
    pause
)

