@echo off
rem MARL-ECDSA dashboard launcher (Windows, double-click to run).
rem Uses %~dp0 so no non-ASCII path literal is embedded in this file.
cd /d "%~dp0"

rem Resolve Python interpreter: PATH first, then the py launcher.
rem (Never hard-code a developer machine path here.)
set "PY_EXE="
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY_EXE set "PY_EXE=%%P"
if not defined PY_EXE (
  for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY_EXE=%%P"
)
if not defined PY_EXE (
  echo [ERROR] Python 3.10+ not found in PATH.
  echo Install Python or edit PY_EXE in this file to point at python.exe.
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
