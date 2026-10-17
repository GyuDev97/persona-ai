@echo off
rem Dev mode: backend (--reload, port 8000) and frontend (Vite, port 5173) in separate windows.
setlocal
cd /d "%~dp0"
set "PY=D:\python\venv\Scripts\python.exe"

if not exist "frontend\node_modules" (
  pushd frontend
  call npm install
  popd
)
start "GyuNexus backend" cmd /k "cd /d %~dp0backend && %PY% -m uvicorn gyunexus.main:create_app --factory --reload --port 8000"
start "GyuNexus frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
start "" cmd /c "timeout /t 4 >nul & start http://localhost:5173"
