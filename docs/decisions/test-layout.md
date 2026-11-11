# Test layout

One test module per library module (the layout: the docstring of `tests/conftest.py`); test data in the test modules
that need it (the static checks define their types in `STATIC_SETUP`); directories without `__init__.py` (test module
names must be unique); the GIL warning filter in `filterwarnings`

**Rejected**

- one module per part of the former nine-part `test_pipelines.py` (parts cut across library modules)
- test packages with `__init__.py` (module names `tests.…`, no gain)
- `from helpers import TRACK` (the autouse fixture replaces it: a stale tracker)
- `pytestmark` per module (repeated in nearly every one)
