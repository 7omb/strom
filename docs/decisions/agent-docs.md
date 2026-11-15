# Agent docs

Each kind of fact has one place, and an agent gets a fact when its work triggers it, because one file loaded in every
session was mostly unused and copies drifted. The places and the rules of each are in `.claude/rules/docs.md`. A note is
loaded by Claude Code for a file it reads or edits and by the rules hook for a path a Bash command names
(`strom_tools.hooks.rules_loading`); the docs check keeps the notes loadable (the docstring of `bin/check_docs.py`).

Measured before (sessions ac2eb2c5, 9c493011, 0837df3e):

- two notes of 23.5 KB that Claude Code replaced by a 2 KB preview, while the hook recorded their rules as loaded;
- the former note `tooling` with 22 entries on about ten topics, loaded whole for eleven path patterns;
- the one decisions file (87 KB), read 20 to 65 times per session in ranges;
- the index agreement in five files.

**Rejected**

- `AGENTS.md` (strom has a `CLAUDE.md`, and by Claude Code's docs, read 2026-11-15, it loads the other only where there
  is none, since its version 2.1.277)
- everything in `CLAUDE.md` (13.5 KB in every session, mostly unused by tooling and naming sessions)
- importing parts with `@` (imports load at start, saving no context)
- copies of script usage or skill steps in `CLAUDE.md` (they drifted)
- the open tasks as a plan in `docs/plans/`, with `docs/todo.md` pointing to it (2026-11-13 to 2026-11-15: two places,
  and the decisions that said "open in `docs/todo.md`" could not name the task)
- research notes that follow the work (`docs/research/backends.md` and `dependency_injection.md` marked their steps as
  implemented or open, 2026-11-09 to 2026-11-11: the open ones were in neither `docs/todo.md` nor a plan)
- notes per area (`tooling.md`, `tests.md`, `typing.md`: until 2026-11-11; an area spans many topics, and a note loads
  whole for any of its paths)
- links between notes and an index note, as in a Zettelkasten (Claude follows a link with a tool call; the file names
  and `paths` are the index, and an index note another place that drifts)
- an index file of `docs/decisions/` (the listing is the index, and an index file another place that drifts)
- a file per fact (the facts of one topic load together; more files for the same trigger)
- a `commands` key in a note's front matter, to trigger by command words such as `tox` (Claude Code ignores it, so the
  two loaders would disagree; a path in the command covers the scripts)
- cutting a note at the hook limit (half a rule reads as the whole rule); a budget that the dispatcher divides among
  handlers (machinery for one handler with notes)
- Claude Code's auto memory for project knowledge (outside the repository: not versioned, not checked, not shared)
- an overall size limit of the notes in the docs check (the hook enforces the output; the limit per note keeps a topic)
