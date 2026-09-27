@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul || (echo Please install Python 3.12 first. & pause & exit /b 1)
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (pause & exit /b 1)
if not exist .env .venv\Scripts\python.exe scripts\setup.py
if errorlevel 1 (pause & exit /b 1)
echo Open http://localhost:8787 in your browser.
.venv\Scripts\python.exe app.py
pause
