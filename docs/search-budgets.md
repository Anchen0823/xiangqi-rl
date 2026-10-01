# Search budgets

Difficulty used to select a fixed `go depth` in `native/src/main.cpp`:

```cpp
const int depth = difficulty == "beginner" ? 4 : difficulty == "casual" ? 7
    : difficulty == "advanced" ? 10 : difficulty == "expert" ? 18 : 14;
```

That made the reported depth a hard-coded ceiling, identical for every position
and every machine. A level could never look further than its number, and the
"高手" tier was capped at ply 18 no matter how much time was available.

## Current design

`difficultyLimits()` in `native/src/search.cpp` maps each level to a
`SearchLimits { nodes, millis, maxDepth }`:

| Level | Nodes | Clock | Depth cap |
|---|---:|---:|---:|
| 入门 beginner | 30,000 | 120 ms | 6 |
| 休闲 casual | 200,000 | 400 ms | 12 |
| 进阶 advanced | 1,200,000 | 1,200 ms | 20 |
| 棋社 club | 3,000,000 | 2,000 ms | 24 |
| 高手 expert | 6,000,000 | 4,000 ms | 32 |

`PikafishClient::analyze` now takes these limits and issues `go nodes` together
with `go movetime` and a depth cap. The node budget is primary because it is
reproducible and independent of machine load; the clock bounds a weak network
on a slow machine, and the depth cap guarantees the UI always receives an
answer. Depth became a *result* of the budget and the position instead of a
constant.

## Measured effect

`reports/search-budget-probe.ps1` drives the built engine through a short
opening and records what each tier actually reached, on this machine with
`checkpoints/expanded-20260930/candidate.nnue`:

| Level | Depth before | Depth reached | Nodes reached | Node budget | Wall time | Binding limit |
|---|---:|---:|---:|---:|---:|---|
| 入门 beginner | 4 | 6 | 3,335 | 30,000 | 13 ms | node budget (11%) |
| 休闲 casual | 7 | 12 | 26,144 | 200,000 | 41 ms | node budget (13%) |
| 进阶 advanced | 10 | 19 | 752,032 | 1,200,000 | 1.2 s | clock |
| 棋社 club | 14 | 24 | 1,293,664 | 3,000,000 | 2.0 s | clock |
| 高手 expert | 18 | 26 | 2,515,339 | 6,000,000 | 4.0 s | clock |

That first run exposed a defect: the legacy `go depth` request was still being
sent alongside the budget, so the old depth cap stayed the real ceiling for the
low tiers. 入门 and 休闲 stopped at 6 and 12 — 11% and 13% of their node budgets
— and the tier ordering was depth ordering, not budget ordering.

Removing the legacy depth request changed the outcome on the same positions and
the same network, re-measured with the same probe:

| Level | Depth | Nodes | Budget | Wall time | Binding limit |
|---|---:|---:|---:|---:|---|
| 入门 beginner | 11 | 30,025 | 30,000 | 43 ms | node budget (100%) |
| 休闲 casual | 18 | 200,224 | 200,000 | 292 ms | node budget (100%) |
| 进阶 advanced | 21 | 799,357 | 1,200,000 | 1,206 ms | clock |
| 棋社 club | 24 | 1,217,808 | 3,000,000 | 2,011 ms | clock |
| 高手 expert | 26 | 2,095,102 | 6,000,000 | 4,004 ms | clock |

Node counts are deliberately reproducible budgets rather than quotas, and the
counters report a slightly over-budget total (30,025 against 30,000) because the
last check happens at a batch boundary. 入门 and 休闲 now spend their whole node
budget and stop on the budget itself; the clock binds from 进阶 upward. The
depth cap is no longer the binding constraint at any tier, so a position that
resolves quickly still returns early. Repeated probes differ by a few percent,
because the probe enters the position through a fixed move list and
multi-threaded search does not visit an identical tree twice; a single opening
position is still only one sample.

## What this does not prove

Reaching a deeper ply is not a strength claim. The tiers are still ordered by
budget rather than measured strength, no play match has been run across the
change, and the protocol in `strength-protocol.md` still applies unchanged.
Equal-node match settings remain the comparison basis, because equal-node play
is what makes two networks comparable independently of this budget work.
