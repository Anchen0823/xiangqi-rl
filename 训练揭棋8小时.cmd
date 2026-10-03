@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\variants\train-jieqi-8hours.ps1
pause
