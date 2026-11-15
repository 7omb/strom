# Lifting

Lifting is typed functions pushed down onto the steps, and a kind that holds a focus is lifted by wrapping that focus,
so that a lifted join stays one join.

- A join lifts by wrapping its focus: no nested join, and about 35% faster for `first(product(stage, stage))` in the
  sandbox.
- The wrappers of lifted focused steps and joins (`first_of`, `second_of`, `counted`) take the inner focus, so that all
  three checkers check a lifting.
- Every kind that holds a focus (a focused step, a join, a gather, a loop) is a `Focused` and rebuilds itself around
  another focus (`with_focus`, 2026-11-11). So a lifting has one arm and one helper for them, and a kind passes its
  settings on in one place, next to its fields.
- `with_focus` is a method, although behaviour otherwise lives in functions (`docs/decisions/architecture.md`): it
  builds data and runs nothing, and only an override sees the type parameters its kind adds. All three checkers accept
  it and reject a wrong lifting.

**Rejected**

- a helper per kind and lifting, each passing every setting on by hand (twelve, until 2026-11-11: dropping `concurrency`
  or `buffer_size` in four of them passed the whole suite; `test_lifting_keeps_every_setting` now checks it for every
  lifting)
- one function rebuilding any focused kind by `match` (the checkers lose the relation between a kind's own type
  parameters and those of its focus)
- `dataclasses.replace` for the rebuilding (it keeps the type of its argument: a cast)
- composing argument-less focuses with `_composed` (a wrong lifting was caught by mypy only, see
  `.claude/rules/typing.md`)
- one parametrised `_lift` (needed `Any`; re-examined 2026-11-06: the three liftings differ in the type function from I
  to their input type, which Python cannot express without `Any` or casts)
- `second` via `swap` (overhead)
- `first(m) = product(m, identity())` for Maps (5× slower, loses step overlap)
