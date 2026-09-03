@echo off
setlocal
cd /d "%~dp0"
set "BUNDLED_PYTHON=C:\Users\arthu\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%BUNDLED_PYTHON%" goto missing
"%BUNDLED_PYTHON%" pipeline.py
if errorlevel 1 goto failed
echo Pipeline completed.
exit /b 0
:missing
echo Python runtime was not found.
pause
exit /b 1
:failed
echo Pipeline failed. Please take a screenshot.
pause
exit /b 1

