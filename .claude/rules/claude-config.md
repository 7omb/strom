---
paths:
  - ".claude/**"
  - "tools/strom_tools/hooks/**"
---

# Claude Code's configuration

- Blocked for Claude (self-modification): writing `.claude/settings.json`, creating files in `.claude/hooks/`, adding
  `allowed-tools` to a skill. Not blocked: editing or deleting a hook module, editing a skill's text (2026-11-06,
  2026-11-11), creating a rules file in `.claude/rules/`, creating a subagent in `.claude/agents/` (2026-11-11). Prepare
  a blocked file in `.checks/claude/` (the scratchpad is emptied on restart) and give the user the `cp`. The hooks
  themselves are in `strom_tools.hooks`.
- The hooks are live while their code changes: `.claude/hooks/dispatch.py` imports `strom_tools.hooks.dispatcher` on
  every tool call, so a module of its import chain that does not import makes every hook fail (reported, never blocking)
  until it is fixed. Test a changed handler on a recorded event first:
  `echo '{"hook_event_name": "Stop", "stop_hook_active": true}' | python3 .claude/hooks/dispatch.py; echo $?`.
- Subagents (2026-11-14): a definition written to `.claude/agents/` reaches a running session, but not at once
  (2026-11-15: a session that had started before the file existed got "Agent type 'researcher' not found" and the type
  some turns later, when Claude Code listed it as new). Until then a general-purpose agent that is told to read the
  definition first stands in. Claude Code starts a subagent only where the user, `CLAUDE.md` or a skill names it. Its
  tool calls run the same hooks (`strom_tools.hooks.rules_loading`).
