# Test layout

There is one test module per library module (the layout: the docstring of `tests/conftest.py`), not one per part of the
former single test file, because those parts cut across library modules. Test data is in the test modules that need it
(the static checks define their types in `STATIC_SETUP`). The directories have no `__init__.py`, so the names of test
modules must be unique. The GIL warning filter is in `filterwarnings`.

**Rejected**

- test packages with `__init__.py` (module names `tests.…`, no gain)
- `from helpers import TRACK` (the autouse fixture replaces it: a stale tracker)
- `pytestmark` per module (repeated in nearly every one)
