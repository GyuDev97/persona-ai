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

echo ===============================
echo GW Assistant Python Server Start
echo ===============================
echo.

echo [INFO] ROOT_DIR=%ROOT_DIR%
echo [INFO] APP_DIR=%APP_DIR%
echo [INFO] UI=http://%HOST%:%PORT%/
echo [INFO] Docs=http://%HOST%:%PORT%/docs
echo.

echo [1/4] Move to app directory
cd /d "%APP_DIR%"
if errorlevel 1 (
    echo ERROR: Failed to change directory to "%APP_DIR%".
    set "EXIT_CODE=1"
    goto :always_pause
)

echo [2/4] Activate virtual environment
if exist "%PROJECT_PYTHON%" (
    echo Using project venv: %PROJECT_VENV%
    call "%PROJECT_VENV%"
) else if exist "%PROJECT_VENV%" (
    echo Project venv exists but python.exe is missing. Skipping broken project venv.
) else if exist "%DEFAULT_PYTHON%" (
    echo Using default venv: %DEFAULT_VENV%
    call "%DEFAULT_VENV%"
) else if exist "%DEFAULT_VENV%" (
    echo Default venv exists but python.exe is missing. Skipping broken default venv.
) else (
    echo INFO: No venv found. Continuing with current Python environment.
)

echo [3/4] Check Python
python --version
if errorlevel 1 (
    echo ERROR: Python is not available in this command prompt.
    echo Hint: recreate the venv with a currently installed Python, or install Python and add it to PATH.
    set "EXIT_CODE=1"
    goto :always_pause
)

echo [4/4] Run server
echo UI will open at http://%HOST%:%PORT%/
echo Press Ctrl+C to stop the server.
echo This window will stay open after the server stops.
echo.
start "" "http://%HOST%:%PORT%/"
python -m uvicorn main:app --reload --host 0.0.0.0 --port %PORT%

set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo ===============================
echo Server process ended.
echo Exit code: %EXIT_CODE%
echo Check the messages above for details.
echo ===============================

:always_pause
echo.
echo Press any key to close this window.
pause > nul
endlocal
exit /b %EXIT_CODE%
