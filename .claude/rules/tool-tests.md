---
paths:
  - "tests/tools/**"
  - "tests/tool_helpers.py"
  - "tests/conftest.py"
---

# Tests of the tools

- Tool tests run git and make in a repository of their own (the fixture `repository`, which also removes the variables a
  make or pytest-xdist above hands down), never in this one, and name made-up paths in what they write (a module
  `shards` in a package `_parts` of the library that does not exist): `bin/rename.py` rewrites every text that cites a
  module it moves, a test's fixture too (2026-11-11).
- A test's own stdin is empty under pytest: a command it starts that inherits stdin reads nothing either, so such a test
  cannot tell inheriting from `DEVNULL`. Start the code under test in a child process that has input
  (`tests/tools/workspace/test_processes.py`; 2026-11-11: the injected bug was `missed` before).
