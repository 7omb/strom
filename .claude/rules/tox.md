---
paths:
  - "tox.toml"
---

# tox

- Tests on 3.14t: `tox -e 3.14t -- ARGS` (in the jail `uv run --frozen tox`; ARGS are pytest's, e.g. `-k … tests/x.py`
  or `-n 0`); it installs the working tree first. Only a probe script runs on tox's interpreter itself, as
  `PYTHONPATH=$PWD/src .tox/3.14t/bin/python probe.py`: `.tox/3.14t` holds a non-editable strom from its last run
  (`ModuleNotFoundError` for new modules), and the path must be absolute for a script that runs elsewhere (2026-11-11).
- A `3.14t` env on the regular interpreter (`No module named pip`, a `python3.14t` lib directory) comes from a stale
  virtualenv cache, which keys interpreter info by path and mtime (constant in the nix store):
  `rm -r ~/.cache/virtualenv/py_info`.
- A tox env is the active venv of what it runs (`VIRTUAL_ENV`), and the dev shell's tools follow it: so `make` runs
  `uv run --no-active`, and `pyproject.toml` points pyright (`venv`) and ty (`python`) at `.venv`. Test a change of
  `tox.toml` with `tox -r`: an env kept from the old config hid that ty resolved against it (2026-11-11).
