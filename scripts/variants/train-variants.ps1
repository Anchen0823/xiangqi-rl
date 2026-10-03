param([ValidateSet('custom','jieqi','banqi','all')][string]$Mode='all',[string]$Output='runs/variants/short-training',[int]$Nodes=32,[int]$Steps=100)
$ErrorActionPreference='Stop'
Set-Location (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)
& node scripts/variants/build-lab.mjs
if ($LASTEXITCODE -ne 0) { throw '变体裁判构建失败' }
if (-not (Test-Path '.venv/Scripts/python.exe')) { throw '缺少训练环境，请先按 README 安装 Python 训练依赖。' }
$env:PYTHONPATH=Join-Path (Get-Location) 'trainer/src'
& ./.venv/Scripts/python.exe -m xiangqi_variants.lab smoke --mode $Mode --out $Output --nodes $Nodes --steps $Steps
if ($LASTEXITCODE -ne 0) { throw '短训验收未通过；数据与检查点已保留，请查看具体错误。' }
