---
name: plan
description: Writing, revising or refreshing a design or migration plan for strom (docs/plans/<topic>.md) - research, review for errors and simplifications, best practices and pitfalls of similar libraries, a self-contained revision. Use when asked to design, plan, sketch a migration, revise a plan ("V2"), or check whether a plan is still up to date.
---

# Plans

A plan lives in `docs/plans/<topic>.md`, linked from its task in `docs/todo.md`, and is deleted once done
(`.claude/rules/docs.md`). Read `ARCHITECTURE.md` and the decisions in `docs/decisions/` it touches first. A list of
findings is a review (skill `review`).

## Writing one

1. **Analyse** the code the plan changes: every use of what changes (`grep`, `bin/rename.py OLD NEW` as a dry run for
   names), the tests and docs that cite it.
2. **Write** its parts in this order (why: `docs/decisions/plan-form.md`):
   - An opening paragraph: the date and the state (waiting for its open questions, agreed, or in progress with the next
     step), what is true afterwards and how one sees it (a command, a test, a measurement).
   - **Requirements**: everything the user asked for, updated in place with every new request. Under it "Not part of it"
     (what one could expect and is left out) and "Stays as it is" (behaviour, names or numbers that must not change).
   - **Problem**: what is wrong or missing, with its reproduction (a failing test, a dated measurement).
   - **Result**: the change as its user sees it, before any mechanism. For the public API: the signature, a call and the
     sentences of the user guide as they will read. For an internal change: the names a contributor finds, or the number
     before and after.
   - **Design**: the mechanism as far as the reviewer and the steps need it (several designs when they differ in
     trade-offs, with a recommendation), what could break and the test that shows it, and under **Rejected** one bullet
     per alternative with why. A plan without a trade-off has no Design.
   - **Open questions**: what the user decides before a step starts, each with an ID, its options and a recommendation.
     A decided question moves into Requirements or Design, and the section goes when it is empty.
   - **Steps**: checkboxes, executable from top to bottom. Each names what changes and the check that shows it (a test
     that fails before and passes after, the expected number), leaves `make check` green and has the checks it needs
     (skill `validate-change`), with only the details needed to execute it. The first step reproduces the problem; the
     last compares the result with the requirements, records the decisions and measurements in `docs/decisions/` and
     deletes the plan.
3. **Cite** code by name, not by line number; a file the plan only proposes by its name without path and extension (a
   module `shards` in `src/strom/_runtime/`) or with an ellipsis: `bin/check_docs.py` fails on a path that does not
   exist. A claim about runtime behaviour ("once per worker", "teardown runs at shutdown") is checked with a probe
   script in the scratchpad before it goes into the plan; third-party packages via
   `uv run --frozen --with PKG python probe.py`.
4. **Review** before handing it over: one pass with the lenses of `ARCHITECTURE.md`, and every design and example
   against the requirements; fix what it finds. What needs the user's decision is an open question of the plan, named in
   the chat.

## Revising one

When asked to go through a plan again (errors, simplifications, research):

- Update the requirements first.
- Check each step against the current code; look for contradictions and steps that can go.
- Research how established libraries and frameworks solved the same interface: their best practices and the pitfalls
  they ran into. A subagent `researcher` per topic reads the sources, with its questions listed in the prompt (how many
  may run: `CLAUDE.md`, Process). Cite the sources, with its marks of what was not read in the source itself.
- **The revision replaces the plan in place and is self-contained**: it never mentions the earlier version, what
  changed, or "V2"/"V3" (the user asked for this repeatedly; git keeps the history). Report the differences in the chat,
  not in the plan.
- End with the review of step 4 of "Writing one".

## Refreshing one

When the code changed since a plan was written: check every name, path and open step against the code
(`bin/check_docs.py docs/plans/<topic>.md` for paths and names) and update them in place, again without a section about
the differences.

## Before executing

Re-read the plan against the current code (other sessions may have refactored it), and ask where a step has become
ambiguous. The state of the work is in the plan: tick a step off when it is done, split one that stops midway into what
is done and the rest, and keep the state of the opening paragraph current. The requirements change only with the user.
