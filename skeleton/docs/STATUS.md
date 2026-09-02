# STATUS - {{tool_name}}

New scaffold created from `tool-template`. Replace this line with a date and an evidence-
based status maintained by the repository owner.

## Working and verified

- `python3 -m {{pkg}} doctor` resolves `$TOOLS_DATA`, the documented default,
  `{{data_env}}`, and explicit `--home`. It reports shared configuration status without
  printing contents. Verified by `tests/test_smoke.py`.

## Not working or not verified

- Domain behavior does not exist yet. Adapters under `shared/` are reusable scaffolding and
  have not made live provider calls from this new repository.

## Next step

- Define `docs/VISION.md`, then implement and test the first domain subcommand described in
  `docs/tasks.md`.
