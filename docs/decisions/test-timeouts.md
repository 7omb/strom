# Test timeouts

A test has 120 s, by pytest-timeout's thread method, which ends the process, because under the signal method a
Hypothesis test that hangs is never ended (2026-11-12). pytest-timeout is in use since 2026-11-11: past sessions had
wrapped 254 commands in `timeout` by hand, and a hang showed no stack. The slowest test took 10.6 s under the `ci`
profile (2026-11-13).

Decided with it:

- A run of a sync test has 5 s (`helpers.RUN_LIMIT_TIME`, also in `check_runs` of the law tests, 2026-11-13). A stalled
  run then fails its Hypothesis example, which shrinks to a minimal pipeline, where pytest-timeout would end the process
  with no example. Each shrink of a stall waits the limit: an injected stall of `loop` (its body's input never shut
  down) shrank to `f=inc` in 11 s at 5 s and ran past the 120 s timeout at 30 s. The suite passed twice under the `ci`
  profile with 1 s.
- `kill -USR1` of a test process writes its stacks to `.checks/stacks/` (`tests/conftest.py`), because stderr is
  pytest's capture.

**Rejected**

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
- the stacks on SIGUSR1 to stderr (pytest captures the file descriptor: the dump went into a deleted temporary file)
