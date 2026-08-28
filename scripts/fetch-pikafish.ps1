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
$patch = Join-Path $root "third_party\pikafish-training.patch"
git -C $target apply --reverse --check $patch 2>$null
if ($LASTEXITCODE -ne 0) {
    git -C $target apply --check $patch
    if ($LASTEXITCODE -ne 0) {
        throw "The Pikafish training patch does not apply cleanly to revision $revision."
    }
    git -C $target apply $patch
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to apply the Pikafish training patch."
    }
}
Write-Host "Pikafish pinned at $revision with the training-feature export patch. Official network files are not downloaded."
