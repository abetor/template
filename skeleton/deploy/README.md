# Deployment templates

Put launchd or systemd unit templates here with installation-time placeholders instead of
machine-specific absolute paths. Runtime data defaults to
`${TOOLS_DATA:-$HOME/tools-data}/{{data_dir}}`; set `{{data_env}}` or pass `--home` to choose
another location. Shared `config.toml` lives at the `TOOLS_DATA` root, while credential
values remain in the process environment.

A launchd unit must provide an explicit PATH containing `nvm-bin` when `codex` is installed
there, plus Python 3.11+ with `tomllib`. launchd's minimal PATH does not see nvm, and Apple
Python 3.9 is insufficient.
