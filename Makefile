# The one definition of the checks: tox (tox.toml) and the git hooks (.pre-commit-config.yaml) run these targets.
# Python tools run in the locked venv, whatever venv is active (in a tox env: its own); ruff, pyright and ty come
# from the dev shell. A tox env that brings its own interpreter and packages passes `RUN=`; `ARGS` are further
# arguments (pytest's, or the examples to run).
RUN := uv run --frozen --no-active
ARGS :=
# Tests in parallel; not in addopts: pytest-xdist would disable the benchmarks (and slows single tests).
PYTEST := $(RUN) pytest -n auto

.PHONY: check
check: lint type test examples

.PHONY: test
test:
	$(PYTEST) $(ARGS)

.PHONY: cov
cov:
	$(PYTEST) --cov $(ARGS)

.PHONY: test-watch
test-watch:
	find . -name '*.py' | entr $(PYTEST) $(ARGS)

.PHONY: examples
examples:
	$(RUN) python bin/run_examples.py $(ARGS)

.PHONY: lint
lint:
	ruff check
	ruff format --check
	$(RUN) python bin/check_docs.py

.PHONY: type
type:
	$(RUN) mypy
	pyright
	ty check
	$(RUN) python bin/run_examples.py --type

.PHONY: bench
bench:
	$(RUN) pytest benchmarks/benchmark.py $(ARGS)

# Each benchmark once, without timing: checks that their results are right.
.PHONY: bench-results
bench-results:
	$(RUN) pytest benchmarks/benchmark.py --benchmark-disable $(ARGS)

.PHONY: build
build:
	uv build
