@echo off
title Door Window Quote

python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Please install Python 3.8+ first.
    pause
    exit /b 1
)

if not exist "venv" (
    echo venv not found. Please run setup.bat first.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
if errorlevel 1 (
    echo Failed to activate venv.
    pause
    exit /b 1
)

echo Starting server...
echo Open http://localhost:8080 in your browser.
echo Press Ctrl+C to stop.
echo.

start http://localhost:8080
python app.py
pause
