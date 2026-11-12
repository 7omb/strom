# Test settings

`make test`/`cov` and tox run pytest with `-n auto` (suite 48 -> 10–22 s, 20 cores, 2026-11-03); Hypothesis profiles
`dev` (default) and `ci` in `tests/conftest.py`, chosen with the plugin's `--hypothesis-profile` (suite 47 / 187 s at 60
/ 300 examples, 2026-11-03); the static typing tests keep mypy's cache in `.mypy_cache`, one per configuration,
interpreter and xdist worker (both tests 3.6 -> 0.44 s warm). Since 2026-11-11: warnings are errors (`filterwarnings`;
the suite passed with them and under `PYTHONDEVMODE=1 PYTHONASYNCIODEBUG=1`, which took 68 s against 36 s); a coverage
floor in `make check` (`fail_under`); pytest-timeout with 300 s per test (past sessions wrapped 254 commands in
`timeout` by hand, and a hang showed no stack; the slowest test took 3.4 s, the rare fan-out of law examples 232 s);
pytest-randomly (order dependence; four random orders passed; its first run found that `bin/collect_ids.py` saved the
IDs in run order, now in definition order with `-p no:randomly`, as the benchmarks run); pytest-repeat for a suspected
flake (`--count`, past sessions looped over suite runs); `kill -USR1` of a test process writes its stacks to
`.checks/stacks/` (`tests/conftest.py`: stderr is pytest's capture)

**Rejected**

- `-n auto` in `addopts` (pytest-xdist disables the benchmarks with only a warning; one test 1.8 -> 2.8 s)
- `--dist worksteal` (no gain)
- an environment variable for the profile (the plugin's option exists; the test module's own profile had silently
  overridden it)
- one cache for both configurations (they invalidate each other's entries)
- one cache for all processes (contention for mypy's SQLite cache, 5 s lock timeout)
- temporary caches (cold every run)
- dev mode and asyncio debug in `make test` (twice the time; a tox env could run it)
- pytest-rerunfailures (hides a flake instead of finding it)
- pytest's own `faulthandler_timeout` instead of pytest-timeout (dumps the stacks but lets the hang go on)
- a timeout of 120 s per test (the known fan-out of generated law examples would fail `make check` now and then, before
  its task is done)
- the stacks on SIGUSR1 to stderr (pytest captures the file descriptor: the dump went into a deleted temporary file)
