---
paths:
  - "tests/**"
  - "benchmarks/**"
---

# Tests

Conventions for tests: `ARCHITECTURE.md`. How a change to tests is checked (collected IDs, injected bugs): skill
`validate-change`.

- Every sleep must be intentional; a docstring where it occurs explains why it is needed.
- After a failing run, rerun only the failures: `make test ARGS="--lf"`; `--sw` (stepwise) stops at the first and starts
  there next time.
- Async tests run on pytest-asyncio (`asyncio_mode = "auto"`, a loop per test): a test that uses the `pools` fixture or
  `outputs_of` is `async def` (the reference semantics there: `helpers.meaning_async`); never call `asyncio.run` inside
  one. Hypothesis tests stay sync on `helpers.collect`/`meaning`/`stats_of`, each an `asyncio.run` with its own pools
  (`meaning` is `testing.evaluate`: not inside an async test).
- CPython closes unreferenced generators by garbage collection and the event loop closes async generators at shutdown;
  closing through a wrapper generator is masked by reference counting (an unreferenced wrapper closes what it delegates
  to). Tests of closing keep references, use closable non-generator iterators, inspect the generator state
  (`endless_stage`) and check inside the running loop; otherwise a missing `close()` goes unnoticed.
- The tests have no packages (no `__init__.py`): pytest imports a test module by its base name, so that name is unique
  in `tests/` (`tests/tools/hooks/test_hook_events.py` beside `tests/metrics/test_events.py`), and mypy takes a second
  `conftest.py` as a duplicate module: fixtures of a sub-directory go into `tests/conftest.py`, helpers into a module
  beside `helpers.py` (`tool_helpers.py`), which all three checkers find (2026-11-11).
