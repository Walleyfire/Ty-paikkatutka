@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Pythonia ei loytynyt.
  echo Asenna Python 3.11 tai uudempi osoitteesta:
  echo https://www.python.org/downloads/windows/
  echo Valitse asennuksessa "Add Python to PATH".
  pause
  exit /b 1
)
if not exist "config.json" (
  copy /Y "config.default.json" "config.json" >nul
  echo Luotiin config.json oletusasetuksista.
)
py -3 -m py_compile tyopaikkatutka.py job_agent.py
if errorlevel 1 (
  echo Ohjelman tarkistus epaonnistui.
  pause
  exit /b 1
)
echo.
echo Asennus tai paivitys valmis.
echo Vanha hakuhistoria sailyy data\jobs.db-tiedostossa.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0LUO_PIKAKUVAKE.ps1" -Quiet
if errorlevel 1 (
  echo Pikakuvaketta ei voitu luoda automaattisesti.
  echo Voit yrittaa myohemmin tiedostolla LUO_PIKAKUVAKE.bat.
) else (
  echo Tyopaikkatutkan pikakuvake luotiin tyopoydalle.
)
echo Kaynnistetaan Tyopaikkatutka.
call "%~dp0KAYNNISTA.bat"
