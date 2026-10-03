param(
  [double]$Hours=8,
  [string]$Output='runs/jieqi/night-8h',
  [string]$Initial='runs/jieqi/pilot-20261003/model',
  [double]$RoundMinutes=60,
  [int]$Nodes=128,
  [int]$Steps=2000,
  [int]$Pairs=8,
  [ValidateSet('cpu','cuda','auto')][string]$Device='cpu'
)
$ErrorActionPreference='Stop'
Set-Location (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
& node scripts/variants/build-lab.mjs
if ($LASTEXITCODE -ne 0) { throw 'Referee build failed' }
if (-not (Test-Path '.venv/Scripts/python.exe')) { throw 'Missing Python environment: .venv' }
New-Item -ItemType Directory -Force (Join-Path $Output 'logs') | Out-Null
$env:PYTHONPATH=Join-Path (Get-Location) 'trainer/src'
$env:PYTHONIOENCODING='utf-8'
$logPath=Join-Path $Output ('logs/session-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
Start-Transcript -LiteralPath $logPath
try {
  & ./.venv/Scripts/python.exe -u -m xiangqi_variants.jieqi_night --hours $Hours --out $Output --initial $Initial --round-minutes $RoundMinutes --nodes $Nodes --steps $Steps --pairs $Pairs --device $Device
  if ($LASTEXITCODE -ne 0) { throw "Jieqi campaign failed; see $Output/night.json and $logPath" }
} finally { Stop-Transcript }
