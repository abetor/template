# {{tool_name}}

After birth, replace this paragraph with one sentence explaining what the tool does and why
it exists.

This repository was created from `tool-template`. Detect template drift from the template
repository:

```bash
python3 -m tooltemplate diff --target <this-repository>
```

## Status

New scaffold: repository mechanics exist, but the domain implementation does not. Keep the
honest current status in `docs/STATUS.md`.

## Quick start

```bash
mkdir -p "${TOOLS_DATA:-$HOME/tools-data}/{{data_dir}}"
python3 -m {{pkg}} doctor              # {{data_env}} and --home override the root
python3 -m pytest -q                   # hermetic tests
```

Registration and paid credentials are not required. `.env.sample` lists optional settings,
not prerequisites.

Runtime data lives outside the repository. The root is `$TOOLS_DATA` or the documented
default `~/tools-data/`. `birth` creates `<root>/{{data_dir}}` idempotently and does not
modify existing data. The shared `<root>/config.toml` is read through `shared/config.py`;
absence is allowed, while an invalid existing file makes `doctor` fail. The file contains
environment variable names, never credential values.

## Agent-facing invocation contract

An agent may call the tool from any directory once it knows the repository path. After
birth, document real subcommands as `command / input / output / exit codes`. The following
shows the required form; `doctor` is implemented and the rest is a template:

- Command: `python3 -m {{pkg}} [--home <data-directory>] doctor`. Run from this repository,
  or set `PYTHONPATH=<this-repository>` when calling it elsewhere.
- Input: command-line arguments; standard input is not read.
- Output: results on stdout and diagnostics on stderr.
- Exit codes: 0 success, 75 quota window, 111 transient failure, and 1 permanent,
  configuration, or usage failure.

## Non-goals

Describe what the tool deliberately does not do so future changes do not blur its boundary.
Example: "This is not a daemon; scheduling belongs to an external supervisor."

## Known limitations

List each open limitation and the current safeguard. Put evidence and verification detail in
`docs/STATUS.md`.

## Repository map

- `{{pkg}}/` contains `cli.py`, reusable `shared/` adapters and filesystem/configuration
  helpers, and isolated extensions under `ext/`.
- `docs/` contains vision, design, status, tasks, and documentation conventions.
- `harness/` contains repository identity and local checks; baseline checks live in the
  template repository.
- `tests/` contains hermetic pytest tests; `smoke/` contains explicit live checks where exit
  77 means skipped because the environment is unavailable.
- `deploy/` contains service-unit templates.

Contributor and agent guidance starts in `AGENTS.md`.
