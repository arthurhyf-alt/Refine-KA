@echo off
setlocal
cd /d "%~dp0"

set "PYTHONW=%LocalAppData%\Programs\Python\Python312\pythonw.exe"
if not exist "%PYTHONW%" set "PYTHONW=%LocalAppData%\Programs\Python\Python313\pythonw.exe"

if not exist "%PYTHONW%" goto missing

for %%P in (8765 8766) do (
  for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P " ^| findstr "LISTENING"') do taskkill /PID %%A /F >nul 2>nul
)

start "" /b "%PYTHONW%" "%~dp0app.py"
timeout /t 2 /nobreak >nul
curl.exe --silent --request POST "http://127.0.0.1:8766/api/pipeline/run" >nul 2>nul
start "" "http://127.0.0.1:8766"
exit /b 0

:missing
echo.
echo Python 3.12 was not found.
echo Please run INSTALL_NETWORK_PYTHON.cmd and finish the installation first.
echo.
pause
exit /b 1
