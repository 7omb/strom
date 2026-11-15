---
paths:
  - "bin/ab.py"
  - "tools/strom_tools/change_checks/benchmark_comparison.py"
  - "tools/strom_tools/commands/ab.py"
---

# A/B comparisons

- `bin/ab.py` runs every selected benchmark 2 × RUNS times: a broad `-k` with the latency and one-to-many rows took 9
  minutes per run at `BENCH_SCALE=0.5` (2026-11-11). Select the rows the change touches, lower the scale or `-n`, and
  run nothing else meanwhile (with tests beside it, reference rows moved by 40% and more). Stopping it leaves its
  current pytest run alive in a separate session: find it under `/proc` and kill it.
- A cost of about 1% needs more runs: 0.6 µs per run on `run_overhead_one_item` showed with `-n 15` (p 0.007 and 0.044)
  and not with 9 (p 0.10 and 0.12; pinned, 2026-11-11).
- Pin every comparison on a CPU with cores of two speeds (unpinned, `bin/ab.py` names the fast ones): a one-pool-task
  row took 13.9 ms unpinned and 6.4 ms on the P-cores, and an unpinned comparison showed 1.49 (p 0.018) where the pinned
  one shows 1.00 (2026-11-11, an i7-12700H: CPUs 0–11). Pin a probe that measures with `taskset -c 0-11 CMD`.
