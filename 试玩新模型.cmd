@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\play-candidate.ps1" -SkipBuild
if errorlevel 1 pause
