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
| A gotcha of one topic, for the files of that work | a note `.claude/rules/<topic>.md` |
| Multi-step procedures | a skill in `.claude/skills/` |
| Decisions and rejected alternatives | `docs/decisions/<topic>.md` |
| Open tasks | `docs/todo.md` |
| A plan in progress | `docs/plans/<topic>.md`, linked from its task; deleted once done |
| Research (comparisons with other libraries), dated | `docs/research/<topic>.md` |
| Terms | `GLOSSARY.md` |
| Usage of a script, mechanism of the code | its docstring |

- `CLAUDE.md` is loaded into every session: at most `strom_tools.docs_check.doc_problems.SESSION_DOC_LIMIT` bytes;
  delete what code, docstrings or tests show at a glance.
- A note in `.claude/rules/` holds one topic, and its `paths` name the files of that work (a script a command names
  counts: `strom_tools.hooks.rules_loading`), so it loads only there; its body stays under the limit of the docs check.
  A gotcha goes where it is said when it happens: enforced (a deny rule, a check), else the tool's message, else the
  docstring of what it concerns, else a note, dated. Once a check or a message says it, the note goes.
- A decision (`docs/decisions/<topic>.md`, `# Topic`, the name in kebab case) starts with what was chosen and why, in a
  few sentences, with a pointer to the design note or docstring that tells how it works (never the mechanism), then its
  measurements, dated; then under **Rejected** one bullet per alternative with why (no size limit: read on demand), not
  what something was called before. Another decision is cited by its path; design-note names (Semantics, …) are those of
  `ARCHITECTURE.md`.
- Research is a snapshot of its date and is not continued: no marks of what was implemented since or is still open
  (decisions go to `docs/decisions/`, open steps to `docs/todo.md`); only its references follow renames.
- Move finished tasks out of `docs/todo.md`; cite code by name, not by line number.
- A revised plan replaces the old one in place and is self-contained (skill `plan`).
- No numbers that go stale: `ARCHITECTURE.md`, Conventions, Code.
