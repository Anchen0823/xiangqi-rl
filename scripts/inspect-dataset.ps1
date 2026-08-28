[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Dataset,
    [int]$MaxRecords = 0,
    [int]$LegalitySample = 100,
    [string]$RulesEngine = 'build\native\xiangqi-engine.exe',
    [string]$Output = ''
)

# Data-quality statistics for a labeled dataset (plan phase 3 quality gate):
# score/outcome distributions, duplicate-FEN ratio, teacher-node distribution,
# and a bestmove legality spot-check against the native rules referee.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Training environment missing: $python (run scripts\setup-training.ps1)"
}
$datasetPath = Join-Path $root $Dataset
if (-not (Test-Path -LiteralPath (Join-Path $datasetPath 'manifest.json'))) {
    throw "Dataset manifest missing: $datasetPath"
}

$arguments = @(
    '-m', 'xiangqi_nnue.inspect', '--dataset', $datasetPath,
    '--legality-sample', $LegalitySample,
    '--rules-engine', (Join-Path $root $RulesEngine)
)
if ($MaxRecords -gt 0) { $arguments += '--max-records'; $arguments += $MaxRecords }
if ($Output -ne '') { $arguments += '--output'; $arguments += (Join-Path $root $Output) }

Push-Location $root
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Dataset inspection failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
