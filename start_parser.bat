@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Python virtual environment not found.
    echo Run install_windows.bat first.
    pause
    exit /b 1
)

echo Starting MQTT SQL Bridge Parser...
".venv\Scripts\python.exe" main.py

echo.
echo Parser stopped. Exit code: %ERRORLEVEL%
pause
