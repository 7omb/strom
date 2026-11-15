# Stage kinds

A test runs a sample of every stage kind through every dispatcher, because the dispatchers on `Stage` end in `case _:`
(`docs/decisions/pyright-strict.md`), so a missing arm is a runtime error, not a type error.
`test_every_stage_kind_goes_through_every_dispatcher` (`tests/stages/test_model.py`) covers the reference, a run with
fusion, a lifting onto either element, a `product` branch and the repr, and it fails when a kind has no sample. A kind
is a concrete subclass of `Stage`; `Focused` is the abstract base of four.

**Rejected**

- a closed union of the kinds for dispatch (the type parameters a kind adds would be lost, see
  `docs/decisions/pyright-strict.md`)
- a sealed `Stage` (user subclasses would be rejected by `__init_subclass__`: a runtime check, not requested)
