# Checks

One definition of each check, a make target (2026-11-11); `make check` is lint, type, test and examples. tox runs the
targets (the envs of a Python version, and the benchmarks' results, on their own interpreter against the installed
package), and so do the git hooks: at a commit `make lint` and `make type`, beside the fixers of the changed files; at a
push `make check`, so the tests run without anyone asking (`pre-commit install` sets up both hooks; direnv does it). The
fixers are a target too (`make fix`, on every file or on `FILES`): ruff's fixes and its formatter, and mdformat as the
commit hook installs it. The commit hook, the Claude Code hooks and `bin/rename.py` run that target and the parts of
`lint` (`lint-python`, which takes `FILES` and ruff's options, and `lint-docs`) instead of the tools

**Rejected**

- the commands spelled out again per tool, in `tox.toml` and as hooks (until 2026-11-11: they drifted, as
  `bin/check_docs.py` ran in `make lint` only, and none of them ran the tests by itself)
- the Claude Code hooks and `bin/rename.py` calling ruff, pre-commit and `bin/check_docs.py` themselves (until
  2026-11-11: a third spelling of the fixers beside the commit hook's, and of parts of lint)
- `fix` also reporting what it could not fix (a failing `ruff check` would end the recipe before mdformat ran, and the
  commit hook showed every leftover twice: the report is `lint`'s)
- nixpkgs-fmt in `fix` (it has one definition, the commit hook, and no hook of Claude Code formats nix files)
- checks in `flake.nix` as one more, hermetic gate (`nix flake check` with the venv from `uv.lock` via uv2nix,
  2026-11-04 to 2026-11-10): a fourth definition, which the jail could not run (no `nix`), and whose sandbox has neither
  uv nor network, so that the examples, uv scripts with locks of their own, ran with the interpreter's packages only (a
  mode `--direct` of `bin/run_examples.py`), skipping those with further dependencies
- for such checks in nix: Python packages from nixpkgs (a second source of versions, see `tool-sources.md`)
- for such checks in nix: `uv sync` in the check (no network in the sandbox)
