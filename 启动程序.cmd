@echo off
setlocal
cd /d "%~dp0"

set "PY312W=%LocalAppData%\Programs\Python\Python312\pythonw.exe"
set "PY313W=%LocalAppData%\Programs\Python\Python313\pythonw.exe"
set "BUNDLED_PYTHONW=C:\Users\arthu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"

if exist "%PY312W%" goto py312
if exist "%PY313W%" goto py313

where pyw >nul 2>nul
if not errorlevel 1 goto pylauncher

where pythonw >nul 2>nul
if not errorlevel 1 goto systempython

if exist "%BUNDLED_PYTHONW%" goto bundled

call "%~dp0start.bat"
exit /b %errorlevel%

:py312
start "" /b "%PY312W%" "%~dp0app.py"
exit /b 0

:py313
start "" /b "%PY313W%" "%~dp0app.py"
exit /b 0

:pylauncher
start "" /b pyw -3 "%~dp0app.py"
exit /b 0

:systempython
start "" /b pythonw "%~dp0app.py"
exit /b 0

:bundled
start "" /b "%BUNDLED_PYTHONW%" "%~dp0app.py"
exit /b 0
