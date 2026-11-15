# Product name

The monoidal product (`***`) is named `product`, the user's choice, and the term is used throughout, also in tests and
benchmark ids; its internal kind stays `Join`. Its docstring shows `duplicate() | product(f, g)` for one item into two
stages, and the Cartesian product of 1:0..n branches.

**Rejected**

- `parallel` (every stage already runs concurrently: the name hid that the input must be a pair and that outputs
  multiply)
- `both` (not the user's choice; no further reason recorded)
- `on_pair` (not the user's choice; no further reason recorded)
- `bimap` (exact only for 1:1 branches)
