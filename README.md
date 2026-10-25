# non-empty lists for Python

Inspired by [Haskell](https://hackage.haskell.org/package/base-4.21.0.0/docs/Data-List-NonEmpty.html) this library provides a `NonEmpty` class.
`NonEmpty` mimics the API for normal Python `list`s:

```python
from nonempty import NonEmpty

n = NonEmpty(1)
n.append(2)
n.extend([3])
n.pop()
```

However, it is not allowed to remove the last element of a non-empty list.
