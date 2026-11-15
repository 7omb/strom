# Change checks

The mechanical parts of validating a change are scripts in `bin/`, and its steps are the project skill
`validate-change`. The scripts cover A/B benchmarks, typing and test-ID snapshots, and injected bugs in a temporary
copy, run detached with a timeout.

Decided with it:

- Typing and test-ID diffs run against a revision (`--against REV`, checked in a temporary copy) besides saved
  snapshots, so that nothing has to be saved before the first edit.
- `:index`, the state the user staged, is a revision beside commits (`docs/decisions/git-index.md`).
- The edit hook (`strom_tools.hooks.python_fixes`) leaves the rules a half-done edit breaks (F401, F811, F821, F822,
  F841) to the end of the turn, when it checks every changed Python file with all rules, also those that commands
  changed. F821 alone had blocked 186 times in four sessions (2026-11-06). The hook leaves a file outside the repository
  as it is.
- A mutant's test runs write no bytecode. A bug as long as the text it replaces, injected within the second of the
  file's modification time, ran from the bytecode of the run without it and counted as `missed`; the first test of
  `bin/mutant.py` found it.
- `bin/ab.py --cpus` pins a comparison, and each of its runs says how long the rest takes.

**Rejected**

- the library's rules for every Python file a session edits (probe scripts in the scratchpad, which the skill `plan`
  asks for, were reformatted and blocked: S101, E501)
- a baseline that must be saved before the first edit as the only way (the step most easily forgotten)
- a mutation-testing tool such as mutmut (generated mutants instead of the bug a test targets)
- pyperf for A/B (a second benchmark harness next to pytest-benchmark)
- make targets (arguments are awkward to pass)
- injecting into `src/` itself (a hang or an interrupted run leaves the bug in the working tree; the Hypothesis database
  and caches would record mutant runs)
- fixing F401 in the hook (it deletes an import added before its use)
- `bin/ab.py` pinned to the fast cores by default (the jail has no `/sys`, and `/proc/cpuinfo` tells the cores apart
  only where the fast ones have two threads each)
