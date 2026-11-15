# Test settings

`make test`, `make cov` and tox run pytest with `-n auto`, because the suite then takes a quarter to a half of its
serial time (2026-11-03).

Decided with it:

- The Hypothesis profiles `dev` (default) and `ci` are in `tests/conftest.py`, chosen with the plugin's
  `--hypothesis-profile`.
- The static typing tests keep mypy's cache in `.mypy_cache`, one per configuration, interpreter and xdist worker.
- Warnings are errors (`filterwarnings`, 2026-11-11). The suite passed with them and under
  `PYTHONDEVMODE=1 PYTHONASYNCIODEBUG=1`, which took 68 s against 36 s.
- `make check` has a coverage floor (`fail_under`, 2026-11-11).
- pytest-randomly runs the tests in a random order (2026-11-11): four random orders passed. Its first run found that
  `bin/collect_ids.py` saved the IDs in run order; it now saves them in definition order with `-p no:randomly`, as the
  benchmarks run.
- pytest-repeat serves a suspected flake (`--count`, 2026-11-11); past sessions looped over suite runs.
- The timeout of a test and the stacks of a hung one: `docs/decisions/test-timeouts.md`. The bound on the outputs of a
  generated stage: `docs/decisions/generated-stages.md`.

**Measured**

- The suite took 48 s serial and 10–22 s with `-n auto` (20 cores, 2026-11-03).
- At 60 examples (`dev`) the suite took 47 s, at 300 (`ci`) 187 s (2026-11-03).
- Both static typing tests took 3.6 s with a cold cache and 0.44 s with a warm one (not dated).

**Rejected**

- `-n auto` in `addopts` (pytest-xdist disables the benchmarks with only a warning; one test 1.8 → 2.8 s)
- `--dist worksteal` (no gain)
- an environment variable for the profile (the plugin's option exists; the test module's own profile had silently
  overridden it)
- one cache for both configurations (they invalidate each other's entries)
- one cache for all processes (contention for mypy's SQLite cache, 5 s lock timeout)
- temporary caches (cold every run)
- dev mode and asyncio debug in `make test` (twice the time; a tox env could run it)
- pytest-rerunfailures (hides a flake instead of finding it)
