---
paths:
  - "Makefile"
  - ".pre-commit-config.yaml"
  - "tox.toml"
  - "tools/strom_tools/workspace/**"
  - "tools/strom_tools/hooks/**"
---

# Make targets

- The checks and the fixers are defined in the `Makefile` only; tox, pre-commit and the Claude Code hooks run its
  targets (`make fix FILES=…`, `make lint-python FILES=… ARGS=…`, `make lint-docs`): a hook or a script that needs ruff,
  mdformat or the docs check calls make, not the tool (`docs/decisions/checks.md`).
