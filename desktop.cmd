@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\desktop.ps1" %*
exit /b %errorlevel%
