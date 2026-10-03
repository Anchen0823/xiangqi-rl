param(
  [double]$Minutes=30,
  [string]$Output='',
  [string]$Initial='runs/variants/acceptance-20261002/jieqi/model',
  [int]$Nodes=64,
  [int]$Steps=1000,
  [int]$Pairs=8,
  [ValidateSet('cpu','cuda','auto')][string]$Device='cpu'
)
$ErrorActionPreference='Stop'
Set-Location (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
if (-not $Output) { $Output = 'runs/jieqi/pilot-' + (Get-Date -Format 'yyyyMMdd-HHmmss') }
& node scripts/variants/build-lab.mjs
if ($LASTEXITCODE -ne 0) { throw '裁判构建失败' }
if (-not (Test-Path '.venv/Scripts/python.exe')) { throw '缺少 .venv 训练环境，请查看 docs/jieqi-training.md。' }
$env:PYTHONPATH=Join-Path (Get-Location) 'trainer/src'
$env:PYTHONIOENCODING='utf-8'
Write-Host "揭棋独立训练输出：$Output"
& ./.venv/Scripts/python.exe -u -m xiangqi_variants.jieqi --minutes $Minutes --out $Output --initial $Initial --nodes $Nodes --steps $Steps --pairs $Pairs --device $Device
if ($LASTEXITCODE -ne 0) { throw '揭棋试训失败；保留数据、日志和检查点，检查 status.json。' }
