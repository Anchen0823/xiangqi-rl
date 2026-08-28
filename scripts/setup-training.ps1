[CmdletBinding()]
param([string]$Python = "py -3.12")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "cuda-path.ps1")
$cuda = Find-CudaToolkit -ProjectRoot $root
if ($cuda) {
    $env:CUDA_PATH = $cuda
    $env:Path = "$(Join-Path $cuda 'bin');$env:Path"
}
$venv = Join-Path $root ".venv"
if (-not (Test-Path $venv)) {
    Invoke-Expression "$Python -m venv `"$venv`""
}
$pythonExe = Join-Path $venv "Scripts\python.exe"
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install torch==2.12.1 --index-url https://download.pytorch.org/whl/cu132
& $pythonExe -m pip install --no-deps -e (Join-Path $root "trainer")
& $pythonExe -m pip install "numpy>=2.0,<3"
& $pythonExe -m pip install "zstandard>=0.22,<1"
& $pythonExe -m xiangqi_nnue.hardware
