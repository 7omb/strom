# Closing check

An iterator is closed when it has a `close` or `aclose` attribute, looked up with `getattr` (`close_if_closable`),
because the other checks either cost per item or leave closable iterators open. `getattr` gives `Any | None`, which
`--disallow-any-expr` accepts.

**Rejected**

- the runtime-checkable Protocol check per item (about 2.3 µs when it fails, e.g. tuple iterators)
- a per-type cache of that check (strong references to every type seen)
- `isinstance(…, Generator)` (files and other closable iterators would no longer be closed)
