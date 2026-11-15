# Law rewrites

A law serves as a rewrite only if it preserves the calls, because the laws equate output bags, not calls
(`ARCHITECTURE.md`, Semantics). `first(f) | first(g) -> first(f | g)` and `product(f, identity()) -> first(f)` do: they
make the same calls on both interpreters (2026-11-01).

**Rejected**

- interchange and copy (common subexpressions): they change calls (see Semantics)
- allowing them for pure stages needs an effect marker (public API)
