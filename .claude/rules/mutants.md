---
paths:
  - "bin/mutant.py"
  - "tools/strom_tools/change_checks/mutants.py"
---

# Mutants

- A mutant of the tools: `bin/mutant.py --replace tools/strom_tools/<module>.py OLD NEW -- -q tests/tools/<test>`; the
  copy holds `tools/`, `bin/` and the hook command beside `src/`.
- `bin/mutant.py` has its own `--timeout` (default 300 s): never wrap it in `timeout`, which kills it before its verdict
  and orphans its pytest and forkserver workers; for a mutant that may hang, a short `--timeout` (2026-11-08).
- A bug that a narrow `-k` reports as `missed` may be caught elsewhere: run it against the whole suite
  (`bin/mutant.py … -- -q -n auto`) before writing a test for it (2026-11-11: a check run also after an error passed
  `-k product` in `test_streaming.py` and failed a test in `tests/interpreters/test_offloaders.py`).
