# Agent docs

`CLAUDE.md` holds what every session needs (agreements, commands) and sends agents to `ARCHITECTURE.md` before code
work; open tasks in `docs/todo.md`, plans in progress in `docs/plans/`; procedures as skills; usage of a script only in
its docstring; research in `docs/research/` is a snapshot of its date and is not continued (2026-11-11): what was
decided from it is recorded in `docs/decisions/`, what is open in `docs/todo.md`.

Knowledge arrives by its trigger (2026-11-11). A gotcha goes, in this order, into enforcement (a deny rule, a check),
the message of the tool where it happens, the docstring of what it concerns, or a note: a rules file of one topic in
`.claude/rules/` whose `paths` name the files of that work, so that Claude Code (Read, Edit) and the rules hook (a path
a Bash command names, `strom_tools.hooks.rules_loading`) load it only there. The docs check keeps the notes loadable:
`paths` present, each glob matching a tracked file, the text under `strom_tools.docs_check.doc_problems.NOTE_LIMIT`; the
hook output stays under Claude Code's limit (`strom_tools.hooks.hook_results.CONTEXT_LIMIT`), and the rules hook names
the notes left out and adds them at a later command. Decisions are a file per topic in `docs/decisions/`; the listing is
the index, a file's first sentence the decision. Measured before (sessions ac2eb2c5, 9c493011, 0837df3e): two notes of
23.5 KB that Claude Code replaced by a 2 KB preview while the hook recorded their rules as loaded; the former note
`tooling` with 22 entries on about ten topics loaded whole for eleven path patterns; the one decisions file (87 KB) read
20 to 65 times per session in ranges; the index agreement in five files.

**Rejected**

- `AGENTS.md` (Claude Code does not load it)
- everything in `CLAUDE.md` (13.5 KB in every session, mostly unused by tooling and naming sessions)
- importing parts with `@` (imports load at start, saving no context)
- copies of script usage or skill steps in `CLAUDE.md` (they drifted)
- research notes that follow the work (`docs/research/backends.md` and `dependency_injection.md` marked their steps as
  implemented or open, 2026-11-09 to 2026-11-11: the open ones were in neither `docs/todo.md` nor a plan)
- notes per area (`tooling.md`, `tests.md`, `typing.md`: until 2026-11-11; an area spans many topics, and a note loads
  whole for any of its paths)
- links between notes and an index note, as in a Zettelkasten (Claude follows a link with a tool call; the file names
  and `paths` are the index, and an index note another place that drifts); an index file of `docs/decisions/` likewise
- a file per fact (the facts of one topic load together; more files for the same trigger)
- a `commands` key in a note's front matter, to trigger by command words such as `tox` (Claude Code ignores it, so the
  two loaders would disagree; a path in the command covers the scripts)
- cutting a note at the hook limit (half a rule reads as the whole rule); a budget that the dispatcher divides among
  handlers (machinery for one handler with notes)
- Claude Code's auto memory for project knowledge (outside the repository: not versioned, not checked, not shared)
- an overall size limit of the notes in the docs check (the hook enforces the output; the limit per note keeps a topic)
