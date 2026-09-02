# AGENTS.md - tool-template

Contributor contract for agents and humans changing this repository. `tool-template` is a
deterministic generator and drift detector for self-contained Python tool repositories. It
also owns the generated skeleton and the baseline repository checks used by child tools.

## Repository and data boundaries

`skeleton/` is product content copied into generated repositories. `tooltemplate/` is the
generator and is not copied. `harness/checks/` is the self-hosted baseline applied here and
to child repositories. Children own their generated copies and never import this project
at runtime.

Generated tools keep mutable state and configuration outside their repositories. Data-home
selection and shared machine configuration are described in `README.md` and implemented by
the skeleton. Credentials remain in the process environment; environment samples contain
names and placeholders only. The generator may create a target repository and its external
data directory, but drift inspection must not mutate the target.

## Reading order

1. `README.md` - product behavior, commands, data boundary, limitations, and tests.
2. `docs/DESIGN.md` - Git-index semantics, manifest and drift contracts, check protocol,
   and generated-skeleton design.
3. `tests/` - executable contracts for generation, checks, adapters, configuration, and
   session capture.
4. `skeleton/AGENTS.md` and `skeleton/docs/conventions.md` - guidance shipped to children.

The root file governs work on the template repository. The skeleton file governs a child
after generation. Keep their shared principles aligned, but do not duplicate root-specific
generator mechanics into the child guidance.

## Code map and invariants

- `tooltemplate/core.py` reads the skeleton file set and contents from the Git index,
  stamps parameters, writes stable manifests, creates repositories, and computes drift.
- `tooltemplate/cli.py` owns the birth and diff command contracts.
- `tests/test_generator.py` pins deterministic generation and drift behavior.
- `harness/run_checks.py` discovers standalone checks described by `harness/repo.yaml`.

The generated file set is a pure function of the indexed skeleton and explicit parameters.
Keep traversal sorted, JSON stable, executable bits preserved, and generated content free
of timestamps, randomness, and machine-specific absolute paths. Stage intended skeleton
changes before running birth or diff; unstaged content is deliberately excluded and only
warned about.

## Working rules

1. Before claiming completion, run and quote both repository gates:

   ```bash
   python3 -m pytest -q -p no:cacheprovider
   python3 harness/run_checks.py --repo-root .
   ```

2. Keep pytest and baseline checks hermetic. They must use temporary directories and fake
   external behavior, with no network, real provider credentials, or paid inference.
3. The ownership boundary for drift comes from the current generator's tracked globs, not
   an old child manifest. A new template-owned path must appear as missing in an old child.
4. A new baseline check starts in observe mode. Move it to block only after existing
   violations are removed. Checks remain standalone and must fail closed on protocol errors.
5. Do not change provider CLI flags without direct verification of the client behavior.
6. Keep secrets out of arguments, generated files, manifests, and samples. Configuration
   stores environment variable names and resolves their values only at runtime.

## Contract changes

Contracts include birth and diff arguments and exit codes, stamping rules, manifest schema,
tracked globs, deterministic output, check IDs and modes, check JSON output, and files under
`skeleton/`. A change needs a regression test and the matching `README.md` or
`docs/DESIGN.md` update. A skeleton contract change also needs child-generation acceptance
and an intentional update to `skeleton/AGENTS.md` when contributor guidance changes.

## Style

Use English in source, tests, generated files, and public documentation. Use plain hyphens
and no emoji. Prefer a small explicit change to speculative machinery. Commits should be
meaningful steps with short imperative subjects and no co-author trailers.
