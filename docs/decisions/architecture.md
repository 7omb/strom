# Architecture

A stage is data, and interpreter functions give it its meaning, because data allows introspection, lifting and a
reference semantics. A kind's one method, `with_focus`, rebuilds it and runs nothing (`docs/decisions/lifting.md`).

**Rejected**

- OO (mixes the stage and its execution)
- visitor (boilerplate)
- tagless final (needs higher-kinded types, so `Any`)
- async stream functions (10× faster for cheap steps, but no introspection, lifting, reference semantics)
- threads (reason not recorded)
- frameworks (reason not recorded)
