# Tool package

The development tools are one package, `strom_tools`, in a source root of its own (`tools/`), with the library's
conventions and checker settings and a test module per module (`tests/tools/`); the scripts in `bin/` and the hook
command `.claude/hooks/dispatch.py` are wrappers of a few lines that keep their paths (2026-11-11). The layers, what
only the entry points may do and how a tool is added: the package's docstring and `ARCHITECTURE.md`, Tools;
`tests/tools/test_structure.py` checks the imports (standard library only, one way between the layers), that only the
entry points read arguments, print and exit, and that every wrapper is the template. Before, the scripts were untested,
imported a helper module and each other through `sys.path`, and each computed the repository's root itself, so that no
function could run on a test repository.

Probed and measured (2026-11-11): setuptools ships every package of `src/` in the wheel; with `pythonpath = ["src"]` the
tox envs of a Python version import the working tree's `strom` instead of the installed one, with `["tools"]` only the
tools come from the working tree. mypy's `disallow_any_expr` found 91 expressions in the scripts (attributes of
`argparse.Namespace`, `json.loads`, groups of `re.Match`): they end at the commands, which assign each argument to an
annotated variable, and in `strom_tools.json_objects`. The outputs of the scripts and of the hook command on recorded
events were the same before and after, apart from `--help`, which now shows each command's docstring. The hook command
for a Bash event: 60 ms before, 62 ms after (medians of 25 interleaved runs; `traceback` is imported only when a handler
fails, and `typing`, which `json_objects` imports for `TypeIs`, costs about 3 ms). The suite: 494 tests in 11.6 s before
(one run), 725 in 9 to 13 s after (three runs of the parallel suite). The first test of the mutants found a wrong
verdict (`change-checks.md`).

