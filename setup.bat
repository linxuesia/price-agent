@echo off
title Door Window Quote - Setup

echo ========================================
echo   Door Window Quote Assistant
echo   Installing...
echo ========================================
echo.

:: Check Python
python --version >nul 2>&1
if not errorlevel 1 goto :HavePython

echo Python not found. Downloading installer...
echo.

set "PYEXE=%TEMP%\python-installer.exe"
powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile '%PYEXE%'" 2>nul

if not exist "%PYEXE%" (
    echo Download failed. Opening download page instead...
    start https://www.python.org/downloads/
    echo.
    echo Please install Python manually ^(check "Add Python to PATH"^),
    echo then re-run setup.bat.
    pause
    exit /b 1
)

echo Installing Python - this may take a minute...
"%PYEXE%" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
del "%PYEXE%" 2>nul

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo Python installed but needs a restart to refresh PATH.
    echo Please RESTART your computer, then run setup.bat again.
    pause
    exit /b 1
)
echo Python installed successfully!
echo.

:HavePython
echo [OK] Python found:
python --version
echo.

:: Create venv
if not exist "venv" (
    echo Creating venv...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv.
        pause
        exit /b 1
    )
)

:: Install packages
echo Installing packages...
call venv\Scripts\activate.bat
pip install --upgrade pip -q 2>nul
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Install failed. Check your network.
    pause
    exit /b 1
)

:: Install Chromium
echo.
echo Installing Chromium...
python -m playwright install chromium 2>nul
if errorlevel 1 (
    echo [WARNING] Chromium install failed.
    echo Images may not be generated.
)

echo.
echo ========================================
echo   Setup complete!
echo ========================================
echo.
echo Next step: double-click run.bat
echo Then open: http://localhost:8080
echo.
pause
