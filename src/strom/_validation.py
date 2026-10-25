"""Value constraints that types cannot express."""


def check_positive(name: str, value: int) -> None:
    """Value constraint that types cannot express; types are left to the type checker."""
    if value < 1:
        raise ValueError(f"{name} must be >= 1, got {value}")
