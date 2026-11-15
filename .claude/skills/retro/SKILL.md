---
name: retro
description: Retrospective of past Claude Code sessions on strom - find friction (hook blocks, tool errors, rejected calls, interrupts, user corrections, repeated commands) and propose fixes to CLAUDE.md, .claude/ (rules, skills, hooks) and bin/. Use when asked for a retrospective or to make Claude work more efficiently here, or when the SessionStart hook suggests it.
---

# Retrospective

## Steps

1. **Collect** with the commands of `uv run --frozen python bin/sessions.py`:
   - `friction --since-retro --details --commands` shows the sessions that went on after the last retrospective: their
     counts since then, each piece of friction with its call and answer, and the frequent commands.
   - `list` shows the sessions. A transcript of many MB outgrew its context: `tools SESSION` shows which tools' results
     filled it, `tokens SESSION` what it and its subagents were charged.
   - `prompts SESSION` shows what the user asked and corrected.
   - `search TERM --all` finds patterns (e.g. `stale`, `again`, `instead`, `hang`, `timed out`).
2. **Look for**:
   - corrections the user had to repeat (a preference to record),
   - questions the user asked more than once (the answer belongs in the docs or a check),
   - work redone by hand that a script would do (frequent commands, throwaway scripts in the scratchpad),
   - hook blocks and tool errors with a common cause, long runs that hit a timeout,
   - docs that went stale (a check in `bin/check_docs.py` could catch the kind).
3. **Compare** with what exists: `CLAUDE.md`, `.claude/rules/`, the skills, the hooks (`strom_tools.hooks.dispatcher`
   lists them), `bin/`, and the decisions `docs/decisions/agent-docs.md`, `docs/decisions/change-checks.md`,
   `docs/decisions/self-improvement.md`, `docs/decisions/friction-log.md`, `docs/decisions/hook-command.md` and
   `docs/decisions/renames.md` (rejected proposals stay rejected without a new reason). For each note in
   `.claude/rules/`: whether a check or a tool's message says it by now (then it goes), and whether its `paths` still
   fit the work it is about. For the docs, whether they grew since the last retrospective, with DATE its date:
   `git diff --shortstat $(git rev-list -1 --before=DATE HEAD) -- CLAUDE.md .claude docs/decisions`, and what
   `bin/check_docs.py --style` lists. More lines added than removed is a finding: look for the fact that now stands
   twice (`.claude/rules/docs.md`).
4. **Report** a numbered list (skill `review`, Output): per finding the evidence (sessions, counts), the cause and the
   fix, where it goes by `.claude/rules/docs.md`. Prefer enforcing (a hook, a check in `make lint`, a script) over
   another instruction; keep `CLAUDE.md` under its size limit.
5. **Apply** what the user picks. Claude can't write `.claude/settings.json`: change the hook modules instead, or
   prepare the file and ask the user to copy it. Record each decision in the file of its topic in `docs/decisions/`.
6. **Mark** the retrospective, so the SessionStart hook counts from here:
   `uv run --frozen python bin/sessions.py mark-retro`.
