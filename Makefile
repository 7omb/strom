.PHONY: test
test:
	python -m pytest tests

.PHONY: test-extensive
test-extensive:
	python -m pytest --hypothesis-profile=extensive --numprocesses=auto tests

.PHONY: test-watch
test-watch:
	find . -name '*.py' | entr python -m pytest tests
