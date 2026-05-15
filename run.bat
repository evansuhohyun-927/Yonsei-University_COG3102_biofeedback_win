@echo off
rem Launch the biofeedback app (Windows)
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\activate.bat (
    echo venv not found. Run setup.bat first.
    exit /b 1
)

call .venv\Scripts\activate.bat

rem Clear potentially conflicting Qt env vars (in case conda or another Python is active)
set QT_PLUGIN_PATH=
set QT_QPA_PLATFORM_PLUGIN_PATH=

rem Point Qt to the venv's PyQt6 plugins
for /f "delims=" %%i in ('python -c "import os, PyQt6; print(os.path.join(os.path.dirname(PyQt6.__file__), 'Qt6', 'plugins'))"') do set QT_QPA_PLATFORM_PLUGIN_PATH=%%i

python -m biofeedback.main %*
endlocal
