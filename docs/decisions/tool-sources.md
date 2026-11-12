# Tool sources

ruff, pyright and ty only from nixpkgs (dev shell, jail, hooks; tox runs the make targets, see `checks.md`), pinned by
`flake.lock`; Python tools from `uv.lock` (the Makefile runs them with `uv run --frozen`). Commands that no check runs
come from nixpkgs too (2026-11-11): py-spy (0.4.2, the first with Python 3.14) and hyperfine in the dev shell and the
jail; of procps and util-linux only `ps`, `pgrep`, `pkill` and `taskset`, linked one by one as `python3.14t` is, not the
collections

**Rejected**

- py-spy in the dev group of `uv.lock` (its wheel is a static binary and runs in the jail, but every `uv sync` would
  install a profiler that no check runs)
- psmisc for `pstree` (`ps -ef --forest` shows the tree)
- mypy from nixpkgs (the static typing tests run `sys.executable -m mypy` and skip without it, also in the tox test
  envs)
- both sources (nixpkgs ruff 0.17.2 vs. locked 0.17.3, 2026-11-03)
- only PyPI (the ruff and ty wheels need nix-ld, the pyright wrapper downloads a node that needs it too: none runs in
  the jail)
