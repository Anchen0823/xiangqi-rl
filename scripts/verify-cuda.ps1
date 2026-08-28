[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$systemCuda = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2"
$localCuda = Join-Path $root ".cuda\v13.2"
$cuda = if ($env:CUDA_PATH -and (Test-Path (Join-Path $env:CUDA_PATH "bin\nvcc.exe"))) {
    $env:CUDA_PATH
} elseif (Test-Path (Join-Path $systemCuda "bin\nvcc.exe")) {
    $systemCuda
} else {
    $localCuda
}
$nvcc = Join-Path $cuda "bin\nvcc.exe"
if (-not (Test-Path $nvcc)) { throw "CUDA 13.2 nvcc not found at $nvcc" }
$env:CUDA_PATH = $cuda
$env:Path = "$(Join-Path $cuda 'bin');$env:Path"
Write-Host "Using CUDA from $cuda"
& $nvcc --version
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vcvars = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -find VC\Auxiliary\Build\vcvars64.bat
if (-not $vcvars) { throw "MSVC x64 compiler environment not found" }
$output = Join-Path $root "build\cuda-smoke"
New-Item -ItemType Directory -Force $output | Out-Null
$source = Join-Path $root "trainer\cuda\device_smoke.cu"
$binary = Join-Path $output "device_smoke.exe"
cmd /d /s /c "`"$vcvars`" && `"$nvcc`" -std=c++17 -O2 `"$source`" -o `"$binary`""
if ($LASTEXITCODE -ne 0) { throw "nvcc compilation failed with exit code $LASTEXITCODE" }
& $binary
if ($LASTEXITCODE -ne 0) { throw "CUDA device smoke test failed with exit code $LASTEXITCODE" }
