@echo off
cd /d "%~dp0"

echo Running setup...
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\setup-backend.ps1"
if errorlevel 1 (
    echo Setup failed.
    pause
    exit /b 1
)

echo Starting arena UI...
powershell -ExecutionPolicy Bypass -NoExit -File "%~dp0scripts\run-remote-ui.ps1"
