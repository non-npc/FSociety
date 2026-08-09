@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python 3.12 or newer is required to run the uncompiled client.
    echo Download it from: https://www.python.org/downloads/
    exit /b 1
)

python main.py %*

if errorlevel 1 (
    echo.
    echo fsociety failed to start. Install dependencies with:
    echo     python -m pip install -r requirements.txt
    exit /b 1
)
