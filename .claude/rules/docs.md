---
paths:
  - "CLAUDE.md"
  - "ARCHITECTURE.md"
  - "README.md"
  - "GLOSSARY.md"
  - "docs/**"
  - ".claude/rules/**"
  - ".claude/skills/**"
---

# Maintaining the agent docs

Where each kind of fact lives, once (point there, don't copy it):

| Fact | Place |
| -- | -- |
| What every agent session needs: working agreements, commands | `CLAUDE.md` |
| Overview, repository, packages, design notes, conventions (code, tests, naming) | `ARCHITECTURE.md` |
| The public API and its semantics (user guide) | docstring of `src/strom/__init__.py` |
| Notes on one area | `.claude/rules/<area>.md`, with `paths` for that area |
| Multi-step procedures | a skill in `.claude/skills/` |
| Decisions and rejected alternatives | `docs/decisions.md`, one section per topic |
| Open tasks | `docs/todo.md` |
| A plan in progress | `docs/plans/<topic>.md`, linked from its task; deleted once done |
| Research (comparisons with other libraries), dated | `docs/research/<topic>.md` |
| Terms | `GLOSSARY.md` |
| Usage of a script, mechanism of the code | its docstring |

- `CLAUDE.md` is loaded into every session: keep it under about 8 KB (measure bytes, not lines: table rows and
  paragraphs are long lines); delete what code, docstrings or tests show at a glance.
- A section of `docs/decisions.md` (`## Topic`) holds the decision in a few sentences: what was chosen and why, with a
  pointer to the design note or docstring that tells how it works (never the mechanism itself), then its measurements,
  dated; then under **Rejected** one bullet per alternative with why (no size limit: read on demand), not what something
  was called before (unless that name was rejected for a reason). Read its headings (`grep '^## ' docs/decisions.md`)
  and the sections a change touches, not the whole file.
- Research is a snapshot of its date and is not continued: no marks of what was implemented since or is still open
  (decisions taken from it go to `docs/decisions.md`, open steps to `docs/todo.md`); only its references follow renames
  (`bin/check_docs.py`, `bin/rename.py`).
- Lines have at most 120 characters: mdformat (pre-commit) wraps paragraphs, not table rows. Tables only for cells of a
  few words, each row within 120 characters; longer content as a list or sections. `bin/check_docs.py` enforces it (the
  tables of `docs/research/` exempt until restructured, `docs/todo.md`).
- Format a changed doc before checking it, `pre-commit run mdformat --files FILE` (the commit hook does it anyway, and
  may then break the limit): mdformat keeps a code span on one line, so split a span that is longer than a line; and a
  block inside one list item (a code fence) puts a blank line between all items of its list, so keep an item to one
  paragraph (2026-11-11).
- Move finished tasks out of `docs/todo.md`; cite code by name, not by line number.
- A revised plan replaces the old one in place (no `_V2` files; git keeps the history) and is self-contained: it never
  mentions earlier versions or what changed (skill `plan`).
- `make lint` runs `bin/check_docs.py`: a cited path or `strom.` name that no longer exists fails it, and so does one
  that is not tracked (a clone would lack it): `git add` a new file that a doc cites.
- No numbers that go stale: `ARCHITECTURE.md`, Conventions, Code.
