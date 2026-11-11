# Product name

The monoidal product (`***`) is `product` (the user's choice, 2026-11-04; the term throughout, also in tests and
benchmark ids; its internal kind stays `Join`); its docstring shows `duplicate() | product(f, g)` for one item into two
stages and the Cartesian product of 1:0..n branches

**Rejected**

- `parallel` (every stage already runs concurrently: the name hid that the input must be a pair and that outputs
  multiply)
- `both`
- `on_pair`
- `bimap` (exact only for 1:1 branches)
