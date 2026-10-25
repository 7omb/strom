---
name: review
description: Review of strom's code, design or docs as a numbered list of findings (problem plus fix) for the user to pick from ("Implement 1-4, 6A"). Use when asked to review, analyse or check the code, a change, the structure, the API, naming or the docs and list findings; not for validating a change (skill validate-change).
---

# Reviewing strom

Read `ARCHITECTURE.md` (conventions, lenses) and the sections of `docs/decisions.md` that the scope touches first: a
finding that re-proposes a rejected alternative needs a new reason, stated as such.

## Scope and criteria

Take the scope from the request (the whole code, the last change: `git diff REV`, a package, the docs, a plan). Check
what the request names; when it names nothing, all of these:

- **Correctness**: concurrency limits, end of stream, closing, cancellation, failures (user guide, Failures), and future
  bugs a change makes easy. Confirm a suspected bug with a test or a run before reporting it as one; otherwise say it is
  unconfirmed.
- **Consistency**: names follow `GLOSSARY.md` and the naming conventions (one term per concept); the reference and
  streaming interpreters agree in structure and entry points.
- **Structure**: cohesive modules with narrow public surfaces (privacy by namespace); a definition lives with its only
  user; no import cycles; SOLID where it applies to functional code.
- **Simplicity**: leftovers of old designs, duplications, ceremony, options without a use.
- **Tests**: orthogonal to each other, testing behaviour through the public API where possible; no public addition only
  for tests.
- **Docs**: each fact once and in its place (`.claude/rules/docs.md`), short and precise, up to date
  (`bin/check_docs.py`), no history of past designs outside `docs/decisions.md`.
- **UX and DX**: what a user or contributor must learn; names that mislead.

## Output

- A numbered list, most important first; a group of findings gets a letter prefix (`A1`, `S3`). Each finding: the
  problem in one or two sentences with where (`module.name`, not line numbers), then the fix; alternatives as lettered
  options (`4A`, `4B`) with their trade-off and a recommendation.
- Concise: no praise, no findings without a fix, no restating the code.
- More than about five findings: also write the list to `docs/plans/<topic>-review.md`, so that later sessions can
  resolve the IDs; delete it once its findings are done or rejected (rejections with a reason go to
  `docs/decisions.md`).
- Change nothing in a review unless asked; the user picks the findings to implement.
