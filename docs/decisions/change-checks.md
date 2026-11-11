# Change checks

Scripts in `bin/` for the mechanical parts of the Process (A/B benchmarks, typing and test-ID snapshots, injected bugs
in a temporary copy, run detached with a timeout), the steps as the project skill `validate-change`; typing and test-ID
diffs against a revision (`--against REV`, checked in a temporary copy) besides saved snapshots; the edit hook
(`strom_tools.hooks.python_fixes`) leaves the rules a half-done edit breaks (F401, F811, F821, F822, F841; 2026-11-06:
F821 alone blocked 186 times in four sessions) to the end of the turn, when it checks every changed Python file (also
those changed by commands) with all rules, and leaves a file outside the repository as it is (2026-11-11); `:index` as a
revision (the state the user staged, see `git-index.md`) beside commits; a mutant's test runs write no bytecode
(2026-11-11: a bug as long as the text it replaces, injected within the second of the file's modification time, ran from
the bytecode of the run without it and counted as `missed`; the first test of `bin/mutant.py` found it)

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
