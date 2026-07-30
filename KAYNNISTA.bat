@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Pythonia ei loytynyt. Asenna Python 3.11 tai uudempi.
  pause
  exit /b 1
)
if not exist "config.json" copy /Y "config.default.json" "config.json" >nul
set "PYTHONW="
for /f "delims=" %%I in ('py -3 -c "import pathlib, sys; print(pathlib.Path(sys.executable).with_name('pythonw.exe'))" 2^>nul') do set "PYTHONW=%%I"
if defined PYTHONW if exist "%PYTHONW%" (
  start "" "%PYTHONW%" "%~dp0tyopaikkatutka.py"
  exit /b 0
)
echo Pythonin ikkunakaynnistinta ei loytynyt.
echo Kaynnistetaan ohjelma komentorivi-ikkunassa virheen selvittamista varten.
py -3 tyopaikkatutka.py
if errorlevel 1 pause
