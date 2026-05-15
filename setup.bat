@echo off
rem Create virtual environment and install dependencies (Windows)
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python not found on PATH. Install Python 3.11+ from python.org and re-run.
    exit /b 1
)

if not exist .venv (
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create venv.
        exit /b 1
    )
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo Setup complete. Run with:
echo   run.bat
endlocal
