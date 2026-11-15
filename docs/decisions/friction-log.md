# Friction log

What cost a session round trips (hook blocks, tool errors, rejected calls, interrupts) is logged per session in
`.checks/friction.jsonl`, and the SessionStart hook suggests the skill `retro` once it passes thresholds. The lines of
the log are increments (2026-11-11; the docstring of `bin/sessions.py`): a retrospective reads them with
`bin/sessions.py friction --since-retro --details`.

**Rejected**

- cumulative counts per session in the friction log, with every session's counts recorded at a retrospective as the base
  (2026-11-08: a session that ended again after a retrospective was summed with all it had before; the times in the
  transcript give the increments without a second record)
- an interrupt counted as a rejection per call it cancels (one interrupt of three pending edits made three of the four
  rejections that suggest a retrospective)
- only the hook blocks and tool errors of a subagent counted, for fear that its cancelled calls count as rejections
  (2026-11-15: a subagent stopped with two pending calls has the rejections and the interrupt in its own transcript, so
  they count as one interrupt)
