# Inputs

A run takes `Iterable[I] | AsyncIterable[I]` as its inputs, because with sync inputs alone an async producer would need
the `[None]` trick and nested runs fail. The feeder dispatches on the protocol once per run (`case AsyncIterable()`),
which is no value check; an object with both protocols is iterated async. mypy, pyright and ty infer `I` from both and
reject inputs of another type (2026-11-05).
