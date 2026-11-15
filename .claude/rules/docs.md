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
| What every session needs: agreements, commands | `CLAUDE.md` |
| Overview, repository, packages, design notes, conventions (code, tests, naming) | `ARCHITECTURE.md` |
| The public API and its semantics (user guide) | docstring of `src/strom/__init__.py` |
| A gotcha of one topic, for the files of that work | a note `.claude/rules/<topic>.md` |
| Multi-step procedures | a skill in `.claude/skills/` |
| A subagent's procedure and gotchas | `.claude/agents/<name>.md` |
| Decisions and rejected alternatives | `docs/decisions/<topic>.md` (form: the note `decisions.md`) |
| Open tasks | `docs/todo.md` |
| A plan in progress, the findings of a review | `docs/plans/<topic>.md`, linked from its task; deleted once done |
| Research, dated | `docs/research/<topic>.md` |
| Terms | `GLOSSARY.md` |
| Usage of a script, mechanism of the code | its docstring |

- `CLAUDE.md` is loaded into every session: at most `strom_tools.docs_check.doc_problems.SESSION_DOC_LIMIT` bytes;
  delete what code, docstrings or tests show at a glance.
- `ARCHITECTURE.md`: a design note opens with its subject in bold and holds one subject. Names that are looked up
  (variables, type parameters) are a nested list, a name per line.
- `GLOSSARY.md`: one term per bullet, the terms of a family under their parent. A definition says what the thing is; how
  it behaves is in its docstring. A group of terms opens with two sentences that place them.
- A note in `.claude/rules/` holds one topic, and its `paths` name the files of that work (a script a command names
  counts: `strom_tools.hooks.rules_loading`), so it loads only there; its body stays under the limit of the docs check.
  A gotcha goes where it is said when it happens: enforced (a deny rule, a check), else the tool's message, else the
  docstring of what it concerns, else a note with the rule, its reason and the date. Once a check or a message says it,
  the note goes.
- Research is a snapshot of its date and is not continued: no marks of what was implemented since or is still open
  (decisions go to `docs/decisions/`, open steps to `docs/todo.md`); only its references follow renames. A design
  belongs in a plan; form: the subagent `researcher`.
- Move finished tasks out of `docs/todo.md`; cite a task by its ID, code by name, not by line number.
- No numbers that go stale: `ARCHITECTURE.md`, Conventions, Code.
