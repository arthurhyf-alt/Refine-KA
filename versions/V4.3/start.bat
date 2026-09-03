@echo off
setlocal
cd /d "%~dp0"

set "PY312=%LocalAppData%\Programs\Python\Python312\python.exe"
set "PY313=%LocalAppData%\Programs\Python\Python313\python.exe"
set "BUNDLED_PYTHON=C:\Users\arthu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%PY312%" goto py312
if exist "%PY313%" goto py313

where py >nul 2>nul
if not errorlevel 1 goto pylauncher

where python >nul 2>nul
if not errorlevel 1 goto systempython

if exist "%BUNDLED_PYTHON%" goto bundled

echo.
echo START FAILED: Python 3 was not found.
echo Run the Python installer helper first.
echo.
pause
exit /b 1

:py312
"%PY312%" app.py
goto finished

:py313
"%PY313%" app.py
goto finished

:pylauncher
py -3 app.py
goto finished

:systempython
python app.py
goto finished

:bundled
"%BUNDLED_PYTHON%" app.py
goto finished

:finished
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo START FAILED: the application stopped with an error.
echo Please take a screenshot of this window.
echo.
pause
exit /b 1
