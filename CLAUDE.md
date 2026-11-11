# strom – Project Notes

Typed, declarative stream processing on asyncio with shared pools. No runtime dependencies; Python 3.14, also the
free-threaded 3.14t.

**Read `ARCHITECTURE.md` before changing, reviewing or proposing code**: the overview, packages, design notes and the
conventions for code, tests and naming; they apply to every change. The user guide is the package docstring
(`src/strom/__init__.py`).

Notes of one topic each are in `.claude/rules/` (Claude Code loads one when it reads or edits a file its `paths` match,
a hook when a Bash command names one; other agents: read those of the files they work on); maintaining them and the
docs: `docs.md` there.

## Working agreements

**Process**

- Additions to the public API need the user's go-ahead.
- If the repository is not in the state the user describes (a commit, a branch, a tag), say so first and wait, also with
  the parts of the request that seem independent of it.
- Every change: reproduce the problem before (test or measurement), validate after. Which checks a kind of change needs
  and how to run them: skill `validate-change` (`.claude/skills/validate-change/SKILL.md`).
- Edit files with Edit/Write, not with scripts in Bash: only those edits show the user a diff and run the PostToolUse
  hook. Scripts only for generated or mechanical changes across many files (renames and moved modules: `bin/rename.py`).
  Read files with Read rather than `cat`/`sed -n`: Claude Code loads `.claude/rules` only then (a hook catches Bash
  reads too).
- The index is the user's: never stage or unstage (`git add`, `git rm`, `git mv`, `git reset`, `git restore --staged`).
  The user keeps a state staged and compares Claude's changes with it (`git diff`). What needs staging (a new file that
  a doc cites, `.claude/rules/docs-format.md`) is a command for the user at the end of the report.
- IDE diagnostics that arrive after edits lag behind multi-file changes; only `make type` counts.
- Long runs only when the user asks: `make bench`, the suite run serially. Otherwise `make test` (parallel), benchmarks
  with `bin/ab.py -- -k …` and `BENCH_SCALE`, in the background. A background command notifies when it ends: wait for
  that, never beside it with a `sleep` loop; to wait for anything else, the Monitor tool.
- Reviews: skill `review`; plans: skill `plan` (a revised plan is self-contained, never mentions earlier versions).
- A report ends with what is left: the open findings or tasks by ID, and the commands the user has to run (staging,
  commit, push, copying a prepared file).

**Improving this setup**

- A gotcha a later session would hit too (tool quirk, checker limitation, jail gap): in the same change, make a tool say
  it or enforce it where it can; else add it, dated, to the note of its topic in `.claude/rules` (`docs.md` there). A
  user correction of how you work: propose the line for `CLAUDE.md`, a rule or a skill, and add it when the user agrees.
- Work done twice by hand (a throwaway script, the same command sequence): propose a script in `bin/`.
- Prefer enforcing (hook, check in `make lint`) over another instruction. Hooks: `.claude/hooks/dispatch.py` runs
  `strom_tools.hooks.dispatcher` for every event, so change its table and the handler modules, not
  `.claude/settings.json` (Claude can't write it).
- Friction (hook blocks, errors, rejections, interrupts) is logged per session in `.checks/friction.jsonl`; the
  SessionStart hook suggests the skill `retro` when it piles up.

## Commands

Environment: `nix develop` (or direnv) provides Python 3.14 and 3.14t, uv, ruff, pyright, ty and nixpkgs-fmt; `.envrc`
installs the git hooks, runs `uv sync` (the `dev` and `bench` groups) and activates `.venv`. Tool options and paths are
in `pyproject.toml`. The checks and the fixers are defined once, as make targets: tox, the git hooks and the Claude Code
hooks run those.

```
make check                     # lint, type, test, examples
make test | cov | test-watch   # pytest -n auto tests/ (cov: branch coverage of strom); more options: ARGS="-k …"
uv run pytest -n auto tests/ …  # options e.g. --hypothesis-profile=ci, -k "static or no_any", --durations=15
make lint | type               # ruff check, format --check, bin/check_docs.py | mypy, pyright, ty, the examples' types
make fix [FILES="…"]           # the fixers: ruff's fixes and format, mdformat; on every file, or on the given ones
make examples                  # bin/run_examples.py [NAME ...]: every example (a uv script), or the named ones
make bench | bench-results     # benchmarks/benchmark.py (no xdist) | each once, results only (rules/benchmarks.md)
make build                     # sdist and wheel in dist/
tox [-e 3.14t] [-- ARGS]       # the make targets; test on 3.14 and 3.14t (ARGS: pytest's), bench-results at scale 0.2
pre-commit run --all-files     # the commit hook: standard hooks, mdformat, make fix, nixpkgs-fmt, make lint | type
git push                       # the pre-push hook: make check
```

`bin/`: `ab.py` (interleaved A/B benchmarks of two revisions), `typing_snapshot.py` (diagnostics of mypy, pyright, ty),
`collect_ids.py` (collected test IDs), `mutant.py` (tests against an injected bug), `run_examples.py`, `check.py`
(`make check` in one line per target), `check_docs.py` (paths and names the docs cite are tracked; in `make lint`),
`rename.py` (an identifier in code or a file that moves, with what the docs say of it), `sessions.py` (past Claude Code
sessions: list, prompts, search, friction). Usage and contract: `--help`; they run with the venv's Python
(`uv run --frozen python`, or the activated venv) and keep snapshots in `.checks/`; a revision `:index` is the staged
state; exit code 4 means the script did not run (wrong arguments, an error), never an outcome. Each is a wrapper of its
command in `strom_tools` (`tools/`), the package of the development tools, with the library's conventions and checkers
and its tests in `tests/tools/`: its guide is the package's docstring (`ARCHITECTURE.md`, Tools). Claude Code hooks: the
handlers `strom_tools.hooks.dispatcher` lists (`make fix` and the lint of edited and changed Python files and of changed
docs, rules for Bash reads, the friction log, a note when the context was summarised).

## Docs

Before proposing or reviewing a design, an alternative or a refactoring, read the decisions it touches: a file per topic
in `docs/decisions/` (`ls`; a file's first sentence is the decision); record each new decision there. Open tasks:
`docs/todo.md`. Where each kind of fact lives: `.claude/rules/docs.md`.
