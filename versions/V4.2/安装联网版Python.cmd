@echo off
setlocal
title Install network-enabled Python

echo Opening the official Python 3.12.10 installer...
echo.
echo In the installer:
echo 1. Check "Add python.exe to PATH".
echo 2. Click "Install Now".
echo 3. After installation, close this window and run "切换到联网版.cmd".
echo.
start "" "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
pause
