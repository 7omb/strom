# pyright strict

The library in strict mode as a `src` execution environment listing the rules (`strict = ["src"]` can't be overridden
per rule); dispatchers on the open `Stage` class end in `case _:`, matches on closed unions (`Leaf`) name every kind
instead, so that the rule checks them; `reportPrivateUsage`, `reportUnusedClass`, `reportUnusedFunction` on since
2026-11-05 (see `module-structure.md`). Left out (65 errors on 2026-11-02, 55 of them these):
`reportUnknownArgumentType`/`MemberType`/`VariableType` (pyright's own Unknowns: the type parameters a stage kind adds
to `Stage[I, O]` after `match`, `isinstance` on `ExceptionGroup`; mypy's `disallow_any_expr` guards against `Any`),
`reportUnnecessaryComparison` (flags the `case unknown: assert_never(unknown)` arms that keep untagged items from
untyped code from vanishing)

**Rejected**

- strict for the tests (untyped pytest and hypothesis API)
- casts or methods per stage kind to bind the extra type parameters for the dispatchers (casts; OO dispatch is rejected
  under Architecture; `Focused.with_focus` rebuilds a kind and dispatches nothing, see `lifting.md`)
- a typed local for the group (pyright narrows it to the assigned `BaseExceptionGroup[Unknown]`)
