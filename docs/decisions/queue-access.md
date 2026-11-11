# Queue access

`put_nowait`/`get_nowait` when no wait is needed (asyncio's `put`/`get` don't yield then either, see anyio's `send`), in
steps and in a join's loops; only puts that wait count as blocked

**Rejected**

- awaiting `put`/`get` per item (a coroutine each: about 9% of 6 inline steps)
