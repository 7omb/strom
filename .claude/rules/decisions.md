---
paths:
  - "docs/decisions/**"
---

# Writing a decision

Why this form: `docs/decisions/decision-form.md`. `bin/check_docs.py` checks it; its docstring says what.

- A decision is a file `docs/decisions/<topic>.md` with the title `# Topic`, its name in kebab case.
- It opens with one sentence of at most 40 words that names its subject and says what was chosen and why. A single
  alternative stands in that sentence: "X, not Y, because Z". How the choice works is in a design note or a docstring,
  and the decision points there.
- Further decisions of the topic stand under "Decided with it", a sentence each with its reason. A decision that is
  looked up by name and has rejected alternatives gets a file.
- Measurements stand under **Measured**, dated: a line with the setup, then a table of short cells or a sentence per
  measurement. The conclusion is a sentence of the lead.
- Under **Rejected** each alternative is a bullet that reads without the one above it and says why it lost, not what
  something was called before. The reason ends the bullet in parentheses, or follows a parenthesis and a colon:
  "alternative (when): why". An alternative whose reason the lead gives has no bullet. "(reason not recorded)" marks a
  lost reason.
- `→` marks before and after, `->` a type or a mapping, `×` a factor. A fraction, two versions and a mapping of numbers
  go in words or into a code span, because the check takes them for a series of measurements.
- A date stands on a measurement, on an observation of a tool that may expire and on "until" under Rejected.
- Another decision is cited by its path; the names of design notes (Semantics, …) are those of `ARCHITECTURE.md`.
