"""The development tools of strom: what the scripts in `bin/` and the Claude Code hooks run.

Not part of the library: nothing here ships (the wheel holds `src/` only), and nothing here imports `strom` or
anything outside the standard library: the hooks run on an interpreter without the venv, and a tool has to work
while the library is broken. A script `bin/NAME.py` is a wrapper of `strom_tools.commands.NAME`, and
`.claude/hooks/dispatch.py` one of `strom_tools.hooks.dispatcher`; a command's usage is its module docstring
(`--help`).

Layers, bottom-up: a module imports only from the layers above its own, and the tools import nothing of each
other (`tests/tools/test_structure.py` checks both).

  foundations   `tool_error` (`ToolError`: what a tool could not do, as the message its command prints),
                `json_objects` (JSON read as `object`, narrowed without `Any`)
  `workspace`   the repository and what runs in it: `repository` (its root, the state directory, the source
                roots), `git_files` (every call of git), `make_targets` (the Makefile's targets: the one
                definition of the checks and the fixers), `process_groups` (a command with a timeout that
                kills its whole group)
  the tools     `change_checks` (what validates a change, skill `validate-change`: revisions, line diffs,
                benchmark comparisons, typing diagnostics, collected test IDs, mutants, the make checks),
                `example_scripts`, `docs_check`, `renames`, `sessions` (Claude Code's transcripts and the
                friction in them)
  entry points  `hooks` (the handlers of the Claude Code hooks and their dispatcher) and `commands` (one
                module per script). Only they read arguments or stdin, print and exit.

Below the entry points a function takes the repository as a value (`Repository`, so a test passes one in a
temporary directory), returns its outcome as data and raises `ToolError` for what it can't do.

A new tool: its module (or sub-package) among the tools, with a test module in `tests/tools/`; its command in
`commands` (`main(argv) -> int`, the docstring as usage); the wrapper in `bin/`, a copy of another one with its
name; its place in the tables of `tests/tools/test_structure.py`. A new hook: a handler
`(Repository, event) -> HookResult` in `hooks`, entered in the table of `hooks.dispatcher`."""
