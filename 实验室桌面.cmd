@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist dist-electron\main\index.cjs (
  call npm.cmd run build
  if errorlevel 1 goto failed
)
set XQLAB_MODE=lab
call npm.cmd start
if errorlevel 1 goto failed
exit /b 0
:failed
echo 桌面入口启动失败，请查看上方错误。
pause
