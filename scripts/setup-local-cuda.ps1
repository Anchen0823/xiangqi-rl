[CmdletBinding()]
param(
    [string]$Version = "13.2.1",
    [string[]]$Components = @(
        "cuda_cccl",
        "cuda_crt",
        "cuda_cudart",
        "cuda_nvcc",
        "libnvvm"
    )
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$root = Split-Path -Parent $PSScriptRoot
$installRoot = Join-Path $root ".cuda\v13.2"
$cacheRoot = Join-Path $root ".cache\cuda-redist"
$manifestPath = Join-Path $cacheRoot "redistrib_$Version.json"
$baseUrl = "https://developer.download.nvidia.com/compute/cuda/redist"

New-Item -ItemType Directory -Force -Path $installRoot, $cacheRoot | Out-Null

Write-Host "Downloading CUDA $Version redistributable manifest..."
& curl.exe --fail --location --retry 5 --retry-all-errors --output $manifestPath "$baseUrl/redistrib_$Version.json"
if ($LASTEXITCODE -ne 0) { throw "CUDA manifest download failed with exit code $LASTEXITCODE" }
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ($manifest.release_label -ne $Version) { throw "Unexpected CUDA manifest version: $($manifest.release_label)" }

foreach ($componentName in $Components) {
    $componentProperty = $manifest.PSObject.Properties[$componentName]
    if (-not $componentProperty) { throw "CUDA component is absent from manifest: $componentName" }
    $component = $componentProperty.Value
    $platformProperty = $component.PSObject.Properties["windows-x86_64"]
    if (-not $platformProperty) { throw "CUDA component has no Windows x64 archive: $componentName" }
    $archiveInfo = $platformProperty.Value
    $archiveName = Split-Path -Leaf $archiveInfo.relative_path
    $archivePath = Join-Path $cacheRoot $archiveName
    $archiveUrl = "$baseUrl/$($archiveInfo.relative_path)"

    $validArchive = $false
    if (Test-Path -LiteralPath $archivePath) {
        $existingHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
        $validArchive = $existingHash -eq $archiveInfo.sha256.ToLowerInvariant()
    }
    if (-not $validArchive) {
        Write-Host "Downloading $componentName $($component.version)..."
        & curl.exe --fail --location --retry 8 --retry-all-errors --continue-at - --output $archivePath $archiveUrl
        if ($LASTEXITCODE -ne 0) { throw "$componentName download failed with exit code $LASTEXITCODE" }
    }

    $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
    if ($actualHash -ne $archiveInfo.sha256.ToLowerInvariant()) {
        throw "$componentName SHA-256 mismatch: expected $($archiveInfo.sha256), got $actualHash"
    }

    $stageRoot = Join-Path $cacheRoot ("stage-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $stageRoot | Out-Null
    Expand-Archive -LiteralPath $archivePath -DestinationPath $stageRoot
    $archiveRoot = Get-ChildItem -LiteralPath $stageRoot -Directory | Select-Object -First 1
    if (-not $archiveRoot) { throw "$componentName archive has no root directory" }
    Get-ChildItem -LiteralPath $archiveRoot.FullName | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $installRoot -Recurse -Force
    }
    Write-Host "Installed $componentName $($component.version)"
}

$nvcc = Join-Path $installRoot "bin\nvcc.exe"
if (-not (Test-Path -LiteralPath $nvcc)) { throw "CUDA installation is incomplete: $nvcc was not created" }
$env:CUDA_PATH = $installRoot
$env:Path = "$(Join-Path $installRoot 'bin');$env:Path"
Write-Host "Project-local CUDA is ready at $installRoot"
& $nvcc --version
