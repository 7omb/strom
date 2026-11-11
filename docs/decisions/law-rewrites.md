# Law rewrites

Only call-preserving ones: `first(f) | first(g) -> first(f | g)`, `product(f, identity()) -> first(f)` (same calls on
both interpreters, 2026-11-01)

**Rejected**

- interchange and copy (common subexpressions): they change calls (see Semantics)
- allowing them for pure stages needs an effect marker (public API)
