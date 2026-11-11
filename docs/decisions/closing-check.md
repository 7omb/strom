# Closing check

`getattr` of `close`/`aclose` (`close_if_closable`; typed `Any | None`, accepted by `--disallow-any-expr`)

**Rejected**

- the runtime-checkable Protocol check per item (about 2.3 µs when it fails, e.g. tuple iterators)
- a per-type cache of that check (strong references to every type seen)
- `isinstance(…, Generator)` (files and other closable iterators would no longer be closed)
