@echo off
REM ============================================================
REM PsychoPy 실험 직접 실행 (Builder UI 없이)
REM
REM Builder가 안 열리거나 Run 버튼이 안 보일 때 사용.
REM 이 .bat을 더블클릭하면 .psyexp를 .py로 컴파일 후 바로 실행.
REM ============================================================

setlocal

set "PSYCHOPY=C:\Program Files\PsychoPy\python.exe"
set "PSYEXP=%~dp0psychopy_experiment\fNIRS_HeartFeedback.psyexp"
set "COMPILED=%~dp0psychopy_experiment\fNIRS_HeartFeedback_lastrun.py"

if not exist "%PSYCHOPY%" (
    echo [ERROR] PsychoPy not found at: %PSYCHOPY%
    echo Please edit run_experiment.bat to set the correct path.
    pause
    exit /b 1
)
if not exist "%PSYEXP%" (
    echo [ERROR] .psyexp not found at: %PSYEXP%
    pause
    exit /b 1
)

echo === Step 1/2: .psyexp -^> .py 컴파일 ===
"%PSYCHOPY%" -c "from psychopy.experiment import Experiment; e=Experiment(); e.loadFromXML(r'%PSYEXP%'); s=e.writeScript(r'%COMPILED%'); open(r'%COMPILED%','w',encoding='utf-8').write(str(s)) if s else None; print('compiled OK')"
if errorlevel 1 (
    echo [ERROR] compile failed
    pause
    exit /b 1
)

echo.
echo === Step 2/2: 실험 실행 ===
echo (참가자 정보 다이얼로그가 떠야 정상)
echo.
cd /d "%~dp0psychopy_experiment"
"%PSYCHOPY%" "%COMPILED%"

if errorlevel 1 (
    echo.
    echo [ERROR] 실행 중 오류 발생
    pause
)
endlocal
