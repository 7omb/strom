# Async tests

Async tests run on pytest-asyncio, not on a hook in `conftest.py` that runs coroutine tests, because pytest-asyncio
covers async fixtures too (the rules: `.claude/rules/tests.md`). The Hypothesis tests stay sync, because async helpers
would gain them nothing, although pytest-asyncio also runs `@given` on `async def` tests (tried with `-n 4` and the `ci`
profile).
