# Full unsupervised training run: fresh self-play -> labels -> split -> train -> export.
#
# Sized for a night-long unattended run. The stages are ordered by cost, and the
# measured rates that set the budgets are:
#   self-play   ~0.13 games/s (12 workers, 5k nodes, ~152 positions/game)
#   labeling    ~860 records/s (reuses the teacher scores self-play cached)
#   split       seconds
#   training    ~4.66 s/optimizer step at batch 8192 (the real bottleneck)
# Training is therefore capped in steps, not epochs: past a few hundred steps the
# warm-started model overfits, and each extra step costs the pipeline ~5 seconds.
#
# Every stage is resumable, and each writes its own log under the run directory,
# so an interrupted run can be restarted with the same -RunName.
param(
    [double]$DurationHours = 7.0,
    [string]$RunName = '',
    # 1500 games is where a night's self-play meaningfully expands the corpus:
    # at the measured ~150 positions/game it yields ~225k positions, about the
    # size of the whole existing selfplay-v1 corpus, in ~3 hours of the budget.
    [int]$Games = 1500,
    [int]$Nodes = 5000,
    [int]$Workers = 12,
    [int]$MaxPlies = 240,
    [int]$RandomPlies = 8,
    [int]$Seed = 20261001,
    [int]$TrainSteps = 1800,
    [string]$InitCheckpoint = 'checkpoints\expanded-20260930\best.pt',
    # Accumulate onto the corpus the warm-start checkpoint was already fitted on
    # instead of regenerating ~200k positions to reach the same starting point.
    # The base partition stays training (it is already memorised, so reusing it
    # leaks nothing); only tonight's games may enter the new val/test, which is
    # why the frozen holdouts below are never retrained on.
    [switch]$Accumulate,
    [string]$AccumName = 'accumulated',
    [string]$BaseTrain = 'datasets\v1-split-20260930\train',
    [string[]]$FrozenHoldout = @(
        'datasets\v1-split-20260930\val',
        'datasets\trial-continue-20260930\val',
        'datasets\trial-continue-20260930\test'
    ),
    [switch]$SkipSelfplay,
    [switch]$SkipTrain
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'

if ($DurationHours -le 0) { throw 'DurationHours must be positive.' }
if ($Workers -lt 1 -or $Workers -gt 12) { throw 'Workers must be in [1, 12].' }
if (-not (Test-Path -LiteralPath $python)) { throw 'Training environment is missing. Run scripts\setup-training.ps1 first.' }

if (-not $RunName) { $RunName = "selfplay-r2-$(Get-Date -Format 'yyyyMMdd-HHmm')" }
$run = Join-Path $root "runs\$RunName"
$source = Join-Path $run 'selfplay'
$labeled = Join-Path $run 'labeled'
$split = Join-Path $run 'split'
$checkpoint = Join-Path $run 'checkpoints'
$reports = Join-Path $run 'reports'
foreach ($directory in @($run, $source, $labeled, $split, $checkpoint, $reports)) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

$deadline = (Get-Date).AddHours($DurationHours)
# Self-play is the long pole and it is resumable, so it gets the leftover time
# minus a reserve for labeling, splitting and a training slot that actually
# reaches the early-stop check rather than being cut off mid-schedule. The
# reserve is capped as a fraction of the budget so a short smoke run still
# exercises self-play instead of spending its whole window on reserve.
$reserveMinutes = [Math]::Min(120, [Math]::Floor($DurationHours * 60 * 0.30))
$selfplayDeadline = $deadline.AddMinutes(-$reserveMinutes)

function Write-Stage([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $Message
    Write-Host $line
    Add-Content -LiteralPath (Join-Path $reports 'run.log') -Value $line -Encoding UTF8
}

function Get-ManifestCount([string]$Path) {
    $manifestPath = Join-Path $Path 'manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath)) { return 0 }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.games -is [array]) { return [int]$manifest.games.Count }
    return 0
}

# The rules + teacher engines need the project root as the working directory:
# the native engine resolves native/bin and models relative to it.
Push-Location $root
try {
    Write-Stage "run $RunName | budget $DurationHours h | deadline $($deadline.ToString('HH:mm'))"
    Write-Stage "artifacts: runs\$RunName"

    # The native engine and Pikafish both need a CUDA-visible environment on this
    # box; cuda-path.ps1 is the project's own locator and is a no-op when absent.
    . (Join-Path $PSScriptRoot 'cuda-path.ps1')
    $cuda = Find-CudaToolkit -ProjectRoot $root
    if ($cuda) { $env:CUDA_PATH = $cuda; $env:Path = "$(Join-Path $cuda 'bin');$env:Path" }

    # ---------------------------------------------------------------- self-play
    if (-not $SkipSelfplay) {
        $done = Get-ManifestCount $source
        Write-Stage "self-play: $done/$Games games already present"
        while ($done -lt $Games -and (Get-Date) -lt $selfplayDeadline) {
            # Small batches keep the manifest advancing every couple of minutes,
            # so a run can be watched from outside without waiting for the whole
            # target. Self-play resumes from the manifest, so batching is free.
            $remaining = [Math]::Min($Games - $done, 25)
            Write-Stage "self-play: requesting $remaining more games ($done/$Games)"
            & $python -u -m xiangqi_nnue.selfplay `
                --rules-engine (Join-Path $root 'build\native\xiangqi-engine.exe') `
                --teacher-engine (Join-Path $root 'native\bin\fairy-stockfish-teacher.exe') `
                --teacher-manifest (Join-Path $root 'third_party\fairy-stockfish-teacher.json') `
                --output $source --games ($done + $remaining) --nodes $Nodes `
                --max-plies $MaxPlies --random-plies $RandomPlies `
                --seed $Seed --workers $Workers `
                2>&1 | Tee-Object -FilePath (Join-Path $reports 'selfplay.log') -Append
            if ($LASTEXITCODE -ne 0) { throw "self-play failed with exit code $LASTEXITCODE" }
            $next = Get-ManifestCount $source
            if ($next -le $done) { throw "self-play made no progress ($done games)" }
            $done = $next
        }
        if ($done -lt $Games) { Write-Stage "self-play: deadline reached at $done/$Games games (resumable)" }
        else { Write-Stage "self-play: complete, $done games" }
    }

    $sourceManifest = Get-Content -LiteralPath (Join-Path $source 'manifest.json') -Raw | ConvertFrom-Json
    $positions = [int]$sourceManifest.totalRecords
    if ($positions -le 0) { throw "self-play produced no positions under $source" }
    Write-Stage "corpus: $positions positions"

    # ------------------------------------------------------------------ labeling
    # Self-play cached the teacher's score and bestmove for every non-opening
    # position, so this pass is read-mostly and costs a few minutes, not hours.
    Write-Stage 'labeling'
    & $python -u -m xiangqi_nnue.label `
        --source $source --source-url "local:$RunName" --attribution "Xiangqi RL self-play $RunName" `
        --dataset $labeled --dataset-id "$RunName-cc0" `
        --feature-engine (Join-Path $root 'native\bin\pikafish.exe') `
        --teacher-engine (Join-Path $root 'native\bin\fairy-stockfish-teacher.exe') `
        --teacher-manifest (Join-Path $root 'third_party\fairy-stockfish-teacher.json') `
        --nodes $Nodes --threads 8 --hash-mb 128 `
        2>&1 | Tee-Object -FilePath (Join-Path $reports 'label.log') -Append
    if ($LASTEXITCODE -ne 0) { throw "labeling failed with exit code $LASTEXITCODE" }

    # --------------------------------------------------------------------- split
    if ($Accumulate) {
        # The foundation is the partition the warm-start checkpoint already saw,
        # plus tonight's games. Only tonight's games are eligible for the new
        # val/test, so the run is judged on data the model has never seen.
        $library = Join-Path $root "datasets\$AccumName"
        Write-Stage "accumulating into datasets\$AccumName (base: $BaseTrain)"
        if (-not (Test-Path -LiteralPath (Join-Path $root $BaseTrain))) {
            throw "base training partition is missing: $BaseTrain"
        }
        $splitArguments = @(
            '-m', 'scripts.prepare-accumulated-split',
            '--base-labeled', (Join-Path $root $BaseTrain),
            '--new-labeled', $labeled,
            '--new-source', $source,
            '--output', $library,
            '--val-ratio', '0.12', '--test-ratio', '0.04',
            '--seed', $Seed, '--dataset-tag', $AccumName,
            '--report', (Join-Path $reports 'accumulation.json')
        )
        foreach ($holdoutDirectory in $FrozenHoldout) {
            $resolved = Join-Path $root $holdoutDirectory
            if (Test-Path -LiteralPath $resolved) {
                $splitArguments += @('--holdout', $resolved)
            } else {
                Write-Stage "  warning: frozen holdout missing, skipped: $holdoutDirectory"
            }
        }
        & $python -u @splitArguments 2>&1 | Tee-Object -FilePath (Join-Path $reports 'accumulate.log') -Append
        if ($LASTEXITCODE -ne 0) { throw "accumulated split failed with exit code $LASTEXITCODE" }
        $trainPath = Join-Path $library 'train'
        $valPath = Join-Path $library 'val'
    } else {
        # Whole games are assigned before positions are deduplicated, so no game
        # can straddle two partitions and leak its own positions into validation.
        Write-Stage 'splitting'
        & $python -u -m xiangqi_nnue.split `
            --labeled $labeled --source $source `
            --train-output (Join-Path $split 'train') --val-output (Join-Path $split 'val') `
            --test-output (Join-Path $split 'test') `
            --train-ratio 0.94 --val-ratio 0.04 --seed $Seed --dataset-tag $RunName `
            2>&1 | Tee-Object -FilePath (Join-Path $reports 'split.log') -Append
        if ($LASTEXITCODE -ne 0) { throw "split failed with exit code $LASTEXITCODE" }
        $trainPath = Join-Path $split 'train'
        $valPath = Join-Path $split 'val'
    }
    foreach ($partition in @($trainPath, $valPath)) {
        $manifest = Get-Content -LiteralPath (Join-Path $partition 'manifest.json') -Raw | ConvertFrom-Json
        Write-Stage "  $(Split-Path -Leaf $partition): $($manifest.totalRecords) records"
    }

    # ------------------------------------------------------------------- training
    if (-not $SkipTrain) {
        $minutesLeft = [Math]::Floor(($deadline - (Get-Date)).TotalMinutes)
        if ($minutesLeft -lt 20) { throw "only $minutesLeft minutes left; not enough to train" }
        Write-Stage "training: up to $TrainSteps steps, $minutesLeft minutes left"
        $env:OMP_NUM_THREADS = '4'
        $env:MKL_NUM_THREADS = '4'
        & $python -u -m xiangqi_nnue.train `
            --config (Join-Path $root 'trainer\config\night-r2.toml') `
            --dataset $trainPath --val-dataset $valPath `
            --init-checkpoint (Join-Path $root $InitCheckpoint) `
            --checkpoint (Join-Path $checkpoint 'latest.pt') `
            --best-checkpoint (Join-Path $checkpoint 'best.pt') `
            --metrics (Join-Path $reports 'metrics.jsonl') `
            --steps $TrainSteps `
            2>&1 | Tee-Object -FilePath (Join-Path $reports 'train.log') -Append
        if ($LASTEXITCODE -ne 0) { throw "training failed with exit code $LASTEXITCODE" }
        Write-Stage 'training: finished'
    }

    # --------------------------------------------------------------------- export
    # best.pt is validation-selected; latest.pt may already be overfitting.
    $best = Join-Path $checkpoint 'best.pt'
    if (Test-Path -LiteralPath $best) {
        Write-Stage 'exporting NNUE'
        & $python -u -m xiangqi_nnue.export_nnue `
            --checkpoint $best --output (Join-Path $checkpoint 'candidate.nnue') `
            --description "Xiangqi RL $RunName" `
            2>&1 | Tee-Object -FilePath (Join-Path $reports 'export.log') -Append
        if ($LASTEXITCODE -ne 0) { throw "export failed with exit code $LASTEXITCODE" }
    }

    # -------------------------------------------------------------------- summary
    $candidate = Join-Path $checkpoint 'candidate.nnue'
    $summary = [ordered]@{
        run            = $RunName
        finishedAt     = (Get-Date).ToString('s')
        budgetHours    = $DurationHours
        accumulated    = [bool]$Accumulate
        baseTrain      = if ($Accumulate) { $BaseTrain } else { $null }
        games          = (Get-ManifestCount $source)
        positions      = $positions
        nodes          = $Nodes
        seed           = $Seed
        initCheckpoint = $InitCheckpoint
        hitDeadline    = ((Get-Date) -ge $deadline)
    }
    if (Test-Path -LiteralPath $candidate) {
        $summary['candidate'] = $candidate
        $summary['candidateSha256'] = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
        $summary['candidateBytes'] = (Get-Item -LiteralPath $candidate).Length
    }
    $bestMetrics = Join-Path $reports 'metrics.jsonl'
    if (Test-Path -LiteralPath $bestMetrics) {
        $summary['lastMetrics'] = (Get-Content -LiteralPath $bestMetrics -Tail 1)
    }
    $summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $reports 'summary.json') -Encoding UTF8
    Write-Stage "done. summary: runs\$RunName\reports\summary.json"
    if (Test-Path -LiteralPath $candidate) {
        Write-Stage 'play the result with:'
        Write-Stage "  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\play-candidate.ps1 -SkipBuild -Network runs\$RunName\checkpoints\candidate.nnue"
    } else {
        Write-Stage 'no candidate network was exported'
    }
} finally {
    Pop-Location
}
