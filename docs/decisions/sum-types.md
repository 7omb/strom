# Sum types

`route` (ArrowChoice `+++`) as its own kind `Route`: `choose`/`from_left`/`from_right` composed by lifting (dist/undist
inside the node), branches lifted to carry the passed-through element, nothing kept or counted at the route; tags
`Left`/`Right`: `@final` frozen dataclasses with an explicit covariant TypeVar (pyright infers PEP 695 ones invariant);
routing by `match` on the tags (`isinstance` on the library's own sum type is accepted); `left`/`right` = `route` with
`identity()`; `tag_by(pred)`; no operator

**Rejected**

- tagged tuples `tuple[Literal["left"], A] | …` (a tagged value is also a pair: `first` treats the tag as data)
- an untagged union with a `TypeIs` predicate (mypy and ty inferred `Right[int | str]`, pyright needed a cast)
- a 1:1 `tagging(fn)` factory (factories are 1:0..n)
- an operator (`^` takes no keyword arguments: two spellings; `+` would mean `<+>`, `&` suggests the rejected `&&&`)
- a generalised `Join` (counting per branch step, pending state)
- dist/undist as steps (change step ids; must be 1:1 inside branches)
- `<+>` deferred (close to the rejected `fanout`)
