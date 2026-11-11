# Stage kinds

The dispatchers on `Stage` end in `case _:` (see `pyright-strict.md`), so a missing arm is a runtime error, not a type
error; `test_every_stage_kind_goes_through_every_dispatcher` (`tests/stages/test_model.py`) runs a sample of every kind
through all of them (reference, run with fusion, lifted onto either element, in a `product` branch, repr) and fails when
a kind has no sample (2026-11-06; a kind is a concrete subclass of `Stage`: `Focused` is the abstract base of four)

**Rejected**

- a closed union of the kinds for dispatch (the type parameters a kind adds would be lost, see `pyright-strict.md`)
- a sealed `Stage` (user subclasses would be rejected by `__init_subclass__`: a runtime check, not requested)
