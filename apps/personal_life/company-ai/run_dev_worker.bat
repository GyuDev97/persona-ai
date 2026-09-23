@echo off
setlocal
cd /d "%~dp0"

echo.
echo ========================================
echo   Company AI - Dev Worker V1
echo ========================================
echo.
echo Dashboard: http://127.0.0.1:8019
echo Stop server: Ctrl+C
echo.

"D:\python\venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8019

if errorlevel 1 (
  echo.
  echo Server stopped with an error. If port 8019 is already in use,
  echo close the existing server or use a different port.
  pause
)

endlocal
