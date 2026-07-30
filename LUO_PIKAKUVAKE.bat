@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0LUO_PIKAKUVAKE.ps1"
if errorlevel 1 (
  echo.
  echo Pikakuvakkeen luominen epaonnistui.
  pause
  exit /b 1
)
echo.
pause
