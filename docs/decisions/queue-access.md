# Queue access

Steps and a join's loops use `put_nowait` and `get_nowait` when no wait is needed, because an awaited `put` or `get`
costs a coroutine per item, about 9% of 6 inline steps. asyncio's `put` and `get` don't yield then either (see anyio's
`send`). Only puts that wait count as blocked.
