# strom – Project Notes

Typed, declarative stream processing on asyncio with shared pools. No runtime dependencies; Python 3.14, also the
free-threaded 3.14t.

**Read `ARCHITECTURE.md` before changing, reviewing or proposing code**: the overview, packages, design notes and the
conventions for code, tests and naming; they apply to every change. The user guide is the package docstring
(`src/strom/__init__.py`).

Notes per area are in `.claude/rules/` (Claude Code loads each when it reads or edits a matching file; other agents:
read them when working there): `typing.md` (checker limitations), `tests.md` (testing notes, benchmarks), `tooling.md`
(build and tool gotchas), `docs.md` (maintaining this file and the docs).

## Working agreements

**Process**

- Additions to the public API need the user's go-ahead.
- Every change: reproduce the problem before (test or measurement), validate after. Which checks a kind of change needs
  and how to run them: skill `validate-change` (`.claude/skills/validate-change/SKILL.md`).
- Edit files with Edit/Write, not with scripts in Bash: only those edits show the user a diff and run the PostToolUse
  hook. Scripts only for generated or mechanical changes across many files (renames: `bin/rename.py`). Read files with
  Read rather than `cat`/`sed -n`: Claude Code loads `.claude/rules` only then (a hook catches Bash reads too).
- IDE diagnostics that arrive after edits lag behind multi-file changes; only `make type` counts.
- Long runs only when the user asks: `make bench`, the suite run serially. Otherwise `make test` (parallel), benchmarks
  with `bin/ab.py -- -k …` and `BENCH_SCALE`, in the background.
- Reviews: skill `review`; plans: skill `plan` (a revised plan is self-contained, never mentions earlier versions).

**Improving this setup**

- A gotcha a later session would hit too (tool quirk, checker limitation, jail gap): add it to the matching
  `.claude/rules` file in the same change, dated. A user correction of how you work: propose the line for `CLAUDE.md`, a
  rule or a skill, and add it when the user agrees.
- Work done twice by hand (a throwaway script, the same command sequence): propose a script in `bin/`.
- Prefer enforcing (hook, check in `make lint`) over another instruction. Hooks: `.claude/hooks/dispatch.py` routes
  every event, so change the handler modules, not `.claude/settings.json` (Claude can't write it).
- Friction (hook blocks, errors, rejections, interrupts) is logged per session in `.checks/friction.jsonl`; the
  SessionStart hook suggests the skill `retro` when it piles up.

## Commands

Environment: `nix develop` (or direnv) provides Python 3.14 and 3.14t, uv, ruff, pyright, ty and nixpkgs-fmt; `.envrc`
installs the git hooks, runs `uv sync` (the `dev` and `bench` groups) and activates `.venv`. Tool options and paths are
in `pyproject.toml`. The checks are defined once, as make targets: tox and the git hooks run those.

```
make check                     # lint, type, test, examples
make test | cov | test-watch   # pytest -n auto tests/ (cov: branch coverage of strom); more options: ARGS="-k …"
uv run pytest -n auto tests/ …  # options e.g. --hypothesis-profile=ci, -k "static or no_any", --durations=15
make lint | type               # ruff check, format --check, bin/check_docs.py | mypy, pyright, ty, the examples' types
make examples                  # bin/run_examples.py [NAME ...]: every example (a uv script), or the named ones
make bench | bench-results     # benchmarks/benchmark.py (no xdist) | each once, results only; .claude/rules/tests.md
make build                     # sdist and wheel in dist/
tox [-e 3.14t]                 # the make targets; test on 3.14 and 3.14t, bench-results with BENCH_SCALE 0.2
pre-commit run --all-files     # the commit hook: standard hooks, mdformat, ruff fixes, nixpkgs-fmt, make lint | type
git push                       # the pre-push hook: make check
```

`bin/`: `ab.py` (interleaved A/B benchmarks of two revisions), `typing_snapshot.py` (diagnostics of mypy, pyright, ty),
`collect_ids.py` (collected test IDs), `mutant.py` (tests against an injected bug), `run_examples.py`, `check.py`
(`make check` in one line per target), `check_docs.py` (paths and names the docs cite are tracked; in `make lint`),
`rename.py` (an identifier in code, its mentions in docs), `sessions.py` (past Claude Code sessions: list, prompts,
search, friction). Usage and contract: each one's docstring (`--help`); they run with the venv's Python
(`uv run --frozen python`, or the activated venv), keep snapshots in `.checks/` and share `bin/_tools.py`; a revision
`:index` is the staged state. Claude Code hooks: the handlers `.claude/hooks/dispatch.py` lists (ruff on edited and
changed Python files, rules for Bash reads, the friction log).

## Docs

Before proposing or reviewing a design, an alternative or a refactoring, read the sections of `docs/decisions.md` it
touches (a section per topic: `grep '^## ' docs/decisions.md`); record each new decision there. Open tasks:
`docs/todo.md`. Where each kind of fact lives: `.claude/rules/docs.md`.
