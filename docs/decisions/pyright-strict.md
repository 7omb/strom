# pyright strict

The library in strict mode as a `src` execution environment listing the rules (`strict = ["src"]` can't be overridden
per rule); dispatchers on the open `Stage` class end in `case _:`, matches on closed unions (`Leaf`) name every kind
instead, so that the rule checks them; `reportPrivateUsage`, `reportUnusedClass`, `reportUnusedFunction` on since
2026-11-05 (see `module-structure.md`). Left out (65 errors on 2026-11-02, 55 of them these):
`reportUnknownArgumentType`/`MemberType`/`VariableType` (pyright's own Unknowns: the type parameters a stage kind adds
to `Stage[I, O]` after `match`, `isinstance` on `ExceptionGroup`; mypy's `disallow_any_expr` guards against `Any`),
`reportUnnecessaryComparison` (flags the `case unknown: assert_never(unknown)` arms that keep untagged items from
untyped code from vanishing). The rest (tests, benchmarks, `bin/`) in strict mode too since 2026-11-11, a last
environment with root `.`, without `reportPrivateUsage` (tests may test internals) and `reportUnknownLambdaType` (79 of
the 313 diagnostics there: the lambdas passed to stages; 214 were the three rules left out above, all from strom's own
inference, none from pytest or hypothesis, which are typed); five rules that strict mode leaves off
(`reportImplicitOverride`, `reportUninitializedInstanceVariable`, `reportPropertyTypeMismatch`,
`reportCallInDefaultInitializer`, `deprecateTypingAliases`) for every file, as they cost nothing on that day

**Rejected**

- strict for the tests with the library's list (until 2026-11-11, when pytest and hypothesis were thought untyped: the
  Unknowns of the lambdas that strom's API infers)
- `reportUnusedCallResult`, `reportMissingSuperCall`, `reportImplicitStringConcatenation` (2026-11-11: 262, 21 and 14
  diagnostics, no bug among those looked at)
- `reportImportCycles` (its one cycle is the deferred import of `strom._stages.display` in `strom._stages.model`, on
  purpose)
- casts or methods per stage kind to bind the extra type parameters for the dispatchers (casts; OO dispatch is rejected
  under Architecture; `Focused.with_focus` rebuilds a kind and dispatches nothing, see `lifting.md`)
- a typed local for the group (pyright narrows it to the assigned `BaseExceptionGroup[Unknown]`)
