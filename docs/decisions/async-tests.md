# Async tests

pytest-asyncio (rules: `.claude/rules/tests.md`); the Hypothesis tests stay sync, although pytest-asyncio also runs
`@given` on `async def` tests (tried with `-n 4` and the `ci` profile)

**Rejected**

- a hook in `conftest.py` running coroutine tests (pytest-asyncio covers async fixtures too)
- every test async (async helpers for no gain)
