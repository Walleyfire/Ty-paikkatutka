@echo off
chcp 65001 >nul
schtasks /Delete /F /TN "Tyopaikkatutka" >nul 2>nul
schtasks /Delete /F /TN "Miikan tyonhakuagentti" >nul 2>nul
echo Tyopaikkatutkan paivittainen ajo on poistettu.
pause
