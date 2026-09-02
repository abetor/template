# DESIGN - {{tool_name}}

After birth, describe the domain architecture, boundaries, contracts, major decisions, and
their reasons here.

Until domain code exists, only the generated scaffold is defined:

- `{{pkg}}/cli.py` is the command entry point; `doctor` performs diagnostics without
  mutation.
- Data uses `$TOOLS_DATA` or the documented default `~/tools-data`. `{{data_env}}` and then
  explicit `--home` override `<root>/{{data_dir}}`; the current working directory is never a
  data path. `shared/config.py` reads `<root>/config.toml` fail-closed.
- `{{pkg}}/shared/` is locally owned vendored code for adapters, filesystem operations,
  configuration, and session capture.
- `{{pkg}}/ext/` isolates extensions from the core.
- Exit codes 0, 75, 111, and 1 mean success, quota, transient failure, and permanent or
  usage failure respectively.
