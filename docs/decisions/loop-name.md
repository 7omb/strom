# Loop name

The feedback combinator is `loop` (the user's choice, 2026-11-04; the term throughout: `Loop`, `_*_loop`, default name
`loop(f)`); its docstring leads with the convention (`Left`: continue, `Right`: output) and a paging example; the
factory table's unprefixed row is labelled `(none)`, not `loop`

**Rejected**

- `iterate` (Haskell's `iterate` builds an infinite sequence `x, f x, f (f x), …`; Python readers take it for iterating
  over items)
- `repeat_until`
- `feedback`
