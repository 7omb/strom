---
paths:
  - "src/strom/**/*.py"
  - "tests/**/*.py"
  - "examples/**/*.py"
  - "benchmarks/**/*.py"
---

# Typing – inference of strom's API

- pyright and ty infer `Unknown` for `flatten()`'s `T`, lambdas in `stage`/`where` and the passed-through type of
  `first`/`second`/`left`/`right` unless annotated (mypy: `Never`); pyright rejects what a lambda does with its
  parameter then (`stage(lambda items: [sorted(items)])` after a typed stage: use a named function, 2026-11-11); pyright
  couldn't match a protocol method with its own type parameter; pyright and ty infer `Unknown` for type variables that
  no argument binds (e.g. `first_focus()`).
- `stream(stage, inputs, pools)`: a generic stage passed directly (`flatten()`, `duplicate()`, `identity()`, `first(f)`,
  `second(f)`, also at the head of a chain) gets no type from `inputs` in mypy ("Cannot infer value of type parameter",
  or `Never`); pyright infers `duplicate()` and `first(f)` but not `flatten()`; ty infers all three (checked
  2026-11-05). Annotate the stage (`pairs: Stage[int, tuple[int, int]] = duplicate()`); after a typed stage `|` gives
  the context.
- `loop`: all three reject a body whose `Left` can't feed back; ty infers `Unknown` for `B` (no type variable from a
  union argument); pyright `Unknown` for a body that never exits.
- mypy infers `list[object]` for a list literal of different event classes: annotate `list[Event]`.
- A Protocol with a generic method `run[A, B]` is matched structurally by all three; but ty 0.0.91 accepts a
  *non-generic* implementation that mypy and pyright reject (checked 2026-11-08), also as an override of an ABC's
  generic method (`PoolCalls.cpu`, 2026-11-10).
- mypy and pyright infer a PEP 695 type parameter that no field uses (a phantom, `IteratorKey[O]`) as invariant, so
  `IteratorKey[O]` is no `IteratorKey[object]`: key a dict by a plain field instead.
