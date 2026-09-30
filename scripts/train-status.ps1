# One-line status for an unattended training run.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\train-status.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\train-status.ps1 -RunName selfplay-r2
#
# Reads only the run's own manifests and logs, so it is safe to call while the
# pipeline is still writing them.
param([string]$RunName = '')

$root = Split-Path -Parent $PSScriptRoot
$runsRoot = Join-Path $root 'runs'
if (-not (Test-Path -LiteralPath $runsRoot)) { Write-Host 'no runs yet'; exit 0 }

if (-not $RunName) {
    $latest = Get-ChildItem -LiteralPath $runsRoot -Directory |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { Write-Host 'no runs yet'; exit 0 }
    $RunName = $latest.Name
}

$run = Join-Path $runsRoot $RunName
if (-not (Test-Path -LiteralPath $run)) { throw "run not found: $run" }
$reports = Join-Path $run 'reports'
$source = Join-Path $run 'selfplay'

Write-Host "run      : $RunName"
$runLog = Join-Path $reports 'run.log'
if (Test-Path -LiteralPath $runLog) {
    Write-Host 'stage    : last lines of run.log'
    Get-Content -LiteralPath $runLog -Tail 4 | ForEach-Object { Write-Host "  $_" }
}

$manifestPath = Join-Path $source 'manifest.json'
if (Test-Path -LiteralPath $manifestPath) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $games = if ($manifest.games -is [array]) { $manifest.games.Count } else { 0 }
    Write-Host "self-play: $games games, $($manifest.totalRecords) positions"
}

$metricsPath = Join-Path $reports 'metrics.jsonl'
if (Test-Path -LiteralPath $metricsPath) {
    $line = Get-Content -LiteralPath $metricsPath -Tail 1
    Write-Host "training : $line"
}

$summaryPath = Join-Path $reports 'summary.json'
if (Test-Path -LiteralPath $summaryPath) {
    Write-Host '--- finished ---'
    Get-Content -LiteralPath $summaryPath -Raw
}

# A live trainer is the only thing that should be holding the GPU; reporting it
# here makes a stalled run obvious without attaching to the process.
$training = Get-Process -Name python -ErrorAction SilentlyContinue |
    Where-Object { $_.StartTime -gt (Get-Date).AddHours(-12) }
if ($training) {
    Write-Host ("python   : {0} process(es), newest CPU {1:N1}s" -f @($training).Count,
        (($training | Measure-Object CPU -Maximum).Maximum))
} else {
    Write-Host 'python   : none running (finished, stopped, or not started)'
}
