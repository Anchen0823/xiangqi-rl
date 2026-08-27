param([ValidateSet('configure','build','test')][string]$Action = 'build')

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$cmake = 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
$ninja = 'C:\Program Files\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe'
$vcvars = 'C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat'
$buildDir = Join-Path $repoRoot 'build\native'

if (!(Test-Path -LiteralPath $cmake)) { throw "CMake not found at $cmake" }
if (!(Test-Path -LiteralPath $ninja)) { throw "Ninja not found at $ninja" }

function Invoke-InDevShell([string]$Command) {
  $output = & cmd.exe /d /s /c "`"$vcvars`" >nul && $Command"
  if ($LASTEXITCODE -ne 0) { throw "Native command failed: $Command" }
  $output
}

if ($Action -eq 'configure') {
  New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
  Invoke-InDevShell "`"$cmake`" -S `"$repoRoot\native`" -B `"$buildDir`" -G Ninja -DCMAKE_MAKE_PROGRAM=`"$ninja`" -DCMAKE_BUILD_TYPE=Release"
  exit
}

if (!(Test-Path -LiteralPath (Join-Path $buildDir 'build.ninja'))) {
  New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
  Invoke-InDevShell "`"$cmake`" -S `"$repoRoot\native`" -B `"$buildDir`" -G Ninja -DCMAKE_MAKE_PROGRAM=`"$ninja`" -DCMAKE_BUILD_TYPE=Release"
}

Invoke-InDevShell "`"$cmake`" --build `"$buildDir`" --config Release"
if ($Action -eq 'test') {
  Invoke-InDevShell "`"$cmake`" --build `"$buildDir`" --target test"
}

