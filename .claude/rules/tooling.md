---
paths:
  - "flake.nix"
  - "flake.lock"
  - "tox.toml"
  - "pyproject.toml"
  - "uv.lock"
  - ".envrc"
  - "Makefile"
  - ".pre-commit-config.yaml"
  - "bin/**"
  - ".claude/hooks/**"
---

# Tooling gotchas (observed)

- pytest-benchmark can lag behind pytest (`AttributeError: … '_nodeid'`): then pin the newest pytest it supports.
- A tox `3.14t` env on the regular interpreter (`No module named pip`, a `python3.14t` lib directory) comes from a stale
  virtualenv cache: it keys interpreter info by path and mtime (constant in the nix store), so an entry from a polluted
  environment (`_PYTHON_SYSCONFIGDATA_NAME`) survives: `rm -r ~/.cache/virtualenv/py_info`.
- Claude Code runs in the jail of `flake.nix` (`jailed-claude`): it has the packages of `claudePkgs` only, no `nix` and
  no git identity.
- The checks and the fixers are defined in the `Makefile` only; `tox.toml`, `.pre-commit-config.yaml` and the Claude
  Code hooks run its targets (`make fix FILES=…`, `make lint-python FILES=… ARGS=…`, `make lint-docs`): a hook or a
  script that needs ruff, mdformat or the docs check calls make, not the tool. A tox env is the active venv of what it
  runs (`VIRTUAL_ENV`), and tools from the dev shell follow that: so `make` runs `uv run --no-active`, and
  `pyproject.toml` points pyright (`venv`) and ty (`python`) at `.venv`. Test a change of `tox.toml` with `tox -r`: an
  env kept from the old config still had its packages and hid that ty resolved against it (2026-11-11).
- `bin/check_docs.py` accepts a cited file only when it is tracked: `git add` a new file that a doc cites (staging is no
  commit). Never `git add -N`: with an intent-to-add entry `git stash create` fails ("Entry … not uptodate. Cannot
  merge") and the revision `:index` gets an empty file (probed 2026-11-11).
- Writing `.claude/settings.json`, creating files in `.claude/hooks/` and adding `allowed-tools` to a skill are blocked
  for Claude (self-modification; editing an existing hook module or a skill's text is not, 2026-11-06): prepare the
  files in `.checks/claude/` (the scratchpad is emptied on restart) and ask the user to copy them.
- Never `git stash` / `git stash pop` to test the baseline: the work is mostly staged, and `pop` without `--index`
  unstages it (repaired 2026-11-10 with `git read-tree` of the dropped stash's index parent). A baseline is
  `git stash create` (a commit, nothing changes) for `bin/ab.py`, `bin/mutant.py --tests-from`.
- Tests on 3.14t: `tox -e 3.14t -- ARGS` (in the jail `uv run --frozen tox`; ARGS are pytest's, e.g. `-k … tests/x.py`
  or `-n 0`), which installs the working tree first (a few seconds). Only a probe script runs on tox's interpreter
  itself, as `PYTHONPATH=$PWD/src .tox/3.14t/bin/python probe.py`: `.tox/3.14t` holds a non-editable strom from its last
  tox run (`ModuleNotFoundError` for new modules), and the path must be absolute for a script that runs in another
  directory (2026-11-11).
- A command started in the background notifies when it ends: wait for that, never beside it with an `until … sleep` loop
  or a `sleep N; tail` (2026-11-11: eleven such loops in one session; one waited for a line that never came, one ran
  into the tool's time limit). To wait for something other than the end of a command, use the Monitor tool.
- `bin/mutant.py` has its own `--timeout` (default 300 s): never wrap it in `timeout`, which kills it before its verdict
  and orphans its pytest and forkserver workers; for a mutant that may hang, pass a short `--timeout` (2026-11-08).
- An example's lock (`examples/<name>.py.lock`) records strom's dependency groups (its editable path source): after
  changing them in `pyproject.toml`, `python bin/run_examples.py --lock`, or every example fails as a stale lock.
  `uv python find --script X` takes no `--python`; pyright's `venv` in `pyproject.toml` outranks `--pythonpath`
  (2026-11-08).
- `git mv` (also that of `bin/rename.py`, which moves a tracked file with it) stages the move, so `:index` then holds
  the new paths with the old contents (imports of the old modules): `--against :index` fails to import. Before moving
  modules, take the baseline as a dangling commit of the index, `git commit-tree $(git write-tree) -p HEAD -m baseline`
  (with `GIT_AUTHOR_*`/`GIT_COMMITTER_*` set: the jail has no identity), and pass its hash as REV; the bin tools reject
  a bare tree id (2026-11-09).
- A baseline of the working tree with its untracked files (moved or new modules, which `git stash create` leaves out),
  without touching the index: with `GIT_INDEX_FILE` set to a scratch file, `git read-tree HEAD`,
  `git add -A -- src tests benchmarks bin examples pyproject.toml`, then
  `git commit-tree $(git write-tree) -p HEAD -m baseline` as above (2026-11-11).
- `bin/ab.py` runs every selected benchmark 2 × RUNS times: a broad `-k` with the latency and one-to-many rows took 9
  minutes per run at `BENCH_SCALE=0.5` (2026-11-11). After each run, stderr says how long the remaining ones take.
  Select the rows the change touches, lower the scale or `-n`, and run nothing else meanwhile (with tests running beside
  it, reference rows moved by 40% and more). Stopping it leaves its current pytest run alive in a session of its own:
  find it under `/proc` (the jail has no `ps`) and kill it. A cost of about 1% needs more runs: 0.6 µs per run on
  `run_overhead_one_item` showed with `-n 15` (p 0.007 and 0.044) and not with 9 (p 0.10 and 0.12; pinned, 2026-11-11).
- `bin/ab.py` runs the working tree's `benchmarks/benchmark.py` on both sides: once the benchmarks import a name the
  baseline lacks (a new public module), side A fails at collection (`ModuleNotFoundError`). Take as A a commit of the
  baseline plus what the benchmarks import (`git read-tree BASE`, `git add` that module, as above; 2026-11-11:
  `strom.metrics`).
- A module moves with `bin/rename.py OLD NEW` (two paths): it rewrites the imports and sorts them. Moved by hand, the
  edit hook sorts imports at once: an import of the old path counts as third-party and jumps above `import strom`
  (2026-11-11).
- On a hybrid CPU (P and E cores; `/proc/cpuinfo`: the E-cores have no sibling with their `core id`) benchmark timings
  depend on the core a thread lands on: a one-pool-task row took 13.9 ms unpinned and 6.4 ms on the P-cores, and one
  unpinned `bin/ab.py` comparison showed 1.49 (p 0.018) where the pinned one shows 1.00. Pin every comparison:
  `bin/ab.py --cpus 0-11` (2026-11-11, an i7-12700H: CPUs 0–11 are the P-cores). The jail has no `taskset`; in front of
  another command (a probe that measures):
  `python3 -c "import os,sys; os.sched_setaffinity(0, range(12)); os.execvp(sys.argv[1], sys.argv[1:])"`
