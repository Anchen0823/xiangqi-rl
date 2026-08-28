[CmdletBinding()]
param([switch]$SkipBuild)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$teacher = Join-Path $root 'native\bin\fairy-stockfish-teacher.exe'
$nodeModules = Join-Path $root 'node_modules'

if (-not (Test-Path -LiteralPath $nodeModules)) {
    throw 'Node dependencies are missing. Run npm install first.'
}
if (-not (Test-Path -LiteralPath $teacher)) {
    throw 'CC0 teacher is missing. Run scripts\install-teacher.ps1 first.'
}

$env:XIANGQI_PIKAFISH_PATH = $teacher
$env:XIANGQI_EMBEDDED_NNUE = '1'
$env:XIANGQI_UCI_VARIANT = 'xiangqi'
$env:XIANGQI_SEARCH_BACKEND = 'cc0-teacher'

Push-Location $root
try {
    if (-not $SkipBuild) { & npm.cmd run native:build }
    if ($LASTEXITCODE -ne 0) { throw "Native build failed with exit code $LASTEXITCODE" }
    Write-Host 'Starting Xiangqi RL with the pinned CC0 teacher AI...'
    Write-Host 'Close the Electron window or press Ctrl+C here to stop.'
    & npm.cmd run dev
    if ($LASTEXITCODE -ne 0) { throw "Desktop app exited with code $LASTEXITCODE" }
} finally {
    Pop-Location
}
