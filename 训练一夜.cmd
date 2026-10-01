@echo off
REM Overnight accumulated training run. Safe to close this window? No - the
REM window must stay open, because closing it stops the pipeline. It is safe to
REM leave the machine alone; every stage checkpoints and is resumable, so
REM re-running this file continues where it stopped.
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\train-night.ps1" -RunName selfplay-r2 -DurationHours 7 -Accumulate -AccumName accumulated
echo.
echo Pipeline exited. Status:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\train-status.ps1" -RunName selfplay-r2
pause
