[CmdletBinding()]
param(
    [string]$Network = 'checkpoints\expanded-20260930\candidate.nnue',
    [switch]$SkipBuild,
    [int]$DebugPort = 0
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$engine = Join-Path $root 'native\bin\pikafish.exe'
$networkPath = if ([IO.Path]::IsPathRooted($Network)) { $Network } else { Join-Path $root $Network }
foreach ($path in @($engine, $networkPath, (Join-Path $root 'node_modules\electron\dist\electron.exe'))) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required file missing: $path" }
}
$env:XIANGQI_PIKAFISH_PATH = $engine
$env:XIANGQI_NNUE_PATH = (Resolve-Path -LiteralPath $networkPath).Path
$env:XIANGQI_EMBEDDED_NNUE = '0'
$env:XIANGQI_SEARCH_BACKEND = 'pikafish'
Remove-Item Env:XIANGQI_UCI_VARIANT -ErrorAction SilentlyContinue
Remove-Item Env:VITE_DEV_SERVER_URL -ErrorAction SilentlyContinue
# ELECTRON_RUN_AS_NODE turns the GUI binary into a plain Node host, and then
# electron.exe fails on the app's "require('electron')" before any window opens.
if ($env:ELECTRON_RUN_AS_NODE) {
    Write-Host "Clearing ELECTRON_RUN_AS_NODE='$($env:ELECTRON_RUN_AS_NODE)' (it would run Electron as plain Node)"
}
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
Push-Location $root
try {
    if (-not $SkipBuild) {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "Build failed: $LASTEXITCODE" }
    }
    Write-Host "Playing with candidate network: $networkPath"
    $launchArguments = @($root)
    if ($DebugPort -gt 0) { $launchArguments += "--remote-debugging-port=$DebugPort" }
    & (Join-Path $root 'node_modules\electron\dist\electron.exe') @launchArguments
    # Closing the window is a normal way to leave the app and does not always
    # leave an exit code behind, so only a real non-zero code is a failure.
    $exitCode = $LASTEXITCODE
    if ($null -ne $exitCode -and $exitCode -ne 0) {
        throw "electron.exe exited with code $exitCode; run scripts\diagnose-play-candidate.ps1 for the log"
    }
} finally { Pop-Location }
