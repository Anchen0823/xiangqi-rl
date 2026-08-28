[CmdletBinding()]
param(
    [int]$Steps = 21,
    [string]$Dataset = 'datasets\selfplay-cache-labeled',
    [string]$Checkpoint = 'checkpoints\demo.pt',
    [switch]$Resume
)

$ErrorActionPreference = 'Stop'
if ($Steps -le 0) { throw 'Steps must be positive.' }
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$datasetPath = Join-Path $root $Dataset
$checkpointPath = Join-Path $root $Checkpoint

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Training environment is missing. Run scripts\setup-training.ps1 first.'
}
if (-not (Test-Path -LiteralPath (Join-Path $datasetPath 'manifest.json'))) {
    throw "Training dataset is missing: $datasetPath. Follow README 'Generate fresh demo data'."
}

$manifest = Get-Content -LiteralPath (Join-Path $datasetPath 'manifest.json') -Raw | ConvertFrom-Json
$records = [int]$manifest.totalRecords
if ($records -le 0) { throw 'Training dataset contains no records.' }
$microBatch = [Math]::Min(64, $records)
$shuffleBuffer = [Math]::Max($microBatch, [Math]::Min(8192, $records))

. (Join-Path $PSScriptRoot 'cuda-path.ps1')
$cuda = Find-CudaToolkit -ProjectRoot $root
if ($cuda) {
    $env:CUDA_PATH = $cuda
    $env:Path = "$(Join-Path $cuda 'bin');$env:Path"
}

Push-Location $root
try {
    & $python -c "import torch; assert torch.cuda.is_available(), 'CUDA is unavailable'; print({'gpu': torch.cuda.get_device_name(0), 'torch': torch.__version__, 'cuda': torch.version.cuda})"
    if ($LASTEXITCODE -ne 0) { throw 'CUDA preflight failed.' }
    Write-Host "Training $records licensed records for $Steps optimizer steps..."
    $arguments = @(
        '-m', 'xiangqi_nnue.train', '--dataset', $datasetPath,
        '--steps', $Steps, '--micro-batch', $microBatch,
        '--accumulate', 1, '--shuffle-buffer', $shuffleBuffer,
        '--checkpoint', $checkpointPath
    )
    if ($Resume) { $arguments += '--resume' }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Training failed with exit code $LASTEXITCODE" }
    $hash = (Get-FileHash -LiteralPath $checkpointPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "Checkpoint: $checkpointPath"
    Write-Host "SHA-256: $hash"
} finally {
    Pop-Location
}
