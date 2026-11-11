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
  - "tools/**"
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
- Claude never changes the index (`CLAUDE.md`, Process; 2026-11-11: the user compares Claude's changes with what is
  staged, and a session that staged its work with `git add -A` took that away). A file is deleted with `rm`, not
  `git rm`; a baseline is a commit made beside the index (below), never a staged version. The tools keep to it too: no
  function of `strom_tools.workspace.git_files` changes the index (a test checks the git commands it runs).
- `bin/check_docs.py` accepts a cited file only when it is tracked. A new file that a doc cites therefore fails
  `make lint` until the user stages it: leave it failing (the message ends in "untracked"), say so, and give the user
  the `git add` with the report. The Stop hook does not block for such a citation: it tells the user, once per set of
  them (`strom_tools.hooks.docs_fixes`). The user never uses `git add -N` for it: with an intent-to-add entry
  `git stash create` fails ("Entry … not uptodate. Cannot merge") and the revision `:index` gets an empty file (probed
  2026-11-11).
- Writing `.claude/settings.json`, creating files in `.claude/hooks/` and adding `allowed-tools` to a skill are blocked
  for Claude (self-modification; editing an existing hook module or a skill's text is not, 2026-11-06, nor deleting a
  hook module, 2026-11-11): prepare the files in `.checks/claude/` (the scratchpad is emptied on restart) and ask the
  user to copy them. The hooks themselves are in `strom_tools.hooks`, which Claude can write.
- The hooks are live while their code changes: `.claude/hooks/dispatch.py` imports `strom_tools.hooks.dispatcher` on
  every tool call, so a module of its import chain that does not import (a syntax error, a name moved halfway) makes
  every hook fail (reported, never blocking) until it is fixed. Test a changed handler on a recorded event first:
  `echo '{"hook_event_name": "Stop", "stop_hook_active": true}' | python3 .claude/hooks/dispatch.py; echo $?`.
- A tool that starts make inherits the variables of a make it runs under, in the environment (`ARGS`, `FILES`, `RUN`,
  `MAKEFLAGS`): `make test ARGS="-k x"` and tox with arguments hand them to the Makefiles of the tool tests, whose
  fixture `repository` (`tests/conftest.py`) therefore removes them (2026-11-11: three hook tests failed under
  `make test ARGS=…` only). It removes the variables of pytest-xdist too: a pytest started by a tool inside a worker
  inherits `PYTEST_XDIST_WORKER`, and pytest-benchmark then passes without measuring or writing its JSON.
- A mutant of the tools: `bin/mutant.py --replace tools/strom_tools/<module>.py OLD NEW -- -q tests/tools/<test>`; the
  copy holds `tools/`, `bin/` and the hook command beside `src/`. Not `-x` together with `-n`: pytest-xdist then ends
  with exit code 2 at the first failure, which is "no verdict" (exit code 3) instead of `caught` (2026-11-11).
- Never `git stash` / `git stash pop` to test the baseline: what the user staged would come back unstaged (`pop` without
  `--index`; repaired 2026-11-10 with `git read-tree` of the dropped stash's index parent). A baseline is
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
- `bin/rename.py OLD NEW --write` with two paths moves the file in the working tree only (2026-11-11; before, `git mv`
  staged the move of a tracked one): the old path shows as deleted and the new one as untracked until the user stages
  both, and the script prints that `git add`. Until then a doc that cites the new path fails the docs check as
  untracked, and `--against :index` compares with the module at its old path.
- The revision `:index` is what the user staged: Claude compares with it, and never stages a version to compare with. A
  baseline of the index as a commit, without changing it: `git commit-tree $(git write-tree) -p HEAD -m baseline` (with
  `GIT_AUTHOR_*`/`GIT_COMMITTER_*` set: the jail has no identity); pass its hash as REV (the bin tools reject a bare
  tree id).
- A baseline of the working tree with its untracked files (moved or new modules, which `git stash create` leaves out),
  without touching the index: with `GIT_INDEX_FILE` set to a scratch file (only then: the `git add` below goes into that
  file, not into the user's index), `git read-tree HEAD`,
  `git add -A -- src tests benchmarks bin tools examples pyproject.toml`, then
  `git commit-tree $(git write-tree) -p HEAD -m baseline` as above (2026-11-11).
- `bin/ab.py` runs every selected benchmark 2 × RUNS times: a broad `-k` with the latency and one-to-many rows took 9
  minutes per run at `BENCH_SCALE=0.5` (2026-11-11). After each run, stderr says how long the remaining ones take.
  Select the rows the change touches, lower the scale or `-n`, and run nothing else meanwhile (with tests running beside
  it, reference rows moved by 40% and more). Stopping it leaves its current pytest run alive in a session of its own:
  find it under `/proc` (the jail has no `ps`) and kill it. A cost of about 1% needs more runs: 0.6 µs per run on
  `run_overhead_one_item` showed with `-n 15` (p 0.007 and 0.044) and not with 9 (p 0.10 and 0.12; pinned, 2026-11-11).
- `bin/ab.py` runs the working tree's `benchmarks/benchmark.py` on both sides: once the benchmarks import a name the
  baseline lacks (a new public module), side A fails at collection (`ModuleNotFoundError`). Take as A a commit of the
  baseline plus what the benchmarks import (`git read-tree BASE`, `git add` that module, in the scratch index as above;
  2026-11-11: `strom.metrics`).
- A module moves with `bin/rename.py OLD NEW` (two paths, see above): it rewrites the imports and sorts them. Moved by
  hand, the edit hook sorts imports at once: an import of the old path counts as third-party and jumps above
  `import strom` (2026-11-11).
- On a hybrid CPU (P and E cores; `/proc/cpuinfo`: the E-cores have no sibling with their `core id`) benchmark timings
  depend on the core a thread lands on: a one-pool-task row took 13.9 ms unpinned and 6.4 ms on the P-cores, and one
  unpinned `bin/ab.py` comparison showed 1.49 (p 0.018) where the pinned one shows 1.00. Pin every comparison:
  `bin/ab.py --cpus 0-11` (2026-11-11, an i7-12700H: CPUs 0–11 are the P-cores). The jail has no `taskset`; in front of
  another command (a probe that measures):
  `python3 -c "import os,sys; os.sched_setaffinity(0, range(12)); os.execvp(sys.argv[1], sys.argv[1:])"`
