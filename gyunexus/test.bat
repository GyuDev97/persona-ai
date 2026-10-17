@echo off
rem Runs backend tests (pytest) and the frontend type check.
setlocal
cd /d "%~dp0"
set "PY=D:\python\venv\Scripts\python.exe"

pushd backend
"%PY%" -m pytest -q
set RC=%errorlevel%
popd
pushd frontend
call npm run typecheck
if errorlevel 1 set RC=1
popd
pause
exit /b %RC%
