# Candidate continuation: 2026-09-30

Completed five configured epochs (130 optimizer updates) on RTX 4060 Laptop,
PyTorch 2.12.1+cu132. The previous `candidate-101.pt` was actually at saved step
1000. Its weights initialized this run; optimizer, learning-rate schedule and
dataset cursor were reset for the larger dataset. Original candidates remain
unchanged. No champion was promoted.

## Data and configuration

- Train: `datasets/trial-split/train`, 52,262 records from the existing trial split.
- Validation: `datasets/trial-continue-20260930/val`, 2,783 records.
- Test: `datasets/trial-continue-20260930/test`, 2,983 records, evaluated after
  training and validation-based checkpoint selection finished.
- To prevent board-position overlap, use the first two FEN fields (board and
  side to move) as the key. Exclude keys from the old 2,975-record calibration
  training dataset and the current training partition from validation/test;
  also exclude validation keys from test. This removes 19 validation and 25
  test records. Existing source data and splits were preserved.
- Data retains its ODbL-1.0 provenance and CC0 teacher labels.
- Config: `trainer/config/trial-continue.toml`; batch 2,048, microbatch 256,
  learning rate 0.0002, 10 warmup steps, cosine decay, seed 823.
- Validate every half epoch; early-stop patience two epochs. Save periodic
  checkpoints every 120 seconds. Pause at 83 C, resume at 78 C.
- Epoch accounting rounds up to 26 full batches; the streaming source consumes
  266,240 samples over the run (approximately 5.09 passes through the records).

## Results

| Metric | Previous checkpoint | New best checkpoint |
|---|---:|---:|
| Validation Huber | 0.157305 | 0.134024 |
| Validation Pearson | 0.435222 | 0.543966 |
| Test Huber | 0.146264 | 0.120181 |
| Test MAE | 0.439672 | 0.382436 |
| Test Pearson | 0.487124 | 0.602538 |

Test Huber decreased by approximately 17.8%. The final update (zero-based step
129) was the validation-selected best. Parameters were checked for finite values.

The exported network loaded in pinned Pikafish. On 12 evenly spaced test
positions, quantized Python evaluation exactly matched engine readback. Maximum
float-versus-engine internal error was 24.5433 on this sample. The old exported
network also matched its checkpoint's quantized evaluation on these 12 positions.
This sample does not establish full-domain quantization parity.

Eight games against the old exported candidate, four paired openings with colors
reversed, seed 20260930, 1,000 nodes per move, Threads 1, Hash 16 MB, 160-ply cap:
**5 wins, 0 draws, 3 losses**. Six games ended in checkmate and two in perpetual
check adjudication; no timeout, crash or illegal-move forfeits occurred. The
score's Wilson lower bound is only 0.3057. This is a small comparative smoke,
not evidence of passing the baseline/teacher/tactical/human strength gates.

## Artifacts (local, gitignored)

- `checkpoints/continue-20260930/latest.pt`: resumable final state.
- `checkpoints/continue-20260930/best.pt`: resumable validation-selected state.
  SHA-256: `be2e68da354b9e39b1b29ad57f136d030f28088eac0afe8c0770488986661db8`.
- `checkpoints/continue-20260930/candidate.nnue` (33,759,924 bytes).
  SHA-256: `eb79d5718ba0d2afb98d419ef0483e83cc67f75149b794a846f46e84cfe53419`.
- `reports/training-20260930/`: preflight and holdout-filter manifests, metrics,
  training log, evaluation JSON, evaluation/export script, and archived match.

## Reproduction

After preparing the filtered holdouts as described above, run from repository root:

```powershell
$env:OMP_NUM_THREADS = '4'
$env:MKL_NUM_THREADS = '4'
.\.venv\Scripts\python.exe -u -m xiangqi_nnue.train `
  --config trainer/config/trial-continue.toml `
  --dataset datasets/trial-split/train `
  --val-dataset datasets/trial-continue-20260930/val `
  --init-checkpoint checkpoints/candidate-101.pt `
  --checkpoint checkpoints/continue-20260930/latest.pt `
  --best-checkpoint checkpoints/continue-20260930/best.pt `
  --metrics reports/training-20260930/metrics.jsonl
```

For interruption recovery, replace `--init-checkpoint ...` with `--resume` and
keep the dataset, batch settings and schedule unchanged. This completed run
already reached its 130-update limit; `--resume` with this config does no more work.
Use separate output paths for a new experiment to preserve these results.

Training code fixes accompanying this run: explicit weight initialization for a
new dataset, valid default shuffle buffer, truthful early-stop checkpoint step,
restored validation-best state on resume, resumable best checkpoints, initial
validation reference, and inclusion of final validation in best-model selection.
Four training tests and eleven config/metrics tests passed, including a small-model
early-stop and resume regression.

Next: expand labeled data beyond the trial partition, keep a fresh final holdout
for future model selection, and run the full strength protocol before promotion.
