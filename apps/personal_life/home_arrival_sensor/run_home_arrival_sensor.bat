@echo off
chcp 65001 > nul
setlocal EnableExtensions
cd /d "%~dp0.."

if exist "D:\python\venv\Scripts\python.exe" (
    "D:\python\venv\Scripts\python.exe" -m home_arrival_sensor.main
) else (
    python -m home_arrival_sensor.main
)

pause
