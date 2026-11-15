# pyright strict

pyright checks the library in strict mode, as a `src` execution environment that lists the rules, because
`strict = ["src"]` can't be overridden per rule.

- Dispatchers on the open `Stage` class end in `case _:`; matches on closed unions (`Leaf`) name every kind instead, so
  that the rule checks them.
- `reportPrivateUsage`, `reportUnusedClass` and `reportUnusedFunction` are on since 2026-11-05
  (`docs/decisions/module-structure.md`).
- Left out (65 errors on 2026-11-02, 55 of them these): `reportUnknownArgumentType`, `reportUnknownMemberType` and
  `reportUnknownVariableType`, and `reportUnnecessaryComparison`. The first three report pyright's own Unknowns: the
  type parameters a stage kind adds to `Stage[I, O]` after `match`, and `isinstance` on `ExceptionGroup`; mypy's
  `disallow_any_expr` guards against `Any`. The last flags the `case unknown: assert_never(unknown)` arms that keep
  untagged items from untyped code from vanishing.
- The rest (tests, benchmarks, `bin/`) is in strict mode too since 2026-11-11, as a last environment with root `.`,
  without `reportPrivateUsage` (tests may test internals) and `reportUnknownLambdaType`. That rule made 79 of the 313
  diagnostics there, the lambdas passed to stages; 214 were the three rules left out above, all from strom's own
  inference, none from pytest or hypothesis, which are typed.
- Five rules that strict mode leaves off hold for every file, as they cost nothing on that day:
  `reportImplicitOverride`, `reportUninitializedInstanceVariable`, `reportPropertyTypeMismatch`,
  `reportCallInDefaultInitializer`, `deprecateTypingAliases`.

**Rejected**

- strict for the tests with the library's list (until 2026-11-11, when pytest and hypothesis were thought untyped: the
  Unknowns of the lambdas that strom's API infers)
- `reportUnusedCallResult`, `reportMissingSuperCall`, `reportImplicitStringConcatenation` (2026-11-11: 262, 21 and 14
  diagnostics, no bug among those looked at)
- `reportImportCycles` (its one cycle is the deferred import of `strom._stages.display` in `strom._stages.model`, on
  purpose)
- casts or methods per stage kind to bind the extra type parameters for the dispatchers (casts; OO dispatch is rejected
  in `docs/decisions/architecture.md`; `Focused.with_focus` rebuilds a kind and dispatches nothing, see
  `docs/decisions/lifting.md`)
- a typed local for the group (pyright narrows it to the assigned `BaseExceptionGroup[Unknown]`)
