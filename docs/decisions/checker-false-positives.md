# Checker false positives

A false positive of one checker gets that checker's ignore comment on its line, with a dated entry in
`.claude/rules/typing.md`, and the code keeps the shape the other two accept (2026-11-11). Each checker has a comment of
its own and fails on one it no longer needs, so an ignore expires with its bug: `# type: ignore[code]` is mypy's alone
(pyright's `enableTypeIgnoreComments` is off), `# pyright: ignore[rule]` is checked by
`reportUnnecessaryTypeIgnoreComment`, `# ty: ignore[rule]` by `unused-ignore-comment` as an error

**Rejected**

- shaping the code so that the checker passes (2026-11-06 to 2026-11-11: the next item of an `io_stage` iterator as a
  bound method of its key with a dummy argument, and explicit type arguments in `_make_step`): a shape stays when the
  bug is fixed; `_make_step` no longer needed its type arguments, and nothing said so
- one `# type: ignore` for mypy and pyright together (an ignore for the false positive of one blinds the other on that
  line, and pyright reports the one mypy alone needs as unnecessary)
- ty's default, a warning for an unused ignore (`ty check` passes with it)
