[CmdletBinding()]
param(
    [switch]$VerifyData,
    [switch]$VerifyCheckpoints
)

# Verifies the reproducibility anchors from docs/amateur-strength-plan.md phase 0:
#   - teacher binary SHA-256 against third_party/fairy-stockfish-teacher.json
#   - Pikafish checkout pinned to third_party/pikafish.rev with the training patch applied
#   - optional: dataset shard manifests (SHA-256 per shard) and checkpoints
# Exits non-zero with a message on any mismatch; prints a JSON report on success.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$failures = [System.Collections.Generic.List[string]]::new()
$report = [ordered]@{}

# --- Teacher binary ---------------------------------------------------------
$manifestPath = Join-Path $root 'third_party\fairy-stockfish-teacher.json'
$teacher = Join-Path $root 'native\bin\fairy-stockfish-teacher.exe'
$report['teacher_manifest'] = $manifestPath
$report['teacher_binary'] = $teacher
if (-not (Test-Path -LiteralPath $teacher)) {
    $failures.Add("teacher binary missing: $teacher (run scripts\install-teacher.ps1)")
} elseif (Test-Path -LiteralPath $manifestPath) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.networkLicense -ne 'CC0-1.0') {
        $failures.Add("teacher network license is not CC0-1.0: $($manifest.networkLicense)")
    }
    $actual = (Get-FileHash -LiteralPath $teacher -Algorithm SHA256).Hash.ToLowerInvariant()
    $report['teacher_sha256'] = $actual
    if ($actual -ne $manifest.assetSha256) {
        $failures.Add("teacher SHA-256 mismatch: expected $($manifest.assetSha256), got $actual")
    }
} else {
    $failures.Add("teacher manifest missing: $manifestPath")
}

# --- Pikafish revision and patch -------------------------------------------
$revPath = Join-Path $root 'third_party\pikafish.rev'
$patchPath = Join-Path $root 'third_party\pikafish-training.patch'
$vendor = Join-Path $root 'native\vendor\Pikafish'
$report['pikafish_revision_file'] = $revPath
$report['pikafish_patch'] = $patchPath
$report['pikafish_checkout'] = $vendor
if (-not (Test-Path -LiteralPath $revPath)) {
    $failures.Add("pikafish revision file missing: $revPath")
} else {
    $expectedRevision = (Get-Content -LiteralPath $revPath -Raw).Trim()
    $report['pikafish_revision'] = $expectedRevision
    if (-not (Test-Path -LiteralPath (Join-Path $vendor '.git'))) {
        $failures.Add("pikafish checkout missing: $vendor (run scripts\fetch-pikafish.ps1)")
    } else {
        $head = (git -C $vendor rev-parse HEAD 2>$null).Trim()
        $report['pikafish_head'] = $head
        if ($head -ne $expectedRevision) {
            $failures.Add("pikafish HEAD $head does not match pinned revision $expectedRevision")
        }
        if (-not (Test-Path -LiteralPath $patchPath)) {
            $failures.Add("pikafish training patch missing: $patchPath")
        } else {
            git -C $vendor apply --reverse --check $patchPath 2>$null
            if ($LASTEXITCODE -ne 0) {
                $failures.Add("pikafish training patch is not applied at $expectedRevision")
            }
        }
    }
}

# --- Optional dataset manifests ---------------------------------------------
if ($VerifyData) {
    $dataRoot = Join-Path $root 'datasets'
    $report['dataset_root'] = $dataRoot
    if (-not (Test-Path -LiteralPath $dataRoot)) {
        $failures.Add("dataset root missing: $dataRoot")
    } else {
        $manifestFiles = Get-ChildItem -LiteralPath $dataRoot -Recurse -Filter 'manifest.json' -ErrorAction SilentlyContinue
        if (-not $manifestFiles) {
            $failures.Add("no dataset manifests found under $dataRoot")
        }
        foreach ($manifestFile in $manifestFiles) {
            $manifest = Get-Content -LiteralPath $manifestFile.FullName -Raw | ConvertFrom-Json
            $shards = @($manifest.shards)
            $verified = 0
            foreach ($shard in $shards) {
                $shardPath = Join-Path $manifestFile.DirectoryName $shard.file
                if (-not (Test-Path -LiteralPath $shardPath)) {
                    $failures.Add("shard missing: $shardPath")
                    continue
                }
                $actual = (Get-FileHash -LiteralPath $shardPath -Algorithm SHA256).Hash.ToLowerInvariant()
                if ($actual -ne $shard.sha256) {
                    $failures.Add("shard SHA-256 mismatch: $shardPath")
                } else {
                    $verified++
                }
            }
            $report["dataset_$($manifestFile.Directory.Name)"] = "$verified/$($shards.Count) shards verified"
        }
    }
}

# --- Optional checkpoint hashes ---------------------------------------------
if ($VerifyCheckpoints) {
    $checkpointDir = Join-Path $root 'checkpoints'
    $report['checkpoint_root'] = $checkpointDir
    if (Test-Path -LiteralPath $checkpointDir) {
        foreach ($checkpoint in Get-ChildItem -LiteralPath $checkpointDir -Filter '*.pt' -ErrorAction SilentlyContinue) {
            $report["checkpoint_$($checkpoint.BaseName)"] =
                (Get-FileHash -LiteralPath $checkpoint.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
}

# --- Report -----------------------------------------------------------------
$json = $report | ConvertTo-Json -Depth 4
$reportPath = Join-Path $root 'reports\verify-artifacts.json'
if (-not (Test-Path -LiteralPath (Split-Path -Parent $reportPath))) {
    New-Item -ItemType Directory -Force (Split-Path -Parent $reportPath) | Out-Null
}
Set-Content -LiteralPath $reportPath -Value $json -Encoding UTF8
Write-Output $json
if ($failures.Count -gt 0) {
    Write-Error "Artifact verification failed:"
    $failures | ForEach-Object { Write-Error "  - $_" }
    exit 1
}
Write-Host "All pinned artifacts verified."
