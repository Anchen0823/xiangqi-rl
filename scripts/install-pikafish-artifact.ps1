[CmdletBinding()]
param([string]$RunId)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $RunId) {
    $RunId = gh run list --repo Anchen0823/xiangqi-rl --workflow pikafish.yml --status success --limit 1 --json databaseId --jq '.[0].databaseId'
}
if (-not $RunId) { throw 'No successful Pikafish build workflow was found' }
$temporary = Join-Path $root ('.cache\pikafish-artifact-' + $RunId + '-' + [guid]::NewGuid().ToString('N'))
$destination = Join-Path $root 'native\bin'
New-Item -ItemType Directory -Force $temporary, $destination | Out-Null
gh run download $RunId --repo Anchen0823/xiangqi-rl --dir $temporary
$binary = Get-ChildItem $temporary -Filter pikafish.exe -Recurse | Select-Object -First 1
if (-not $binary) { throw 'Downloaded artifact does not contain pikafish.exe' }
Copy-Item -LiteralPath $binary.FullName -Destination (Join-Path $destination 'pikafish.exe') -Force
Write-Host "Installed pinned search binary to $destination"
