---
name: validate-change
description: The checks a change to strom needs before it is reported done (CLAUDE.md, Process) - reproduce the problem first, then the suite, interleaved A/B benchmarks, typing diffs of mypy, pyright and ty against HEAD, test-ID diffs for restructured tests and an injected bug for changed tests. Use when starting a change to src/, tests/, benchmarks/, examples/ or bin/, and before reporting it done.
allowed-tools: Bash(git status:*), Bash(git diff:*)
---

# Validating a change

Reproduce the problem before, validate after. The scripts in `bin/` do the mechanical parts; usage and contract: each
one's docstring (`uv run --frozen python bin/<script>.py --help`).

Uncommitted changes now:

!`git status --short`

## Which steps

| Change | Steps |
| -- | -- |
| Library (`src/`) | 1, 2, 3, 4; 6 if tests changed |
| Tests only | 1, 2, 4, 6; 5 if they were moved, renamed or split |
| Benchmarks | 2, 4; their results with `make bench-results` |
| `bin/`, examples, config | 2, 4, plus running what changed on a case it must handle |
| Docs only (`*.md`, docstrings) | `make lint` (`bin/check_docs.py`: the paths and names they cite are tracked) |

`REV` below is the revision the change starts from: `HEAD` while it is uncommitted, else e.g. `main~2`; `:index` is the
staged state (stage a version to compare later edits with, no commit needed).

## Steps

1. **Reproduce** before the first edit: a failing test, or a measurement (step 3 measures it against the change).

2. **Suite**: `make check` (lint, type, tests, examples), or `uv run --frozen python bin/check.py` for one line per
   target and the full output of failures only. A test that fails or newly skips is part of the report, with its output.

3. **Benchmarks**: `uv run --frozen python bin/ab.py REV . -- -k "<affected benchmarks>"` (interleaved runs; add
   `BENCH_SCALE=0.2` for a first look). Run it in the background (`run_in_background`): one benchmark group with the
   default 9 runs per side takes several minutes, past a foreground timeout. Report the ratios with their p-values:
   timing claims need repeated, interleaved runs, a single run is no evidence. The full `make bench` only when the user
   asks.

4. **Typing**: `uv run --frozen python bin/typing_snapshot.py diff --against REV`. Every added diagnostic is a finding;
   `tests/` must get no new ty diagnostics.

5. **Restructured tests**: `uv run --frozen python bin/collect_ids.py diff --against REV`; explain every removed and
   added ID.

6. **Changed or new tests**: inject the bug they target into a copy of the library and check that the new tests catch it
   and, if they replace old ones, what the old ones did:

   - `uv run --frozen python bin/mutant.py --replace src/strom/<module>.py "<old>" "<new>" -- -x -q -k <tests>`
   - `... --tests-from REV` for the old tests.

   Outcomes: `caught` is the goal; `missed` means the test does not check what it claims; `hung` needs a narrower `-k`;
   exit code 3 (no verdict) means the tests fail without the bug too. Typical bugs: a concurrency limit ±1, an end of
   stream or a close left out, a count off by one. A failure flag shared by all runs hangs and says nothing: inject a
   bug that a narrow `-k` can catch.

## Report

State each step's outcome: done and passed, done with findings (quote them), or skipped and why. Never weaken an
assertion to make a step pass (`ARCHITECTURE.md`, Conventions).
