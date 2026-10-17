@echo off
chcp 65001 > nul
setlocal EnableExtensions
cd /d "%~dp0.."

if not exist "D:\python\venv\Scripts\activate.bat" (
    echo [ERROR] D:\python\venv was not found.
    echo Create it first, then install posture_alert\requirements.txt in that venv.
    pause
    exit /b 1
)

call "D:\python\venv\Scripts\activate.bat"
python -m posture_alert.main

pause
