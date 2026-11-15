# Hook command

One hook command, `.claude/hooks/dispatch.py`, is registered for every event of Claude Code and runs
`strom_tools.hooks.dispatcher`, so that hooks change without touching `.claude/settings.json`, which Claude can't write.
It runs at every tool call, so it imports only what its event needs.

Decided with it:

- The rules a Bash command touches are loaded by a hook: half the reads were `cat` or `sed`, which Claude Code doesn't
  count, and the user had asked "are the rules respected?" four times. Since Claude Code 2.1.293 it loads the rule
  itself after a `cat`, `head`, `tail`, `sed -n` or `grep` of one file, so the hook adds nothing after such a command
  (2026-11-15): in three reviews by a subagent 2, 7 and 8 notes had arrived twice.
- The dispatcher imports the modules of an event's handlers only for that event, and the docs check is a sub-package, so
  that the hook after a Bash call reads the rules files without git (Measured). The tests in `tests/tools/hooks/` check
  which modules each event loads.
- A note beside a block stays as it is: both are printed, and the hooks reference says the JSON is read with exit code 2
  too (`strom_tools.hooks.hook_results`; not yet observed: B28 in `docs/todo.md`).

**Measured** (2026-11-15), the hook command for a Bash event before and after the new record classes of
`strom_tools.sessions.transcripts`, medians of 25 interleaved runs against the commit of 2026-11-14

| State of the handlers | Before, ms | After, ms |
| -- | -- | -- |
| every handler module imports its tool at the top | 113 | 134 |
| `docs_fixes` imports the docs check only when it runs | 64 | 71 |

Defining the new dataclasses costs about a millisecond each: `docs_check` and `transcripts` took 6 ms each to import.
The 7 ms left are mostly `transcripts`, which `rules_loading` imports for `loaded_natively`.

**Measured** (2026-11-13), the hook command, medians of 25 interleaved runs against the state before each change

| Change | Event | Before, ms | After, ms |
| -- | -- | -- | -- |
| imports per event | PreToolUse Bash | 145 | 91 |
| imports per event | PostToolUse Read, a tool without handlers | 145 | 90 |
| imports per event | PostToolUse Bash | 146 | 142 |
| the docs check as a sub-package | PostToolUse Bash | 142 | 112 |

With the sub-package the other events did not change; importing `git_files` with `subprocess` and `tempfile` took 20–25
ms of the 142.

**Rejected**

- one JSON object with `"decision": "block"` for a block beside a note (the path with exit code 2 and stderr is the one
  the friction count knows from the transcripts, and the reference says the note is read beside it)
- the dispatcher's tables naming handlers by strings, to import only the modules of an event (the names lose their
  types; a table as a function that imports its modules keeps them)
- the rules hook after every Bash command that names a file (a note twice costs less than a note missed, but Claude
  Code's own load after a plain view is reliable since 2.1.293)
- telling a subagent's records from a session's by `isSidechain` when reading a transcript (a file is one conversation:
  no session's transcript of 54 held a marked record)
- a lazy import of the docs check inside `docs_fixes` (only the Stop imports the module, and the check runs there)
