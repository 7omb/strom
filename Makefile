# The one definition of the checks and the fixers: tox (tox.toml), the git hooks (.pre-commit-config.yaml) and the
# Claude Code hooks (.claude/hooks) run these targets. Python tools run in the locked venv, whatever venv is active
# (in a tox env: its own); ruff, pyright and ty come from the dev shell. A tox env that brings its own interpreter
# and packages passes `RUN=`; `ARGS` are further arguments (pytest's, the examples to run, options of `ruff check`).
RUN := uv run --frozen --no-active
ARGS :=
# Tests in parallel; not in addopts: pytest-xdist would disable the benchmarks (and slows single tests).
PYTEST := $(RUN) pytest -n auto
# FILES narrows `fix` and `lint-python` to some files (names without spaces), each tool taking those of its kind:
# the hooks pass the files of a commit, or those Claude changed. Without FILES, every file.
FILES :=
python_files := $(if $(FILES),$(filter %.py %.pyi,$(FILES)),.)
# the Markdown files as pre-commit takes them (nothing: FILES without any)
markdown_files := $(if $(FILES),$(if $(filter %.md,$(FILES)),--files $(filter %.md,$(FILES))),--all-files)

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
lint: lint-python lint-docs

.PHONY: lint-python
lint-python:
	$(if $(python_files),ruff check $(ARGS) $(python_files))
	$(if $(python_files),ruff format --check $(python_files))

.PHONY: lint-docs
lint-docs:
	$(RUN) python bin/check_docs.py

# The fixers: what ruff can fix and its formatter, and mdformat as the commit hook has it (.pre-commit-config.yaml:
# in pre-commit's venv; pre-commit also fails when the hook changed a file, so a second run tells that from an error
# of mdformat). What they leave is `lint`'s to report.
mdformat := pre-commit run mdformat $(markdown_files)
.PHONY: fix
fix:
	$(if $(python_files),ruff check --fix-only --quiet $(ARGS) $(python_files))
	$(if $(python_files),ruff format --quiet $(python_files))
	$(if $(markdown_files),$(mdformat) > /dev/null || $(mdformat))

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
