# Run errors

A failed run always raises one `ExceptionGroup` ("pipeline run failed") of the errors `failing` recorded, even of a
single one, because a bare error for the common case leaves callers without code for the group. The errors are as raised
(a user's own group stays whole), with the run's TaskGroup nesting removed; KeyboardInterrupt and SystemExit are
unwrapped. This is strict like asyncio's TaskGroup, anyio and Trio >= 0.25 (Trio docs, "Designing for multiple errors").
The block of `stream` follows the TaskGroup rules (user guide, Failures), and the outputs never end as if complete after
a failure.

**Rejected**

- the block's error alone unchanged and the block not cancelled (Trio's "option 2"; users know the TaskGroup rules)
- one error unwrapped, several as a flat group (callers handle only the common case; flattening took a user's group
  apart)
- a library error raised `from` the group (user errors only via `__cause__`)
- only the first error (drops concurrent ones)
