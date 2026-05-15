@echo off
rem Build a standalone Windows .exe of the biofeedback app.
rem Output: dist\Biofeedback\Biofeedback.exe  (folder distribution)
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\activate.bat (
    echo venv not found. Run setup.bat first.
    exit /b 1
)
call .venv\Scripts\activate.bat

rem Clear potentially polluting env vars
set QT_PLUGIN_PATH=
set QT_QPA_PLATFORM_PLUGIN_PATH=
set PYTHONPATH=
set PYTHONHOME=

set PY=.venv\Scripts\python.exe

%PY% -m pip install --quiet pyinstaller pillow

rem Generate icon if absent
if not exist resources\icon.ico (
    echo Generating placeholder icon resources\icon.ico ...
    %PY% resources\make_icon.py
)

rem Clean previous build artifacts
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist Biofeedback.spec del /q Biofeedback.spec

%PY% -m PyInstaller ^
    --windowed ^
    --noconfirm ^
    --icon=resources\icon.ico ^
    --name=Biofeedback ^
    --collect-all PyQt6 ^
    --collect-all sounddevice ^
    --collect-data pyqtgraph ^
    --collect-data scipy ^
    --exclude-module PyQt5 ^
    --exclude-module PySide6 ^
    --exclude-module PySide2 ^
    --exclude-module pyqtgraph.examples ^
    --exclude-module pyqtgraph.opengl ^
    --exclude-module tkinter ^
    --exclude-module matplotlib ^
    --hidden-import=serial.tools.list_ports ^
    --hidden-import=scipy.signal ^
    --hidden-import=pyqtgraph ^
    app_entry.py

if errorlevel 1 (
    echo.
    echo Build failed.
    exit /b 1
)

echo.
echo Build complete.
echo Exe at: %CD%\dist\Biofeedback\Biofeedback.exe
echo.
echo To distribute, zip the entire dist\Biofeedback\ folder.
echo Or use --onefile (edit this script) for a single .exe.
endlocal
