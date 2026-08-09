@echo off
title Install Rust AutoConnect Requirements
color 0A
echo ===================================================
echo Installing required Python libraries...
echo ===================================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ and check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: Install requirements
pip install -r requirements.txt
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo [ERROR] Failed to install some libraries. Check the errors above.
    pause
    exit /b 1
)

echo.
echo ===================================================
echo [SUCCESS] All libraries installed successfully!
echo You can now run main.py or start the app.
echo ===================================================
pause
exit /b 0
