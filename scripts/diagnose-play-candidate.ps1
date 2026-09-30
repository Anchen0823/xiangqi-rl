[CmdletBinding()]
param(
    [string]$Network = 'checkpoints\expanded-20260930\candidate.nnue',
    [switch]$SkipBuild
)
# Diagnose why the playable app exits.
#
# Unlike scripts\play-candidate.ps1 this keeps Electron's own output and reports
# the real exit code, because "App exited:" with nothing after it says neither
# what happened nor why. It also clears every variable that changes how the
# Electron binary starts.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$electron = Join-Path $root 'node_modules\electron\dist\electron.exe'
$engine = Join-Path $root 'native\bin\pikafish.exe'
$networkPath = if ([IO.Path]::IsPathRooted($Network)) { $Network } else { Join-Path $root $Network }
foreach ($path in @($electron, $engine, $networkPath, (Join-Path $root 'build\native\xiangqi-engine.exe'))) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Required file missing: $path" }
}

# ELECTRON_RUN_AS_NODE turns the GUI binary into a plain Node host, and then
# electron.exe fails on the app's "require('electron')" before any window opens.
foreach ($name in 'ELECTRON_RUN_AS_NODE', 'ELECTRON_NO_ATTACH_CONSOLE',
                  'VITE_DEV_SERVER_URL', 'XIANGQI_UCI_VARIANT') {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}
$env:XIANGQI_PIKAFISH_PATH = $engine
$env:XIANGQI_NNUE_PATH = (Resolve-Path -LiteralPath $networkPath).Path
$env:XIANGQI_EMBEDDED_NNUE = '0'
$env:XIANGQI_SEARCH_BACKEND = 'pikafish'

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outLog = Join-Path $root "electron-$stamp.out.log"
$errLog = Join-Path $root "electron-$stamp.err.log"
$werDir = Join-Path $env:LOCALAPPDATA 'CrashDumps'

Write-Host 'Environment check:'
Write-Host "  ELECTRON_RUN_AS_NODE = '$($env:ELECTRON_RUN_AS_NODE)'   (must be empty)"
Write-Host "  electron.exe         = $electron"
Write-Host "  network              = $env:XIANGQI_NNUE_PATH"
Write-Host "  engine               = $env:XIANGQI_PIKAFISH_PATH"

Push-Location $root
try {
    if (-not $SkipBuild) {
        Write-Host 'Building...'
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "Build failed with exit code $LASTEXITCODE" }
    }
    Write-Host ''
    Write-Host 'Launching; close the window when you are done...'
    $process = Start-Process -FilePath $electron -ArgumentList $root, '--enable-logging' `
        -PassThru -NoNewWindow -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    $process.WaitForExit()
    $code = $process.ExitCode

    Write-Host ''
    Write-Host "Process id            : $($process.Id)"
    Write-Host "Electron exit code    : $code (0x$('{0:X8}' -f $code))"
    Write-Host "stdout log            : $outLog"
    Write-Host "stderr log            : $errLog"
    foreach ($pair in @(@('stdout', $outLog), @('stderr', $errLog))) {
        Write-Host "--- $($pair[0]) ---"
        $lines = @(Get-Content -LiteralPath $pair[1] -ErrorAction SilentlyContinue)
        if ($lines.Count -eq 0) { Write-Host '(empty)' } else { $lines | Select-Object -Last 40 }
    }
    $dumps = @(Get-ChildItem -LiteralPath $werDir -Filter 'electron*.dmp' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 3)
    Write-Host "--- crash dumps in $werDir ---"
    if ($dumps.Count -eq 0) { Write-Host '(none)' }
    else { $dumps | ForEach-Object { Write-Host "  $($_.LastWriteTime)  $($_.Name)  $($_.Length) bytes" } }

    if ($code -eq 0) {
        Write-Host ''
        Write-Host 'Result: the app closed normally.'
    } elseif ($code -eq -1073741819) {
        Write-Host ''
        Write-Host 'Result: the app hit an access violation (0xC0000005) - a crash, not an app error.'
    } elseif ($code -eq -2147483645) {
        Write-Host ''
        Write-Host 'Result: the app hit a breakpoint exception (0x80000003) - a crash inside Electron.'
    } else {
        Write-Host ''
        Write-Host 'Result: the app did not exit cleanly; see the logs above.'
    }
} finally { Pop-Location }
