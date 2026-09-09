# template

`template` creates self-contained Python tool repositories and detects drift between
generated repositories and the current template. It is intended for teams that want a
repeatable repository shape without turning generated projects into permanently coupled
framework clients.

[Quick start](#quick-start) | [Offline demo](#demo) | [Architecture](docs/DESIGN.md) | [Tests](#tests) | [Contributing and agent guide](AGENTS.md) | [MIT license](LICENSE)

## Problem

A clone-and-rename workflow loses its relationship with the source template. Improvements
to shared adapters, repository checks, and data-boundary rules never reach existing
projects, while copying an entire framework into every repository makes future comparison
ambiguous.

`template` makes repository creation a deterministic function of the committed
`skeleton/` tree and explicit parameters. Existing projects can then be regenerated in a
temporary directory and compared byte for byte with the template-owned files.

## What it provides

- `birth` creates a new repository, stamps repository and package names, writes a stable
  manifest, preserves executable bits, and initializes Git.
- `diff` regenerates the tracked portion of a child repository and reports `in-sync`,
  `drifted`, and `missing` files without modifying the child.
- `harness/run_checks.py` discovers baseline and repository-local checks and enforces block
  checks with machine-readable output.
- `skeleton/` provides a small CLI, fail-closed TOML configuration, atomic filesystem
  helpers, agent adapters, hermetic test scaffolding, and public contributor guidance.

The implementation uses only the Python standard library at runtime.

## Architecture

The generator reads both the skeleton file list and file contents from the template
repository's Git index. Unstaged skeleton edits are deliberately excluded and reported as
a warning. This keeps generation reproducible from a specific committed state.

The generated `.tool-manifest.json` records the template name, stamping parameters,
template-owned glob patterns, and the rationale for files that children own themselves.
`diff` reads those parameters, regenerates into a temporary directory, and compares the
current template-owned paths. It never auto-merges changes.

Baseline checks are standalone Python programs. Each declares an ID and `observe` or
`block` mode in its header and accepts `--repo-root`. The runner combines template checks
with local child checks, deduplicates IDs, and fails only for violated block checks.

See [docs/DESIGN.md](docs/DESIGN.md) for the detailed contracts and design decisions.

## Quick start

Requirements: Python 3.11 or newer and Git. Run from a Git checkout with
an editable installation: generation reads the indexed `skeleton/` and
repository-owned harness assets. A standalone wheel is not a supported setup. The
repository is `template`, the distribution is `tool-template`, and the Python package is
`tooltemplate`.

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .

# Create a repository. Use --pkg when the import package cannot be derived
# from the kebab-case repository name.
python3 -m tooltemplate birth --name tool-example --into ../tool-example

# Detect drift later. Exit 0 means in sync, 1 means drift, and 2 means an
# operational error.
python3 -m tooltemplate diff --target ../tool-example

# Run baseline plus repository-local checks.
python3 harness/run_checks.py --repo-root ../tool-example
```

`birth` refuses a non-empty target unless it contains only explicitly safe metadata. It
also warns when Git identity is missing, but it does not create the first commit.

## Demo

Use a temporary data root to keep the demonstration isolated:

```bash
demo_root="$(mktemp -d)"
TOOLS_DATA="$demo_root/data" python3 -m tooltemplate birth \
  --name tool-example --into "$demo_root/tool-example"
TOOLS_DATA="$demo_root/data" python3 -m tooltemplate diff \
  --target "$demo_root/tool-example"
python3 harness/run_checks.py --repo-root "$demo_root/tool-example"
```

The successful path prints the created repository and data paths, an `in-sync` drift
result, and a summary with all block checks passing. Generated repositories contain their
own Git metadata but no commit.

## Data and credential boundary

Generated tools keep runtime data outside the repository. Resolution order is:

1. explicit `--home`;
2. the generated tool's dedicated environment variable;
3. `$TOOLS_DATA/<tool>-data`;
4. `~/tools-data/<tool>-data`.

The default remains configurable through `TOOLS_DATA`; the current working directory is
never used as a data home. `birth` creates the selected data directory idempotently.
`diff` does not touch it.

The optional shared `$TOOLS_DATA/config.toml` stores paths, commands, and environment
variable names, not credential values. Secrets remain in the process environment.
`.env.sample` files document names only, while `.env` and `.env.*` are ignored.

## Limitations

- Only one generation profile, `default`, is implemented.
- Drift is detected but never merged automatically.
- The built-in secret check recognizes known credential formats, sensitive filenames,
  and populated environment samples. It does not prove that arbitrary JSON/YAML values or
  Git history are secret-free. A separate history scan is required before publication.
- The bundled agent adapters are reusable scaffolding. Their parsers and classification
  rules are tested through generated children, but this repository does not perform live
  provider calls.
- The generated CLI is a scaffold. A child repository must add and test its own domain
  commands.

## Tests

Run the hermetic suite without bytecode or pytest cache files:

```bash
python3 -m pip install 'pytest>=8'
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider
python3 harness/run_checks.py --repo-root .
```

For an end-to-end acceptance check, create a child under a temporary directory, run the
child's tests and baseline checks, and verify `tooltemplate diff` reports `in-sync`.

## Provenance

This repository began as a public source snapshot of a personal tool. Earlier local development
history is not included.

## License

MIT. Copyright (c) 2026 abetor. See [LICENSE](LICENSE).
