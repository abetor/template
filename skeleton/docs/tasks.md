# tasks - {{tool_name}}

Agent task queue. Architectural context belongs in `docs/DESIGN.md`.

1. Define `docs/VISION.md`: purpose, target scenario, and deliberate non-goals.
2. Implement the first domain subcommand under `ext/`, register it in `cli.py`, and test it.
3. Update README quick start and `docs/STATUS.md` with observed evidence.

## Not now: return triggers

This is not a backlog. It records mechanisms deliberately deferred until their stated
trigger occurs.

| Mechanism | Return trigger | Current approach |
|---|---|---|
| Example: SQLite queue | A second concurrent writer appears | One JSON file written atomically |
