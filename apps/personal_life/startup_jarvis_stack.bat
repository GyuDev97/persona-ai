@echo off
chcp 65001 > nul
setlocal

set "ROOT_DIR=D:\github\persona-ai"
set "APP_DIR=%ROOT_DIR%\apps\personal_life"
set "PROJECT_VENV=%APP_DIR%\venv\Scripts\activate.bat"
set "PROJECT_PYTHON=%APP_DIR%\venv\Scripts\python.exe"
set "DEFAULT_VENV=D:\python\venv\Scripts\activate.bat"
set "DEFAULT_PYTHON=D:\python\venv\Scripts\python.exe"
set "HOST=127.0.0.1"
set "PORT=8000"
set "GYUVIS_TTS_BACKEND=edge"
set "GYUVIS_TTS_ALLOW_FALLBACK=0"
set "GYUVIS_EDGE_TTS_VOICE=ko-KR-InJoonNeural"
set "GYUVIS_EDGE_TTS_RATE=+12%%"
set "GYUVIS_EDGE_TTS_PITCH=-8Hz"
set "GYUVIS_JARVIS_HUD_URL=http://127.0.0.1:%PORT%/gyuvis/standby-v2"
set "GYUVIS_HUD_AUTO_ALLOW_CAMERA=1"

echo ===============================
echo GyuVIS JARVIS Stack Launcher
echo ===============================
echo.
echo [INFO] APP_DIR=%APP_DIR%
echo [INFO] Server=http://%HOST%:%PORT%/
echo [INFO] Wake TTS=%GYUVIS_TTS_BACKEND% voice=%GYUVIS_EDGE_TTS_VOICE% rate=%GYUVIS_EDGE_TTS_RATE% pitch=%GYUVIS_EDGE_TTS_PITCH%
echo.

if not exist "%APP_DIR%" (
    echo ERROR: APP_DIR not found: "%APP_DIR%"
    set "EXIT_CODE=1"
    goto :always_pause
)

echo [1/4] Selecting Python environment
if exist "%PROJECT_PYTHON%" (
    set "PYTHON_BOOT=call ""%PROJECT_VENV%"""
    echo Using project venv: %PROJECT_VENV%
) else if exist "%DEFAULT_PYTHON%" (
    set "PYTHON_BOOT=call ""%DEFAULT_VENV%"""
    echo Using default venv: %DEFAULT_VENV%
) else (
    set "PYTHON_BOOT=python --version"
    echo INFO: No venv found. Each window will use Python from PATH.
)

echo [2/4] Starting API server window
start "GyuVIS API Server" cmd /k "cd /d ""%APP_DIR%"" && %PYTHON_BOOT% && python -m uvicorn main:app --reload --host 0.0.0.0 --port %PORT%"

echo [3/4] Starting PC agent runner window
start "GyuVIS PC Agent Runner" cmd /k "cd /d ""%APP_DIR%"" && %PYTHON_BOOT% && python pc_agent_runner.py"

echo [4/4] Starting PC wake listener window
start "GyuVIS PC Wake Listener" cmd /k "cd /d ""%APP_DIR%"" && %PYTHON_BOOT% && python pc_wake_listener.py"

echo.
echo Waiting briefly before opening UI...
timeout /t 3 /nobreak > nul
start "" "http://%HOST%:%PORT%/"

set "EXIT_CODE=0"
echo.
echo ===============================
echo Launch requests sent.
echo Close each opened console window to stop that component.
echo ===============================

:always_pause
echo.
echo Press any key to close this launcher window.
pause > nul
endlocal
exit /b %EXIT_CODE%
