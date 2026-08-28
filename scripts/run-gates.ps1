[CmdletBinding()]
param(
    [string]$CandidateEngine = 'native\bin\pikafish.exe',
    [string]$CandidateEvalFile = 'checkpoints\candidate-101.nnue',
    [string]$CandidateName = 'pikafish',
    [string]$TeacherEngine = 'native\bin\fairy-stockfish-teacher.exe',
    [string]$BaselineEngine = 'build\native\xiangqi-engine.exe',
    [string]$RulesEngine = 'build\native\xiangqi-engine.exe',
    [int]$BaselineDepth = 3,
    [int]$Gate1Games = 800,
    [int]$Gate2Games = 400,
    [int]$Nodes = 5000,
    [int]$MaxPlies = 240,
    [int]$OpeningPlies = 8,
    [int]$Seed = 20260828,
    [int]$TimeoutSeconds = 60,
    [string]$OutDir = '',
    [switch]$SkipGate1,
    [switch]$SkipGate2,
    [switch]$SkipTactical
)

# One-command strength gates from docs/strength-protocol.md. Runs artifact
# verification first, then Gate 1 (candidate vs calibrated baseline, 800 games,
# 95% Wilson lower bound > 60%), Gate 2 (candidate vs strong CC0 teacher at equal
# nodes, 400 games, lower bound >= 20%), and the tactical suite when present.
# Writes an audit report to $OutDir; fails when any enabled gate fails.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Training environment missing: $python (run scripts\setup-training.ps1)"
}
if ($OutDir -eq '') {
    $OutDir = Join-Path $root ("reports\gates-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
New-Item -ItemType Directory -Force $OutDir | Out-Null
$audit = [ordered]@{
    timestamp = (Get-Date).ToString('o')
    candidate = $CandidateName
    engine_sha256 = ''
    rules_engine = $RulesEngine
    hardware = ''
    command_line = $MyInvocation.Line
}

# --- Preflight: artifact verification ---------------------------------------
Write-Host '== Verifying pinned artifacts =='
& (Join-Path $PSScriptRoot 'verify-artifacts.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Artifact verification failed; refusing to run gates.' }
$audit.artifact_verification = 'passed'

if (Test-Path -LiteralPath (Join-Path $root $CandidateEngine)) {
    $audit.engine_sha256 = (Get-FileHash -LiteralPath (Join-Path $root $CandidateEngine) -Algorithm SHA256).Hash.ToLowerInvariant()
}
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $audit.hardware = (nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1)
}

function Invoke-Match {
    param([string]$OpponentArg, [string]$OpponentEngine, [string]$OpponentEval,
          [string]$OpponentName, [int]$Games, [string]$Label)
    $out = Join-Path $OutDir $Label
    $arguments = @(
        '-m', 'xiangqi_nnue.match',
        '--engine', (Join-Path $root $CandidateEngine),
        '--eval-file', (Join-Path $root $CandidateEvalFile),
        '--engine-name', $CandidateName,
        $OpponentArg, (Join-Path $root $OpponentEngine),
        '--engine-name', $OpponentName,
        '--rules-engine', (Join-Path $root $RulesEngine),
        '--games', $Games, '--opening-plies', $OpeningPlies,
        '--nodes', $Nodes, '--max-plies', $MaxPlies,
        '--seed', $Seed, '--timeout', $TimeoutSeconds,
        '--candidate', $CandidateName, '--out-dir', $out
    )
    if ($OpponentEval) { $arguments += '--eval-file'; $arguments += (Join-Path $root $OpponentEval) }
    if ($Label -eq 'gate1') { $arguments += '--baseline-depth'; $arguments += $BaselineDepth }
    Write-Host "== Running ${Label}: $Games games ($CandidateName vs $OpponentName) =="
    Push-Location $root
    try {
        & $python @arguments
        if ($LASTEXITCODE -ne 0) { throw "$Label match failed with exit code $LASTEXITCODE" }
    } finally {
        Pop-Location
    }
    $summary = Get-Content -LiteralPath (Join-Path $out 'summary.json') -Raw | ConvertFrom-Json
    $audit[$Label] = $summary
    return $summary
}

# --- Gate 1: candidate vs calibrated baseline -------------------------------
if (-not $SkipGate1) {
    $summary = Invoke-Match -OpponentArg '--baseline' -OpponentEngine $BaselineEngine `
        -OpponentEval '' -OpponentName 'baseline' -Games $Gate1Games -Label 'gate1'
    $bound = [double]$summary.wilson_95_lower_bound
    if ($bound -le 0.60) {
        throw "Gate 1 FAILED: Wilson 95% lower bound $bound <= 0.60 (need > 0.60)."
    }
    Write-Host "Gate 1 PASSED (Wilson 95% lower bound $bound > 0.60)"
} else {
    Write-Host '== Skipping Gate 1 =='
}

# --- Gate 2: candidate vs strong CC0 teacher, equal nodes -------------------
if (-not $SkipGate2) {
    $summary = Invoke-Match -OpponentArg '--teacher' -OpponentEngine $TeacherEngine `
        -OpponentEval '' -OpponentName 'cc0-teacher' -Games $Gate2Games -Label 'gate2'
    $bound = [double]$summary.wilson_95_lower_bound
    if ($bound -lt 0.20) {
        throw "Gate 2 FAILED: Wilson 95% lower bound $bound < 0.20 (need >= 0.20)."
    }
    Write-Host "Gate 2 PASSED (Wilson 95% lower bound $bound >= 0.20)"
} else {
    Write-Host '== Skipping Gate 2 =='
}

# --- Tactical suite ----------------------------------------------------------
$suitePath = Join-Path $root 'datasets\tactical-suite.jsonl'
if (-not $SkipTactical) {
    if (-not (Test-Path -LiteralPath $suitePath)) {
        Write-Warning "Tactical suite not found at $suitePath; skipping (versioned suite is a Phase 2 task)."
        $audit.tactical = 'skipped (suite not found)'
    } else {
        # The suite runner is wired once the versioned suite exists; for now the
        # match harness exercises positions via --baseline/--engine as needed.
        $audit.tactical = 'present; runner pending versioned suite'
        Write-Warning 'Tactical suite runner is not yet implemented; suite file present.'
    }
} else {
    Write-Host '== Skipping tactical suite =='
}

$auditPath = Join-Path $OutDir 'gate-audit.json'
Set-Content -LiteralPath $auditPath -Value ($audit | ConvertTo-Json -Depth 6) -Encoding UTF8
Write-Host "Audit report: $auditPath"
Write-Host ($audit | ConvertTo-Json -Depth 6)
Write-Host 'All enabled gates passed.'
