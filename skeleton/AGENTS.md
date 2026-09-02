# AGENTS.md - {{tool_name}}

This is the `{{tool_name}}` tool repository, created from `tool-template`. Read files in this
order: `README.md`, `docs/VISION.md`, `docs/DESIGN.md`, `docs/STATUS.md`, and
`docs/tasks.md`. Documentation and state conventions are in `docs/conventions.md`.

## Central invariant: data beside the repository, never inside it

The repository contains code and durable public documentation. Runtime data defaults to
`${TOOLS_DATA:-$HOME/tools-data}/{{data_dir}}`. The `{{data_env}}` environment variable
overrides the root and an explicit `--home` overrides the environment. The current working
directory is never a data home.

Evaluate designs against a clean-machine test: a contributor clones this repository and can
run the keyless path without neighboring repositories or paid credentials. Template baseline
checks enforce the boundary.

## Code map

- `{{pkg}}/cli.py` defines `argparse` subcommands. `doctor` performs non-mutating
  diagnostics. Exit codes are 0 success, 75 quota, 111 transient failure, and 1 permanent or
  usage failure.
- `{{pkg}}/shared/` is vendored template code: provider adapters, atomic filesystem helpers,
  fail-closed shared configuration, and session capture. This repository owns its copy; a
  modification is an intentional fork that `tooltemplate diff` can reveal.
- `{{pkg}}/ext/` contains extensions. Add a directory for a new capability and keep the core
  independent of extension internals.
- `tests/` is hermetic and must stay green under `python3 -m pytest -q`. `smoke/` contains
  explicit live checks where exit 77 means skip.

## Rules

- Do not import sibling tools. Call another tool as a CLI process. Copy reusable code into
  `shared/` and own it locally.
- Paid APIs are optional configuration. `.env.sample` is documentation and is not read by
  code. `doctor` may report only whether a credential exists, never its value.
- Machine state uses JSON or SQLite and atomic writes. Markdown is a human-readable render,
  never the machine source of truth.
- Do not adjust provider CLI flags without direct verification. Each flag reflects observed
  client behavior rather than style preference.

## Do not copy

- Incident lists from other repositories. Accumulate evidence from this tool's own behavior.
- Domain configuration or profiles from sibling tools.
- Speculative mechanisms. Add complexity only for a demonstrated requirement.

## Routine changes

- New subcommand: add an `ext/` directory, register it in `cli.py`, add a test, and document
  the command in README.
- Shared-code change: record why the local copy intentionally diverges from the template.
- New check: add it under `harness/checks/` in `observe` mode first; switch to `block` only
  after existing violations are removed.
- Incident: add a regression test. If it represents a class of failures, add an enforcing
  guard and document the rule in `docs/conventions.md`.
- Keep `AGENTS.md` at or below 6,000 characters; `repo/agents-size` enforces the limit.

Use English in source and public documentation. Do not claim completion without running and
reporting the relevant tests.
