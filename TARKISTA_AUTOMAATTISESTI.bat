@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
py -3 tyopaikkatutka.py --scan >> "logs\scheduled.log" 2>&1
