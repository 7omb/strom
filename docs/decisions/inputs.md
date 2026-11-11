# Inputs

`Iterable[I] | AsyncIterable[I]`; the feeder dispatches on the protocol once per run (`case AsyncIterable()`), an object
with both is iterated async; a dispatch on the protocol, not a value check; mypy, pyright and ty infer `I` from both and
reject inputs of another type (2026-11-05)

**Rejected**

- sync inputs only (async producers would need the `[None]` trick; nested runs fail)
