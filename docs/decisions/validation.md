# Validation

Value constraints are checked in the `__post_init__` of frozen dataclasses, without pydantic, because pydantic is a
dependency and blocked the interpreter backend.

**Rejected**

- runtime type checks (the type checker's job: `ARCHITECTURE.md`, Conventions)
