# Sum types

`route` (ArrowChoice `+++`) is a separate kind, `Route`, because a generalised `Join` would count per branch step and
keep pending state, which a route needs neither of.

- `choose`, `from_left` and `from_right` are composed by lifting (dist and undist inside the node). The branches are
  lifted to carry the passed-through element, and nothing is kept or counted at the route.
- The tags `Left` and `Right` are `@final` frozen dataclasses with an explicit covariant TypeVar (pyright infers PEP 695
  ones invariant).
- Routing is a `match` on the tags (`isinstance` on the library's own sum type is accepted).
- `left` and `right` are `route` with `identity()`, `tag_by(pred)` makes the tags, and there is no operator.

**Rejected**

- tagged tuples `tuple[Literal["left"], A] | …` (a tagged value is also a pair: `first` treats the tag as data)
- an untagged union with a `TypeIs` predicate (mypy and ty inferred `Right[int | str]`, pyright needed a cast)
- a 1:1 `tagging(fn)` factory (factories are 1:0..n)
- an operator (`^` takes no keyword arguments: two spellings; `+` would mean `<+>`, `&` suggests the rejected `&&&`)
- dist/undist as steps (change step ids; must be 1:1 inside branches)
- `<+>` deferred (close to the rejected `fanout`)
