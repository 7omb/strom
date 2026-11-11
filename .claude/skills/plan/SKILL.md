---
name: plan
description: Writing, revising or refreshing a design or migration plan for strom (docs/plans/<topic>.md) - research, review for errors and simplifications, best practices and pitfalls of similar libraries, a self-contained revision. Use when asked to design, plan, sketch a migration, revise a plan ("V2"), or check whether a plan is still up to date.
---

# Plans

A plan lives in `docs/plans/<topic>.md`, linked from its task in `docs/todo.md`, and is deleted once done
(`.claude/rules/docs.md`). Read `ARCHITECTURE.md` and the sections of `docs/decisions.md` it touches first.

## Writing one

1. **Requirements**: the plan opens with a short list of everything the user asked for, updated in place with every new
   request.
2. **Analyse** the code it changes: every use of what changes (`grep`, `bin/rename.py OLD NEW` as a dry run for names),
   the tests and docs that cite it.
3. **Design**: the problem, the design (several when they differ in trade-offs, with a recommendation), what it rejects
   and why. Cite code by name, not by line number; a file the plan only proposes by its name without path and extension
   (a module `shards` in `src/strom/_runtime/`) or with an ellipsis: `bin/check_docs.py` fails on a path that does not
   exist. A claim about runtime behaviour ("once per worker", "teardown runs at shutdown") is checked with a probe
   script in the scratchpad before it goes into the plan; third-party packages via
   `uv run --frozen --with PKG python probe.py`.
4. **Steps**: executable from top to bottom, each one leaving `make check` green, with the checks it needs (skill
   `validate-change`). Only the details needed to execute it.
5. **Review** before handing it over: one pass with the lenses of `ARCHITECTURE.md`, and every design and example
   against the requirements; fix what it finds, report in the chat only what needs the user's decision.

## Revising one

When asked to go through a plan again (errors, simplifications, research):

- Update the requirements first.
- Check each step against the current code; look for contradictions and steps that can go.
- Research how established libraries and frameworks solved the same interface (asyncio, Trio, anyio, concurrent.futures,
  Ray, Dask, OpenTelemetry, …): best practices and the pitfalls they ran into. Cite sources.
- **The revision replaces the plan in place and is self-contained**: it never mentions the earlier version, what
  changed, or "V2"/"V3" (the user asked for this repeatedly; git keeps the history). Report the differences in the chat,
  not in the plan.
- End with the review of step 5 of "Writing one".

## Refreshing one

When the code changed since a plan was written: check every name, path and step against the code
(`bin/check_docs.py docs/plans/<topic>.md` for paths and names), drop what is done, update the rest in place, again
without a section about the differences.

## Before executing

Re-read the plan against the current code (other sessions may have refactored it), and ask where a step has become
ambiguous. Tick off steps in the plan as they are done.
