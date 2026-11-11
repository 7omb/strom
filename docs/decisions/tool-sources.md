# Tool sources

ruff, pyright and ty only from nixpkgs (dev shell, jail, hooks; tox runs the make targets, see `checks.md`), pinned by
`flake.lock`; Python tools from `uv.lock` (the Makefile runs them with `uv run --frozen`)

**Rejected**

- mypy from nixpkgs (the static typing tests run `sys.executable -m mypy` and skip without it, also in the tox test
  envs)
- both sources (nixpkgs ruff 0.17.2 vs. locked 0.17.3, 2026-11-03)
- only PyPI (the ruff and ty wheels need nix-ld, the pyright wrapper downloads a node that needs it too: none runs in
  the jail)
