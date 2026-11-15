# Tool package

The development tools are one package, `strom_tools`, in a separate source root (`tools/`), with the library's
conventions, checker settings and tests, because as scripts they were untested and could not run on a test repository.
The scripts in `bin/` and the hook command are wrappers that keep their paths. The layers, what only the entry points
may do and how a tool is added are in the package's docstring and in `ARCHITECTURE.md` (Tools);
`tests/tools/test_structure.py` checks them.

Decided with it:

- The tests run what the tools start for real, on projects a test writes: the three checkers, pytest-benchmark and uv
  with example scripts that have no dependencies. uv gets a cache of the test, so that a test needs no network and
  leaves nothing in the user's cache. Only `make examples` and `make type` run examples with dependencies.
- What a tool reads leniently is parsed once, at the boundary, into values, and an outcome is a sum type with one
  renderer, because the readers had each narrowed the raw dicts again and the commands had compared outcome strings.
- What decides is apart from what runs and what prints, so that a decision is tested without a repository. A command
  reads its arguments, calls its tool and prints what it returns; a hook handler is a shell around a pure decision.
- Every process the tools start runs through `strom_tools.workspace.processes`, with one outcome type, so that a failed
  git command is a `ToolError` with git's message instead of a traceback.
- A module of the tools holds one concept, as in the library. The tools' terms are in `GLOSSARY.md`, Tools. A command's
  docstring holds its usage and what its output says, its tool's docstring the mechanism.
- The exit code of a command that did not run is in `docs/decisions/tool-exit-codes.md`, what the hook command costs in
  `docs/decisions/hook-command.md`.

**Probed and measured** (2026-11-11)

- setuptools ships every package of `src/` in the wheel. With `pythonpath = ["src"]` the tox envs of a Python version
  import the working tree's `strom` instead of the installed one; with `["tools"]` only the tools come from the working
  tree.
- mypy's `disallow_any_expr` found 91 expressions in the scripts (attributes of `argparse.Namespace`, `json.loads`,
  groups of `re.Match`): they end at the commands, which assign each argument to an annotated variable, and in
  `strom_tools.json_objects`.
- The outputs of the scripts and of the hook command on recorded events were the same before and after, apart from
  `--help`, which now shows each command's docstring. Those of `bin/sessions.py`, `bin/check_docs.py` and
  `bin/rename.py` on this repository were the same before and after the parsing at the boundary.
- The hook command for a Bash event took 60 ms before and 62 ms after (medians of 25 interleaved runs): `traceback` is
  imported only when a handler fails, and `typing`, which `json_objects` imports for `TypeIs`, costs about 3 ms.
- The suite had 494 tests in 11.6 s before (one run) and 725 in 9 to 13 s after (three runs of the parallel suite).
- `loaded_natively` scans the raw lines: on the largest transcript (30 MB) parsing takes 192 ms and the scan 40 ms
  (minimum of 5), where the whole hook command takes about 60 ms.

**Rejected**

- the package beside `strom` in `src/` (a `packages.find` exclusion to keep it out of the wheel; its tests either skip
  in the tox envs of a Python version or make them test the working tree's library; `src/` no longer "the library" for
  `library_copy`, the docs check and the docs)
- `bin/` as the package, with `pythonpath = ["bin"]` (a script stays module and command in one; top-level modules named
  `check`, `sessions` and `rename` on the import path of the test run; the hooks keep importing through `sys.path`)
- a module per tool with its `main` in it (a hook that needs a tool's core imports its command line; "only `main`
  prints" is a convention no import rule can check)
- one command `python -m strom_tools NAME` instead of the scripts (every citation, skill and the permission rule for
  `bin/` in `.claude/settings.json` change; possible later, a command is a function `main(argv)`)
- a uv workspace member or an installed dev dependency for the tools (a changed dev group makes every example's lock
  stale)
- the repository root on the import path with a top-level package (`tests`, `bin` and `benchmarks` importable too)
- tool tests beside the tools (a second test tree with its own configuration and Hypothesis profiles)
- a `conftest.py` in `tests/tools/` (mypy: "Duplicate module named conftest" without packages; the fixture is in
  `tests/conftest.py`)
- git and make injected into the tools as objects (one real implementation each: a test makes a repository in a
  temporary directory, with a Makefile whose targets record their calls)
- the library's pyright rules at the top level instead of once more for `tools/` (108 diagnostics in `tests/` and
  `benchmarks/`, 71 of them `reportUnknownLambdaType`: a change to the tests' standards)
- `functools.cache` for what the docs check reads once (its decorator is an expression with `Any`; and a cache of the
  process outlives the repository of a test: the memo is a field of `Known`)
- mypy strict without `disallow_any_expr` for the tools (`Any` from `json.loads` flowed through the transcript readers
  unnoticed)
- examples with dependencies in the tests (the network, and minutes for their environments)
- `loaded_natively` over the parsed records (on every Bash call: 192 ms on the largest transcript against a 40 ms scan)
- the hooks' memos as JSON, or beside `state_dir` in `workspace` (what they hold is lines; only the hooks use them)
- the result of a process as bytes, for `git archive` (every other caller wanted text: the archive goes into a file)