What the tools start is run by their tests for real, on projects a test writes: the three checkers, pytest-benchmark
(one run per side of a comparison whose metric is a constant of each revision's library; skipped in the tox envs of a
Python version, which lack the plugin) and uv with example scripts that have no dependencies, in a cache of the test (no
network, nothing left in the user's cache). Only `make examples` and `make type` run examples with dependencies.

A command that could not run exits with 4, `DID_NOT_RUN` in `strom_tools.commands.command_line` (2026-11-11): wrong
arguments, a `ToolError` or an exception, which is still printed with its traceback. Before, these were 2, 1 and 1: for
`bin/mutant.py` the verdicts `hung` and `missed`, and for the scripts that compare lines "they differ".

The import order of the library's packages is checked like that of the tools (`tests/test_packages.py`, 2026-11-11): the
layers of `ARCHITECTURE.md`, the groups of `_runtime`, no metrics in the runtime, no runtime in the reference semantics;
a break injected for each was caught by its test.

A note beside a block stays as it is (2026-11-11): both are printed, and the hooks reference says the JSON is read with
exit code 2 too (`strom_tools.hooks.hook_results`; not yet observed, `docs/todo.md`).

What a tool reads leniently is parsed once, at the boundary, into values (2026-11-11, review of the tools, A): a
transcript's lines into the record classes of `strom_tools.sessions.transcripts`, the friction log's lines into
`SessionLogged` and `RetroLogged`; outcomes are sum types with one renderer (`strom_tools.example_scripts.Outcome`,
`strom_tools.docs_check.doc_problems.Problem`), closed sets enums (`Kind`, `HitKind`, `Checker`), and what a hook
remembers between calls a `Memo` (`strom_tools.hooks.memos`: lines in a file of the state directory). Before, the
readers each narrowed the raw dicts again, and the commands compared outcome strings. `loaded_natively` scans the raw
lines: on the largest transcript (30 MB) parsing takes 192 ms and the scan 40 ms (minimum of 5), where the whole hook
command takes about 60 ms. The outputs of `bin/sessions.py`, `bin/check_docs.py` and `bin/rename.py` on this repository
were the same before and after.

What decides is apart from what runs and what prints (2026-11-11, review of the tools, B). A command reads its
arguments, calls its tool and prints what it returns: the interleaved comparison yields its runs and then the rows
(`strom_tools.change_checks.benchmark_comparison.comparison`), a rename is a plan (`strom_tools.renames.rename_of`,
`hits`, `write`), `friction.covered` picks the transcripts of a report, and the snapshot arguments are parsed into a
request. A hook handler is a shell around a pure decision (`docs_fixes._verdict`, `rules_loading._to_add`,
`friction_notes._suggestion`), tested without a repository. Every process the tools start runs through
`strom_tools.workspace.processes` (`tests/tools/test_structure.py` checks it), with one outcome type; a failed git
command is a `ToolError` with git's message instead of a traceback. `docs_check` reads a doc as lines with their context
and classifies a reference before it looks it up.

The hook command for a Bash event, medians of 25 interleaved runs against HEAD: 113 and 134 ms with every handler module
importing its tool at the top (defining the new dataclasses costs about a millisecond each: `docs_check` and
`transcripts` took 6 ms each to import), then 64 and 71 ms with `docs_fixes` importing the docs check only when it runs;
the 7 ms left are mostly `transcripts`, which `rules_loading` imports for `loaded_natively` (`docs/todo.md`).

The dispatcher imports the modules of an event's handlers only for that event (2026-11-13): each table is a function
that imports them (`strom_tools.hooks.dispatcher`; `tests/tools/hooks/test_dispatcher.py` checks in a fresh interpreter
which modules each one loads). The hook command, medians of 25 interleaved runs against the state before: PreToolUse
Bash 145 → 91 ms, PostToolUse of a tool without handlers (Read) 145 → 90 ms, PostToolUse Bash 146 → 142 ms.

The docs check is a sub-package, so that the hook after every Bash call reads the rules files without git (2026-11-13):
`doc_lines` (a doc's lines and their parts), `rule_notes` (the rules files), `doc_problems` (the check, with
`git_files`). `rules_loading` imports only `rule_notes` (`tests/tools/hooks/test_rules_loading.py` checks that it loads
no `git_files`). PostToolUse Bash 142 → 112 ms (medians of 25 interleaved runs against the state before), the other
events unchanged; importing `git_files` with `subprocess` and `tempfile` took 20–25 ms of it.

A module of the tools holds one concept, as in the library (2026-11-11, review of the tools, C): the snapshot store
apart from the line diffs (`strom_tools.change_checks.snapshots`, the commands' part in
`strom_tools.commands.snapshot_commands`), what a hook answers apart from what it gets (`hook_results`, `hook_events`),
and running make named for what it holds (`strom_tools.workspace.make_runs`). The tools' terms are in `GLOSSARY.md`,
Tools; a command's docstring holds its usage and what its output says, the mechanism its tool's.

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
- exit code 2 for "did not run", as diff and grep have it, with the verdicts of `bin/mutant.py` renumbered (its codes
  are cited by the skill `validate-change` and learned; 4 is free in every command, and pytest uses it for a usage error
  too)
- keeping the traceback's exit code 1 for an exception in a command (a crash of `bin/mutant.py` read as `missed`)
- one JSON object with `"decision": "block"` for a block beside a note (the path with exit code 2 and stderr is the one
  the friction count knows from the transcripts, and the reference says the note is read beside it)
- examples with dependencies in the tests (the network, and minutes for their environments)
- `loaded_natively` over the parsed records (on every Bash call: 192 ms on the largest transcript against a 40 ms scan)
- the hooks' memos as JSON, or beside `state_dir` in `workspace` (what they hold is lines; only the hooks use them)
- the result of a process as bytes, for `git archive` (every other caller wanted text: the archive goes into a file)
- the dispatcher's tables naming handlers by strings, to import only the modules of an event (the names lose their
  types; a table as a function that imports its modules keeps them)
- a lazy import of the docs check inside `docs_fixes` (only the Stop imports the module, and the check runs there)
