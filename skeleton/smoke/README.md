# Smoke tests

Tests under `tests/` are hermetic and do not access networks or live providers. Explicit
live verification belongs here as `smoke_*.py` or `smoke_*.sh`, runs manually or under an
external scheduler, and is not part of the hermetic CI gate.

Exit 77 means skipped because a required binary, login, or network is unavailable. It is not
a failure; every other non-zero exit is a failure.

## Live verification report

Code-level success is not proof of live behavior. Record each run as:

| Step | Expected | Observed | Result |
|---|---|---|---|

Include a section named "Unverified boundaries" explaining what the run did not exercise
and why.

Before trusting a green smoke test, point it at an intentionally unavailable target such as
invalid configuration or a stopped service. The test must fail. A green result against the
dead target is a defect in the smoke test. Exit 77 is valid only when the test explicitly
states that it did not run.
