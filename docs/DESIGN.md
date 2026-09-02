# DESIGN - tool-template

This document describes the architecture, contracts, and reasons behind the major design
choices. The implementation is owned by this repository, uses the Python standard library,
and does not import code from sibling repositories.

## Generator

`tooltemplate/core.py` contains the mechanics, `tooltemplate/cli.py` defines the command
line interface, and `tooltemplate/__main__.py` is the module entry point.

The complete source of a birth operation is the Git index:

- `git ls-files -s -z -- skeleton/` supplies paths, blob IDs, stages, and executable bits;
- one `git cat-file --batch` process supplies blob contents;
- the working-tree copies of skeleton files are not used.

Reading the index makes birth reproducible from the state that will be committed. An
unstaged edit therefore does not enter a child repository. Both `birth` and `diff` report
such edits so that the exclusion cannot remain silent. An unmerged index stage or duplicate
relative path is rejected before the destination is written.

Stamping is a pure function of relative path, bytes, and parameters. `{{tool_name}}` becomes
the kebab-case repository name and `{{pkg}}` becomes the Python package name. Substitution
applies to paths and UTF-8 text contents, while binary contents remain byte-identical.
Executable bits come from the index.

Determinism is the central invariant: traversal is sorted, JSON uses stable key and
indentation settings, and generation contains no timestamps or randomness. A test compares
two complete births byte for byte.

The public `birth` operation validates the destination, resolves and creates the external
data directory, writes the generated files, initializes Git, and warns when Git identity is
not configured. Data-directory creation happens before product files are written, so a
permission failure leaves an empty destination that can be retried safely. The lower-level
`birth_into` function does not touch external data and is safe for temporary regeneration.

The generated `.tool-manifest.json` contains:

- template identity;
- explicit `tool_name`, `pkg`, and `profile` parameters;
- current template-owned glob patterns;
- explanations for child-owned paths.

JSON output is stable. The only implemented profile is `default`; the profile field remains
explicit so a malformed or foreign manifest fails instead of silently selecting defaults.

## Regeneration diff

`diff` reads parameters from the target manifest, regenerates the current skeleton into a
temporary directory, and compares template-owned files byte for byte. Stamping cancels out
because both sides use the same parameters, so the report exposes content drift only.

The ownership boundary comes from `TRACKED_GLOBS` in the current generator, not from the
target's old manifest. A template-owned file added after a child was created therefore
appears as `missing`. Child-owned README, contributor instructions, domain CLI, and local
checks are not treated as template drift.

Statuses are `in-sync`, `drifted`, and `missing`. Exit codes are 0 for no drift, 1 for drift,
and 2 for an operational error. `diff` is intentionally read-only for the target and never
auto-merges.

## Repository check contract

A check is one self-contained executable Python file with no imports from neighboring
checks. Its header contains `# tool-check`, an ID, `observe` or `block` mode, and an optional
rule reference. Its interface is:

```text
<check> --repo-root <path> [--json]
```

Exit 0 means no violations and exit 1 means violations. The check runner discovers baseline
checks beside itself and local checks under the target repository, deduplicates them by ID,
executes each with JSON output, and fails only for violated block checks. The runner itself
has no check header and is not discovered recursively.

The baseline currently covers repository data leakage, required public documentation,
contributor-file size, tracked or nearby secrets, and environment-file ignore rules. Each
check reads the Git index where the future commit is the relevant object. Protocol errors
fail closed.

A green secret check is deliberately narrower than a claim that no secret exists. It checks
sensitive filenames, populated environment samples, known literal credential formats, and
index contents up to the 10 MiB data boundary. Arbitrary values in structured documents and
old Git history require separate review and scanning.

## Generated skeleton

The skeleton provides:

- an `argparse` CLI with exit codes 0 (success), 75 (quota window), 111 (transient failure),
  and 1 (permanent or usage failure);
- a configurable data-home resolver and non-mutating `doctor` command;
- fail-closed parsing of shared TOML configuration;
- atomic writes and a repository-external runtime state directory;
- provider-specific adapters behind a small common interface;
- session capture and hermetic pytest scaffolding;
- contributor, architecture, operations, and testing templates.

Adapter code is vendored into each generated repository, which then owns its copy. Drift is
visible through regeneration; children never import this repository at runtime. Provider
flags must be changed only with direct verification because inherited standard input,
repository checks, resume semantics, and structured errors differ across command-line
clients.

Runtime data resolves in this order: explicit `--home`, tool-specific environment variable,
`$TOOLS_DATA/<tool>-data`, then `~/tools-data/<tool>-data`. The current working directory is
never a data home. This default is portable and configurable rather than tied to a specific
machine.

## Shared configuration

`$TOOLS_DATA/config.toml`, or the same file under the documented default root, is an optional
shared machine contract with schema version 1:

- `[paths]` requires absolute `vault`, `topics_root`, and `sources_root` values; `~` is
  expanded while reading;
- `[harness.claude]` and `[harness.codex]` require non-empty `argv` arrays and may define
  default model or effort names;
- dynamic `[tools.<name>]` tables require `argv` and may define an absolute `cwd` plus a list
  of environment variable names.

The parser rejects unknown keys, wrong types, unsupported schema versions, relative paths,
and environment entries that contain values. A missing file produces an explicit
`CommonConfig(exists=False)` value. An invalid existing file makes `doctor` fail with the
path and schema location but without echoing secret values. Credentials remain exclusively
in the process environment.

The example at `deploy/config.example.toml` is documentation only and is never copied to a
user's data directory automatically.

## Deliberate exclusions

These are return triggers rather than a hidden backlog:

| Excluded feature | Return trigger | Current approach |
|---|---|---|
| Automatic drift merge | The same manual patch repeatedly lands in many children | Report drift and let each child owner apply it |
| Profile overlays and deletes | A second production profile has concrete differences | One explicit `default` profile |
| Shared check library | Non-trivial logic is duplicated in at least three checks | Standalone files with small repeated wrappers |
| Child registry | Per-child diff commands become easy to miss | Address one explicit child at a time |
| Installed baseline checks | A child must run them without access to this repository | Keep the baseline here so one change updates all checks |
