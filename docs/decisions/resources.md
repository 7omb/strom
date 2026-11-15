# Resources

A leaf's resource, `"cpu"` or `"io"`, not a parameter of the factories, decides where a function runs and how its items
come, because a streamed cpu step had no use and a returned list already gives a collected io step. "io" streams the
items, one pool task each, from an iterator kept in its worker (a list or a tuple comes whole,
`docs/decisions/io-stage-items.md`); "cpu" collects them in one pool task. `item_fn_of` matches the resource
exhaustively, and `PoolConfig` and `RunBackends` hold one field per resource, so there is no "else" that a third one
would fall into.

**Rejected**

- named resources (they would touch the factories and the stage data; open as B25 in `docs/todo.md`, cross-stage limits)
