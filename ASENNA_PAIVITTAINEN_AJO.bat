@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ASENNA_PAIVITTAINEN_AJO.ps1"
if errorlevel 1 (
  echo Ajastuksen luominen epaonnistui.
) else (
  echo Tyopaikkatutka tarkistaa paikat joka paiva klo 09.00.
)
pause
