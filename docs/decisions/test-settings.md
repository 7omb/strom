# Test settings

`make test`/`cov` and tox run pytest with `-n auto` (suite 48 -> 10–22 s, 20 cores, 2026-11-03); Hypothesis profiles
`dev` (default) and `ci` in `tests/conftest.py`, chosen with the plugin's `--hypothesis-profile` (suite 47 / 187 s at 60
/ 300 examples, 2026-11-03); the static typing tests keep mypy's cache in `.mypy_cache`, one per configuration,
interpreter and xdist worker (both tests 3.6 -> 0.44 s warm)

**Rejected**

- `-n auto` in `addopts` (pytest-xdist disables the benchmarks with only a warning; one test 1.8 -> 2.8 s)
- `--dist worksteal` (no gain)
- an environment variable for the profile (the plugin's option exists; the test module's own profile had silently
  overridden it)
- one cache for both configurations (they invalidate each other's entries)
- one cache for all processes (contention for mypy's SQLite cache, 5 s lock timeout)
- temporary caches (cold every run)
