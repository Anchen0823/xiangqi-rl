[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $root 'third_party\fairy-stockfish-teacher.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.networkLicense -ne 'CC0-1.0') {
    throw "Teacher network is not CC0-1.0: $($manifest.networkLicense)"
}
$cache = Join-Path $root '.cache\teacher'
$destination = Join-Path $root 'native\bin\fairy-stockfish-teacher.exe'
$download = Join-Path $cache ($manifest.release + '-' + [guid]::NewGuid().ToString('N') + '.exe')
New-Item -ItemType Directory -Force $cache, (Split-Path -Parent $destination) | Out-Null
try {
    Invoke-WebRequest -Uri $manifest.assetUrl -OutFile $download -UseBasicParsing
    $actualSize = (Get-Item -LiteralPath $download).Length
    if ($actualSize -ne $manifest.assetBytes) {
        throw "Teacher asset size mismatch: expected $($manifest.assetBytes), got $actualSize"
    }
    $actualHash = (Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $manifest.assetSha256) {
        throw "Teacher SHA-256 mismatch: expected $($manifest.assetSha256), got $actualHash"
    }
    Copy-Item -LiteralPath $download -Destination $destination -Force
}
finally {
    if (Test-Path -LiteralPath $download) {
        Remove-Item -LiteralPath $download -Force
    }
}
Write-Host "Installed verified $($manifest.release) teacher to $destination"
