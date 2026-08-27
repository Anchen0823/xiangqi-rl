[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$revision = (Get-Content (Join-Path $root "third_party\pikafish.rev") -Raw).Trim()
$vendorRoot = Join-Path $root "native\vendor"
$target = Join-Path $vendorRoot "Pikafish"
New-Item -ItemType Directory -Force $vendorRoot | Out-Null
if (-not (Test-Path (Join-Path $target ".git"))) {
    git clone --filter=blob:none https://github.com/official-pikafish/Pikafish.git $target
}
git -C $target fetch --depth 1 origin $revision
git -C $target checkout --detach $revision
Write-Host "Pikafish pinned at $revision. Official network files are not downloaded."
