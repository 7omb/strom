"""What stages mean and how they run: the reference semantics and the streaming interpreter.

Each interpreter dispatches on the stage kinds; the typed work is done by helpers. (Pattern matching
cannot recover the hidden type parameters of a Step, Chain or Join, hence the helpers. mypy narrows the
matched stages to Any type arguments, i.e. it does not check the calls in the arms; pyright and ty keep
I and O and check them. Leaves are a closed union, which all three check fully.)"""
