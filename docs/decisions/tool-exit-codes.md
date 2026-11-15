# Tool exit codes

A command of the tools that could not run exits with 4, `DID_NOT_RUN` in `strom_tools.commands.command_line`, because
its failure must never read as an outcome. The code covers wrong arguments, a `ToolError` and an exception, which is
still printed with its traceback. Before, these were 2, 1 and 1: for `bin/mutant.py` the verdicts `hung` and `missed`,
and for the scripts that compare lines "they differ".

**Rejected**

- exit code 2 for "did not run", as diff and grep have it, with the verdicts of `bin/mutant.py` renumbered (its codes
  are cited by the skill `validate-change` and learned; 4 is free in every command, and pytest uses it for a usage error
  too)
- keeping the traceback's exit code 1 for an exception in a command (a crash of `bin/mutant.py` read as `missed`)
