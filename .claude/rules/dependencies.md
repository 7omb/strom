---
paths:
  - "pyproject.toml"
  - "uv.lock"
---

# Dependencies

- pytest-benchmark can lag behind pytest (`AttributeError: … '_nodeid'`): then pin the newest pytest it supports.
- `uv python find --script X` takes no `--python`; pyright's `venv` in `pyproject.toml` outranks `--pythonpath`
  (2026-11-08).
