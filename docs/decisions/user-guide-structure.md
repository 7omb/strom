# User guide structure

The user guide, the package docstring, has three parts, because in one flat list a newcomer had to read laws and queue
sizing before learning how to map a function.

1. Quick start: the example, types, running, the factory table, writing functions, `concurrency`, handling failures.
2. By task: pairs, branching, collecting per input, repeating (the combinators), and setup and teardown (worker
   handles).
3. Reference: semantics with the Haskell correspondences, resources vs. concurrency, metrics, fusion, order, failures,
   sync code, testing, backends.

The section names that others cite (`Backends`, `Fusion`, `Worker handles`, the factory table) are kept.

Decided with it (2026-11-15; the evidence: `docs/research/docs-writing.md`, 3.1 to 3.10):

- A combinator of part 2 has an input with the outputs it gives beside its rule, with the same four small stages
  throughout, and the notation stays. The tests check each line against the reference semantics
  (`test_the_examples_of_the_user_guide_give_the_outputs_it_shows` in `tests/test_init.py`).
- The example of the quick start is that of `README.md`, complete and with its output; a test keeps the two the same.
- Worker handles are a task of part 2, with the advice on connection pools: part 1 held them before the reader had
  written a function. What one combinator does in full is in its docstring, to which part 2 points.
- A term is introduced where the guide first uses it (step, pool task, in flight, occurrence): `pydoc strom` shows no
  glossary.
- The correspondences to Haskell are for readers who know it and say where they end; the feature list of `README.md`
  says what a combinator does before it names its arrow.

**Rejected**

- the instances in place of the notation (readers who know the model read the terse form as well or better)
- a box of fixed points per combinator in part 2, as Pekko's "emits / backpressures / completes" (the docstring of each
  combinator has them in one place)
- examples as doctests (a run's outputs come in any order, and the examples would need their functions in the docstring)
