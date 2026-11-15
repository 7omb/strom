# Tool sources

ruff, pyright and ty come from nixpkgs only, pinned by `flake.lock`, because their PyPI packages need nix-ld and so do
not run in the jail; the Python tools come from `uv.lock`. The first three serve the dev shell, the jail and the hooks
(tox runs the make targets, `docs/decisions/checks.md`); the Makefile runs the Python tools with `uv run --frozen`.

Decided with it:

- Commands that no check runs come from nixpkgs too (2026-11-11): py-spy (0.4.2, the first with Python 3.14) and
  hyperfine, in the dev shell and the jail.
- Of procps and util-linux the jail has only `ps`, `pgrep`, `pkill` and `taskset`, linked one by one as `python3.14t`
  is, not the collections.
- The jail has only `python3.14t` of the free-threaded build on PATH (2026-11-08): the jail reverses the package order,
  so `uv -p 3.14` had picked 3.14t.

**Rejected**

- py-spy in the dev group of `uv.lock` (its wheel is a static binary and runs in the jail, but every `uv sync` would
  install a profiler that no check runs)
- psmisc for `pstree` (`ps -ef --forest` shows the tree)
- mypy from nixpkgs (the static typing tests run `sys.executable -m mypy` and skip without it, also in the tox test
  envs)
- both sources (nixpkgs ruff 0.17.2 vs. locked 0.17.3, 2026-11-03)
- only PyPI (the ruff and ty wheels need nix-ld, the pyright wrapper downloads a node that needs it too: none runs in
  the jail)
- setting `UV_PYTHON` in the jail alone (covers uv's default, not `-p 3.14` or other tools that search PATH)
- reversing `pythonVersions` for the jail (relies on how jail.nix orders PATH)
