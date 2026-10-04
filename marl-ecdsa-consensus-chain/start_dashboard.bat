@echo off
rem MARL-ECDSA dashboard launcher (Windows, double-click to run).
rem Uses %~dp0 so no non-ASCII path literal is embedded in this file.
cd /d "%~dp0"

set PY_EXE=C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe

if not exist "%PY_EXE%" (
  echo [ERROR] Python312 not found: %PY_EXE%
  echo Please edit PY_EXE in this file.
  pause
  exit /b 1
)

echo Starting MARL-ECDSA dashboard on http://127.0.0.1:9090 ...
start "marl-dashboard" /min "%PY_EXE%" -X utf8 start_dashboard.py

rem Wait for the server to bind the port, then open the browser.
timeout /t 6 /nobreak >nul
start "" http://127.0.0.1:9090

echo.
echo Dashboard window was started minimized (title: marl-dashboard).
echo Close that window to stop the server.
timeout /t 3 /nobreak >nul
exit /b 0
