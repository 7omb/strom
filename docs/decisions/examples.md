# Examples

Reference code for users, kept correct and apart from the tests: each `examples/*.py` checks its own results and exits 0
or 1, reporting each wrong result on stderr; `bin/run_examples.py` runs them one at a time in their own process groups,
with a timeout per example, from `make check` and tox; the tests cover the library on their own (removing the example
tests lost only `default_cpu_workers`/`default_io_workers`, now tested; functions of a `__main__` script on the process
backend: `test_process_backend_runs_functions_of_the_main_script`). Each example is a uv script (2026-11-08): a PEP 723
header with its dependencies (strom as an editable path source) and a lock of its own (`<name>.py.lock`), run with
`uv run --script --locked` and type-checked against its own environment (`--type`, part of `make type`), so the dev
environment carries no example's dependencies and examples may pin different versions of one package

**Rejected**

- example dependencies in the dev group (one version per package for all examples, and the dev environment grows with
  every example)
- a uv workspace member per example (a `pyproject.toml` and directory for each one-file script)
- `ignore_missing_imports` for example dependencies (their API unchecked)
- a copy of the example's pipelines in `tests/` (`pipelines_under_test.py`: nothing kept it in step with the example,
  and the tests named after the example checked the copy)
- tests importing the examples (tests depend on reference code)
- `tests/test_examples.py`, also behind a deselected marker (reference code in the suite; nothing runs it by default)
- running them in-process (`__main__` would be pytest: the process backend could not import their functions)
- a plain make loop (no timeout, no killing the pool workers)
