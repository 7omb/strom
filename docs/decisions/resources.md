# Resources

Two, `"cpu" | "io"`, and the resource decides both where a function runs and how its items come: "io" streams them, one
pool task each, from an iterator kept in its worker (a list or a tuple comes whole, see `io-stage-items.md`); "cpu"
collects them in one pool task (`item_fn_of` matches the resource exhaustively, 2026-11-06); `PoolConfig` and
`RunBackends` hold one field per resource, so there is no "else" that a third one would fall into

**Rejected**

- separating placement from delivery by a parameter (a streamed cpu step: no use seen; a collected io step is what a
  returned list asks for, without a parameter on every factory)
- named resources (they would touch the factories and the stage data; open in `docs/todo.md` as cross-stage limits)
