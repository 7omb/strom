---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
  - "benchmarks/**/*.py"
  - "examples/**/*.py"
  - "tools/**/*.py"
---

# Typing – false positives of one checker

The convention (`ARCHITECTURE.md`, Conventions): the code keeps the shape the other two checkers accept, and the one
that is wrong gets its own ignore comment on the line, with a dated entry here. Each checker has a comment of its own
and fails once it no longer needs one, so an ignore expires with its bug:

| Checker | Comment | What reports an unused one |
| -- | -- | -- |
| mypy | `# type: ignore[code]` | strict (`warn_unused_ignores`) |
| pyright | `# pyright: ignore[rule]` | `reportUnnecessaryTypeIgnoreComment` |
| ty | `# ty: ignore[rule]` | `unused-ignore-comment` as an error |

pyright does not read `# type: ignore` (`enableTypeIgnoreComments` is off), and ty only one without a code: a line that
all three reject on purpose carries three comments (`tests/test_init.py`). The checkers' limitations by area:
`typing-api.md`, `typing-stdlib.md`, `typing-tools.md` (here).

Ignored now:

- ty 0.0.91 (2026-11-11): a generic function that may return None (`next_item[O](key) -> NextItem[O] | None`) as the
  argument of a generic `run(fn: Callable[[A], B], arg: A) -> B`: ty solves `B` to None ("Expected `(...) -> None`"), at
  most calls but not at all (the probe `.checks/probes/p6_ty_generic_none.py`; rerun it with a new ty: `ty check FILE`);
  mypy and pyright accept them. `# ty: ignore[invalid-argument-type]` at the calls it reports: `Offloader.streamed`
  (`strom._interpreters.offloaders`), `check_streaming_backend` (`strom.testing`),
  `tests/runtime/test_iterator_registry.py`, `tests/runtime/test_thread_backend.py`. When ty reports one of them as
  unused, remove it; when it reports another call of `next_item`, add one. The same with `partial(f, ...)` of such a
  function (2026-11-10).
- mypy 2.4 `possibly-undefined` (2026-11-11): a name assigned in every arm of an exhaustive `match` but one that
  returns; `# type: ignore[possibly-undefined]` at its uses (`strom_tools.commands.snapshot_commands.save_or_diff`).
- mypy `exhaustive-match` and pyright `reportMatchNotExhaustive` on nested class patterns (`assoc_sum` in
  `tests/stages/test_combinators.py`, 2026-11-11): both ignores on the `match` line.
- pyright 1.1.414: `isinstance(group, RunFailed)` on the group `pytest.RaisesGroup` passes to `check` is "never an
  instance" (`RunFailed` is an `ExceptionGroup[Exception]`), but it is (`tests/interpreters/test_streaming.py`,
  2026-11-11).
