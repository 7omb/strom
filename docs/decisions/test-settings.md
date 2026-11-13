# Test settings

`make test`/`cov` and tox run pytest with `-n auto` (suite 48 -> 10–22 s, 20 cores, 2026-11-03); Hypothesis profiles
`dev` (default) and `ci` in `tests/conftest.py`, chosen with the plugin's `--hypothesis-profile` (suite 47 / 187 s at 60
/ 300 examples, 2026-11-03); the static typing tests keep mypy's cache in `.mypy_cache`, one per configuration,
interpreter and xdist worker (both tests 3.6 -> 0.44 s warm). Since 2026-11-11: warnings are errors (`filterwarnings`;
the suite passed with them and under `PYTHONDEVMODE=1 PYTHONASYNCIODEBUG=1`, which took 68 s against 36 s); a coverage
floor in `make check` (`fail_under`); pytest-timeout with 120 s per test (past sessions wrapped 254 commands in
`timeout` by hand, and a hang showed no stack; the slowest test took 10.6 s under the `ci` profile, 2026-11-13), by its
thread method, which ends the process (2026-11-12: under the signal method a stalled law test ran for 15 min);
pytest-randomly (order dependence; four random orders passed; its first run found that `bin/collect_ids.py` saved the
IDs in run order, now in definition order with `-p no:randomly`, as the benchmarks run); pytest-repeat for a suspected
flake (`--count`, past sessions looped over suite runs); `kill -USR1` of a test process writes its stacks to
`.checks/stacks/` (`tests/conftest.py`: stderr is pytest's capture).

Since 2026-11-12 a generated stage gives at most `strategies.MAX_OUTPUTS` outputs per input (how: its docstring in
`tests/strategies.py`): the laws compose a generated stage with itself (a loop feeds items back, `interchange` applies a
stage twice), and Hypothesis's mutation phase built nests of `product`s over 1:3 leaves whose outputs multiplied (3^k
per pass). Measured (2026-11-12): five such leaves in `loop_unfolds` gave 16,593 outputs for one input (0.7 s), one
example took 434 s; all law tests 30 times, interleaved, 390 and 76 s on HEAD (slowest test 48 s, one ended by the
timeout) against 50 and 49 s (slowest 2.9 s).

Since 2026-11-13 a run of a sync test (`helpers.RUN_LIMIT_TIME`, also in `check_runs` of the law tests) has 5 s: a
stalled run fails its Hypothesis example, which shrinks to a minimal pipeline, where pytest-timeout would end the
process with no example. Each shrink of a stall waits the limit: an injected stall of `loop` (its body's input never
shut down) shrank to `f=inc` in 11 s at 5 s and ran past the 120 s timeout at 30 s; the suite passed twice under the
`ci` profile with 1 s.

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
- pytest-timeout's signal method (the default): it raises `Failed` in the test, which Hypothesis takes for a failing
  example; it then runs the next example without a timer, so a `@given` test that hangs is never ended (2026-11-12). And
  the exception, raised by a signal handler between any two bytecodes, can land where Python ignores it (a weakref
  callback, a finaliser; asyncio's callbacks re-raise only `SystemExit` and `KeyboardInterrupt`) or halfway through
  asyncio's bookkeeping, and the run it interrupts then waits forever: the stall of a law test, 15 min at 0% CPU with
  every task waiting on a queue (2026-11-12). Reproduced (2026-11-13): an exception raised from `SIGALRM` at random
  times during a run stalled a run within 10 rounds, a `KeyboardInterrupt` as well; 1,453 runs interrupted by a real
  SIGINT, which `asyncio.run`'s handler turns into a cancellation, never stalled.
- pytest's own `faulthandler_timeout` instead of pytest-timeout (dumps the stacks but lets the hang go on)
- a timeout of 300 s per test (it allowed for the fan-out of generated law examples, up to 232 s, until their outputs
  were bounded; a hang takes that long to end)
- a bound by measurement, `assume` on the outputs of a generated stage (a meaning per example, and it rejects examples
  only after they were built); fewer `max_leaves` (a nest of 1:3 leaves stays possible); `filter` for the bound (a
  retried draw puts the strategy's repr, 34 kB, into an event: a `HypothesisWarning`, an error here)
- the stacks on SIGUSR1 to stderr (pytest captures the file descriptor: the dump went into a deleted temporary file)
