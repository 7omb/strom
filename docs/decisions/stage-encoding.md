# Stage encoding

Initial encoding: steps hold a `Leaf` (the user's function as data: what it maps to, where it runs); lifted and branch
steps are `FocusedStep`s (a step plus a `Focus`: `split`/`merge`/`finish`, composed by lifting, applied in the one task
loop, unlifted steps through `same_focus`; `_focusing` serves the reference semantics); joins hold branches plus a
`Focus` onto the pair of branch inputs (plain `product`: `same_focus`)

**Rejected**

- a join's own `split`/`merge`/`finish` (a second encoding of the focus: one hand-written rewrite per lifting)
- final encoding as a record of interpretations (pyright rejects the rank-2 lifting field; new interpreters would edit
  every constructor; opaque)
- object algebras/tagless final (need HKT)
- typed-port graph (types erased inside)
- join as a tagged linear stream (branches share queues and slots: latency f + g)
- right-nested chain and a pure `_Arr` node (no benefit without fusion; a fusion pass can flatten the tree itself)
- `adapt` closures on the leaf's ItemFn (one async generator per lifting level: A/B `first(stage)` 2.96 → 2.41 µs per
  item, `first³` 4.57 → 2.97, `product(stage, stage)` 8.79 → 7.81 with the focus in the loop)
- one wrapper generator per focused step (no gain at depth 1)
