param([int]$Pairs=32, [int]$Nodes=128, [double]$Minutes=60)
$ErrorActionPreference='Stop'
Set-Location (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
$env:PYTHONPATH=Join-Path (Get-Location) 'trainer/src'
$env:PYTHONIOENCODING='utf-8'
& ./.venv/Scripts/python.exe -u scripts/variants/evaluate-jieqi-night.py --pairs $Pairs --nodes $Nodes --minutes $Minutes
if ($LASTEXITCODE -ne 0) { throw 'Jieqi independent evaluation failed' }
