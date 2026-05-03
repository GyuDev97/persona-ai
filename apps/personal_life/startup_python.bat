@echo off
chcp 65001 > nul
setlocal EnableExtensions

set "ROOT_DIR=D:\github\persona-ai"
set "APP_DIR=%ROOT_DIR%\apps\personal_life"
set "PROJECT_VENV=%APP_DIR%\venv\Scripts\activate.bat"
set "PROJECT_PYTHON=%APP_DIR%\venv\Scripts\python.exe"
set "DEFAULT_VENV=D:\python\venv\Scripts\activate.bat"
set "DEFAULT_PYTHON=D:\python\venv\Scripts\python.exe"
set "VENV_ACTIVATE="
set "HOST=127.0.0.1"
set "PORT=8000"

echo ===============================
echo GyuVIS Python Server Launcher
echo ===============================
echo.
echo [INFO] ROOT_DIR=%ROOT_DIR%
echo [INFO] APP_DIR=%APP_DIR%
echo [INFO] App URL=http://%HOST%:%PORT%/
echo [INFO] API Docs=http://%HOST%:%PORT%/docs
echo.

echo [1/4] Moving to app directory...
cd /d "%APP_DIR%"
if errorlevel 1 (
    echo [ERROR] Could not move to APP_DIR: "%APP_DIR%"
    set "EXIT_CODE=1"
    goto :always_pause
)

echo [2/4] Activating Python environment...
if exist "%PROJECT_PYTHON%" (
    set "VENV_ACTIVATE=%PROJECT_VENV%"
    echo Using project venv: %PROJECT_VENV%
) else if exist "%DEFAULT_PYTHON%" (
    set "VENV_ACTIVATE=%DEFAULT_VENV%"
    echo Using default venv: %DEFAULT_VENV%
) else (
    echo [INFO] No venv found. Using Python from PATH.
)
if not "%VENV_ACTIVATE%"=="" call "%VENV_ACTIVATE%"

echo [3/4] Checking Python...
python --version
if errorlevel 1 (
    echo [ERROR] Python is not available in this command prompt.
    set "EXIT_CODE=1"
    goto :always_pause
)

echo [4/4] Starting server...
echo Open http://%HOST%:%PORT%/ in your browser.
echo Press Ctrl+C to stop the server.
echo.
start "" "http://%HOST%:%PORT%/"
python -m uvicorn main:app --reload --host 0.0.0.0 --port %PORT%

set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo ===============================
echo Server process stopped.
echo Exit code: %EXIT_CODE%
echo ===============================

:always_pause
echo.
echo Press any key to close this window.
pause > nul
endlocal
exit /b %EXIT_CODE%
