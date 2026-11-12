# Checker rules

The rule sets of ruff and the error codes of mypy beyond `--strict` that cost little on the day they were measured and
name a class of bug or of rot, all in `pyproject.toml` (2026-11-11). ruff: the sets with no or a few hits then (`A`,
`ASYNC`, `C4`, `DTZ`, `ERA`, `FA`, `FLY`, `FURB`, `G`, `ISC`, `LOG`, `PERF`, `PGH`, `PIE`, `PTH`, `Q`, `RET`, `RSE`,
`RUF`, `SIM`, `SLOT`, `T10`, `TID`, `YTT`): 58 hits, among them `RUF043` (8 `pytest.raises(match=)` patterns with
unescaped metacharacters) and `RUF100` (17 stale `noqa`). mypy: `ignore-without-code`, `possibly-undefined`,
`exhaustive-match`, `redundant-expr`, `truthy-bool`, `unused-awaitable` and the others listed there, `strict_bytes`: 8
diagnostics, 3 kept as ignores (`.claude/rules/typing.md`); `warn_unreachable` for the library and the tools only.
pyright: `docs/decisions/pyright-strict.md`

**Rejected**

- `PL`, `TRY`, `EM`, `FBT`, `PT018`, `COM`, `D`, `TC` (120 to 1,673 hits each, mostly style without a bug class; `TC`,
  261, moves imports into `TYPE_CHECKING` blocks: a second kind of import, for an import cost not measured)
- `RUF022`, `RUF023` (sorted `__all__` and `__slots__`: they follow the user guide and the fields)
- `warn_unreachable` in the tests (it flags the `raise` before the `yield` that makes an async generator, and attributes
  an awaited call changes after an `assert` narrowed them)
- `ASYNC110` in the tests (a poll of another thread's or process's state, which has no event to wait for)
