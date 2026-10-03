@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist dist\renderer\index.html (
  call npm.cmd run lab:build
  if errorlevel 1 goto failed
)
node scripts\serve-lab.mjs --open
if errorlevel 1 goto failed
exit /b 0
:failed
echo 变体实验室启动失败，请查看上方错误。
pause
