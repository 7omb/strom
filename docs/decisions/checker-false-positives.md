# Checker false positives

A false positive of one checker gets that checker's ignore comment on its line, and the code keeps the shape the other
two accept, because a shape made for a checker's bug stays when the bug is fixed. Each ignore has a dated entry in
`.claude/rules/typing.md`, which lists each checker's comment and what reports an unused one: an ignore expires with its
bug. mypy's `ignore-without-code` makes each of its ignores name the code, and ruff's `# noqa: CODE` is checked by
`RUF100` (2026-11-11: 17 had outlived their rule, among them an `E402` in every wrapper).

**Rejected**

- shaping the code so that the checker passes (2026-11-06 to 2026-11-11: the next item of an `io_stage` iterator as a
  bound method of its key with a dummy argument, and explicit type arguments in `_make_step`): a shape stays when the
  bug is fixed; `_make_step` no longer needed its type arguments, and nothing said so
- one `# type: ignore` for mypy and pyright together (an ignore for the false positive of one blinds the other on that
  line, and pyright reports the one mypy alone needs as unnecessary)
- ty's default, a warning for an unused ignore (`ty check` passes with it)
