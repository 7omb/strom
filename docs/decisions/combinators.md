# Combinators

Two stages are applied to one item by `duplicate() | product(f, g)`, not by a `fanout` (`&&&`) combinator, which the
user explicitly did not want.
