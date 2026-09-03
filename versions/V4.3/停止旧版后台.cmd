@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Stop Industry Screener

if exist "%~dp0data\server.pid" (
  set /p SAVED_PID=<"%~dp0data\server.pid"
  if defined SAVED_PID taskkill /PID !SAVED_PID! /F >nul 2>nul
)

for %%R in (8765 8766) do (
  for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%%R" ^| findstr "LISTENING"') do (
    echo Stopping Industry Screener on port %%R, PID %%P...
    taskkill /PID %%P /F >nul 2>nul
  )
)

echo Done. You can now run 启动程序.cmd again.
timeout /t 2 /nobreak >nul
