---
paths:
  - "**/*.md"
---

# Formatting and checking the docs

- Lines have at most 120 characters: mdformat (pre-commit) wraps paragraphs, not table rows. Tables only for cells of a
  few words, each row within 120 characters; longer content as a list or sections (`bin/check_docs.py` enforces it,
  except the tables of `docs/research/` until they are restructured, B27 in `docs/todo.md`).
- At the end of a turn the Stop hook (`strom_tools.hooks.docs_fixes`) formats the changed docs with mdformat and runs
  `bin/check_docs.py`; within a turn, `make fix FILES=FILE`. mdformat keeps a code span on one line, so split a span
  that is longer than a line; and a block inside one list item (a code fence) puts a blank line between all items of its
  list, so keep an item to one paragraph (2026-11-11).
- `bin/check_docs.py` (in `make lint`) fails on a cited path or `strom.` name that does not exist, and on one that is
  not tracked (a clone would lack it): for a new file that a doc cites, leave it failing (the message says untracked)
  and give the user the `git add` with the report; never `git add -N` (`docs/decisions/docs-check.md`). The Stop hook
  does not block for such a citation: it tells the user, once per set of them.
- Wording (`docs/decisions/decision-form.md`): a reason is a clause with "because" or "so that", not a parenthesis,
  which holds names, dates, pointers and units; only a rejected alternative ends with its reason in parentheses. A run
  of independent items is a list, numbers that are compared are a table, and a reference names what it refers to unless
  that stands in the sentence before. A sentence has a verb and says what a thing is, not what it is not; "never" is
  kept for a prohibition. A colon stands before a pointer or an example, and "because", "so" or "then" where one of them
  is meant. Commands that run in order are a numbered list, and the items of one list have one form, sentences.
  "Separate", or nothing, stands for "of its own". For a review of the docs, `bin/check_docs.py --style` prints the
  paragraphs and list items worth a look.
