# Decision form

A decision file opens with one sentence that says what was chosen and why, because a reader of its first lines must get
the decision, and 36 of 65 first sentences had over 40 words (2026-11-15). The rules are in the note
`.claude/rules/decisions.md`, what `bin/check_docs.py` checks of them in its docstring, and the evidence in
`docs/research/docs-writing.md` (4.2 to 4.5, 5.4, 5.5).

Decided with it:

- A single alternative stands in the lead and has no bullet under **Rejected**, because about twenty decisions gave one
  reason twice, in the lead and in the bullet (2026-11-15).
- The list under **Rejected** has no size limit, because it is read on demand.
- A date stands only on a measurement, on an observation of a tool and on "until" under **Rejected**, because git has
  the date of a decision (2026-11-15: 190 dates in 74 files).

**Rejected**

- a limit on the length of every sentence (the long sentences that are hard to read are run-in lists and series of
  measurements, which the other checks find; the limits of the style guides are advice, and for expert readers no study
  supports one)
- the counts of `--style` in `make lint` (over 70 hits on the day they were added, and no count says that a text is hard
  to read)
- the reason of a rejected alternative as a clause too (the closing parenthesis is where a reader looks, and
  "alternative (why)" is a form a check can know)
- a file per decision throughout (`docs/decisions/agent-docs.md` rejects a file per fact: the decisions of one topic are
  read together)
- deleting a rejected alternative whose reason is lost (the user may know it; the mark makes the gap visible)
- a count of long paragraphs under `--style` (none had over 250 words on the day it was added, so it prompted nothing)
- any parenthesis or colon as the reason of a rejected alternative (a date in parentheses, a ratio or a time of day
  passed for one)
