@echo off
rem GyuNexus launcher: installs/builds if needed, starts the server, opens the browser.
rem URL: http://127.0.0.1:8000   (ASCII only on purpose: cmd breaks on UTF-8 text in .bat files)
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [ERROR] Python not found: %PY%
  echo Edit the PY line at the top of start.bat.
  pause
  exit /b 1
)
if not exist ".env" (
  echo [INFO] .env not found. Copying .env.example - set OPENAI_API_KEY and save.
  copy ".env.example" ".env" >nul
  notepad ".env"
)

"%PY%" -c "import gyunexus" 2>nul
if errorlevel 1 (
  echo [GyuNexus] Installing backend packages...
  "%PY%" -m pip install -e "backend[dev]"
  if errorlevel 1 (
    pause
    exit /b 1
  )
)
if not exist "frontend\dist\index.html" (
  echo [GyuNexus] Building dashboard...
  pushd frontend
  if not exist node_modules call npm install
  call npm run build
  if errorlevel 1 (
    popd
    pause
    exit /b 1
  )
  popd
)

start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000"
cd backend
"%PY%" -m uvicorn gyunexus.main:create_app --factory --host 0.0.0.0 --port 8000
pause
