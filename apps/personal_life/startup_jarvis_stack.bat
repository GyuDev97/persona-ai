@echo off
chcp 65001 > nul
setlocal EnableExtensions
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "ROOT_DIR=D:\github\persona-ai"
set "APP_DIR=%ROOT_DIR%\apps\personal_life"
set "PROJECT_VENV=%APP_DIR%\venv\Scripts\activate.bat"
set "PROJECT_PYTHON=%APP_DIR%\venv\Scripts\python.exe"
set "DEFAULT_VENV=D:\python\venv\Scripts\activate.bat"
set "DEFAULT_PYTHON=D:\python\venv\Scripts\python.exe"
set "PYTHON_BOOT="
set "HOST=127.0.0.1"
set "PORT=8000"

set "GYUVIS_TTS_BACKEND=edge"
set "GYUVIS_TTS_ALLOW_FALLBACK=0"
set "GYUVIS_EDGE_TTS_VOICE=ko-KR-InJoonNeural"
set "GYUVIS_EDGE_TTS_RATE=+12%%"
set "GYUVIS_EDGE_TTS_PITCH=-8Hz"
set "GYUVIS_JARVIS_HUD_URL=http://127.0.0.1:%PORT%/gyuvis/standby-v3?boot=veil^&veil=1^&autoGesture=1^&autoPresence=1^&voiceWelcome=0"
set "GYUVIS_HUD_AUTO_ALLOW_CAMERA=1"
set "GYUVIS_AGENT1_START_TIME=06:00"
set "GYUVIS_AGENT1_END_TIME=23:00"
set "GYUVIS_AGENT1_COLLECT_INTERVAL_SECONDS=600"
set "GYUVIS_FOLLOWUP_RECORD_SECONDS=8"
set "GYUVIS_FOLLOWUP_MAX_RECORD_SECONDS=14"
set "GYUVIS_FOLLOWUP_SILENCE_SECONDS=1.2"
set "GYUVIS_FOLLOWUP_VOICE_THRESHOLD=0.018"
set "GYUVIS_DEBUG_AUDIO=1"
rem Use the stable MME microphone-array device, not the unreliable WDM-KS input.
set "GYUVIS_INPUT_DEVICE=mme-default"

echo ===============================
echo GyuVIS Stack Launcher
echo ===============================
echo.
echo [INFO] APP_DIR=%APP_DIR%
echo [INFO] Server=http://%HOST%:%PORT%/
echo [INFO] TTS=%GYUVIS_TTS_BACKEND% voice=%GYUVIS_EDGE_TTS_VOICE% rate=%GYUVIS_EDGE_TTS_RATE% pitch=%GYUVIS_EDGE_TTS_PITCH%
echo [INFO] Agent01 news window=%GYUVIS_AGENT1_START_TIME%-%GYUVIS_AGENT1_END_TIME% interval=%GYUVIS_AGENT1_COLLECT_INTERVAL_SECONDS%s
echo.

if not exist "%APP_DIR%" (
    echo [ERROR] APP_DIR not found: "%APP_DIR%"
    set "EXIT_CODE=1"
    goto :always_pause
)

echo [1/4] Checking Python environment...
if exist "%PROJECT_PYTHON%" (
    set "PYTHON_BOOT=call ""%PROJECT_VENV%"" && "
    echo Using project venv: %PROJECT_VENV%
) else if exist "%DEFAULT_PYTHON%" (
    set "PYTHON_BOOT=call ""%DEFAULT_VENV%"" && "
    echo Using default venv: %DEFAULT_VENV%
) else (
    echo [INFO] No venv found. Using Python from PATH.
)
%PYTHON_BOOT%python --version
if errorlevel 1 (
    echo [ERROR] Python is not available.
    set "EXIT_CODE=1"
    goto :always_pause
)

echo [2/4] Starting API server window...
start "GyuVIS API Server" cmd /k "cd /d ""%APP_DIR%"" && %PYTHON_BOOT%python -m uvicorn main:app --reload --host 0.0.0.0 --port %PORT%"

echo [3/4] Starting PC agent runner window...
start "GyuVIS PC Agent Runner" cmd /k "cd /d ""%APP_DIR%"" && %PYTHON_BOOT%python pc_agent_runner.py"

echo [4/4] Starting PC wake listener window...
start "GyuVIS PC Wake Listener" cmd /k "cd /d ""%APP_DIR%"" && %PYTHON_BOOT%python pc_wake_listener.py"

echo.
echo Waiting for API health check...
set "HEALTH_OK=0"
for /l %%I in (1,1,12) do (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing 'http://%HOST%:%PORT%/health' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch { exit 1 }"
    if not errorlevel 1 (
        set "HEALTH_OK=1"
        goto :open_ui
    )
    timeout /t 1 /nobreak > nul
)
echo [WARN] API health check did not respond yet. Opening UI anyway.

:open_ui
start "" "http://%HOST%:%PORT%/"

set "EXIT_CODE=0"
echo.
echo ===============================
echo Launch requests were sent.
echo Close each console window to stop its component.
echo ===============================

:always_pause
echo.
echo Press any key to close this launcher window.
pause > nul
endlocal
exit /b %EXIT_CODE%
