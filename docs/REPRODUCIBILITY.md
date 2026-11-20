# Reproducibility

## Determinism guarantees

| Source | Mechanism |
|---|---|
| Piece sequence | Per-player `random.Random(seed)` seven-bag (`environment/randomizer.py`) |
| Garbage holes | Per-player `random.Random(garbage_seed)` |
| Opponent randomness | Owned `random.Random` seeded per match/episode |
| Match seeds | `VersusMatch` derives four independent seeds from one match seed |
| Environment resets | Auto-reset advances the episode seed by 7919 (deterministic) |
| Neural sampling | Torch RNG seeded at agent construction (`seed` argument) |
| Replays | Store seeds + per-tick actions/events + frames; verification re-simulates |

Replay verification is a hard check, not a claim:

```bash
.venv/bin/python -m tetrisrl replay --file results/replays/<id>.json --verify
```

If a mechanics change alters outcomes, verification of old replays fails loudly by
design; the archived replays and the commit they were produced with are the record.

## Reproducing the experiments

```bash
# 1. Mechanics gate
.venv/bin/python -m pytest tetrisrl/tests -q

# 2. Run the experiment matrix (writes results/tetrisrl.sqlite3 + results/runs/*)
.venv/bin/python scripts/run_experiments.py --matrix main

# 3. Evaluate final checkpoints against all baselines
.venv/bin/python scripts/run_experiments.py --matrix evaluate

# 4. Round-robin tournament with replays
.venv/bin/python -m tetrisrl tournament --participants random,heuristic,search --seeds 5

# 5. Build tables/plots
.venv/bin/python scripts/make_report.py
```

Each run directory contains:

```
results/runs/<run_id>/
  config.json            exact training configuration
  training_state.json    curriculum position (resume)
  checkpoints/step_*.pt  periodic checkpoints
  checkpoints/best_*.pt  best evaluation checkpoint (never overwritten)
  checkpoints/final_*.pt final checkpoint
  eval/eval_<step>_<opponent>.json  full per-match evaluation records
```

The SQLite database (`results/tetrisrl.sqlite3`, override with `TETRISRL_DB`) stores
run metadata, the full metric series, checkpoint index, tournaments and matches.

## Seeding policy

* Training seeds: `0` for the main matrix, `1..3` for seed-variance checks.
* Evaluation uses paired seeds: match `i` uses `eval_seed + i`; the evaluated agent
  plays half the matches on each side to remove side bias.
* Confidence intervals: Wilson score interval for win rates, normal approximation
  for means; sample sizes are always reported (`n`).

## Hardware

Experiments were executed on:

* AMD Ryzen 5 7500F class CPU (12 threads available), 30 GB RAM
* NVIDIA RTX 5060 Ti 16 GB, driver 620.70.06, PyTorch 2.14.1+cu130
* Linux (CachyOS kernel 7.3), Python 3.12.15

Simulation throughput is reported per run in the `throughput/steps_per_sec` metric;
`python -m tetrisrl benchmark` measures the current machine.

## Environment caveat encountered

After a failed suspend/resume the NVIDIA driver returned `-EIO` on device open
(`nvidia-smi: No devices were found`) while the GPU was physically present. A
reboot restored it. A CPU-only `torch` wheel cannot use the GPU even when the
device works; the CUDA wheel must be installed (see README).
