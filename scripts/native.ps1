param([ValidateSet('configure','build','test')][string]$Action = 'build')

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (!(Test-Path -LiteralPath $vswhere)) { throw "vswhere not found at $vswhere" }
$vsRoot = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (!$vsRoot) { throw 'Visual Studio C++ tools not found' }
$bundledCmake = Join-Path $vsRoot 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
$bundledNinja = Join-Path $vsRoot 'Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe'
$cmakeCommand = Get-Command cmake -ErrorAction SilentlyContinue
$ninjaCommand = Get-Command ninja -ErrorAction SilentlyContinue
$cmake = if ($cmakeCommand) { $cmakeCommand.Source } else { $bundledCmake }
$ninja = if ($ninjaCommand) { $ninjaCommand.Source } else { $bundledNinja }
$vcvars = Join-Path $vsRoot 'VC\Auxiliary\Build\vcvars64.bat'
$buildDir = Join-Path $repoRoot 'build\native'

if (!(Test-Path -LiteralPath $cmake)) { throw "CMake not found at $cmake" }
if (!(Test-Path -LiteralPath $ninja)) { throw "Ninja not found at $ninja" }
if (!(Test-Path -LiteralPath $vcvars)) { throw "MSVC environment not found at $vcvars" }

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
