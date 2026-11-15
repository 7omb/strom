# Loop name

The feedback combinator is named `loop`, the user's choice, and the term is used throughout: `Loop`, `_*_loop`, the
default name `loop(f)`. Its docstring leads with the convention (`Left`: continue, `Right`: output) and a paging
example. The factory table's unprefixed row is labelled `(none)`, not `loop`.

**Rejected**

- `iterate` (Haskell's `iterate` builds an infinite sequence `x, f x, f (f x), …`; Python readers take it for iterating
  over items)
- `repeat_until` (not the user's choice; no further reason recorded)
- `feedback` (not the user's choice; no further reason recorded)
