# Architecture

Stages as data + interpreter functions (a kind's one method, `with_focus`, rebuilds it and runs nothing: see
`lifting.md`)

**Rejected**

- OO (mixes the stage and its execution)
- visitor (boilerplate)
- tagless final (needs HKT → `Any`)
- async stream functions (10× faster for cheap steps, but no introspection, lifting, reference semantics)
- threads
- frameworks
