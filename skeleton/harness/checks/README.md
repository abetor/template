# Local checks for {{tool_name}}

A check is one self-contained executable Python file with no imports from neighboring
checks:

- header: `# tool-check`, `# id: {{tool_name}}/<name>`, `# mode: observe|block`, and an
  optional `# rule: <reference>`;
- CLI: `--repo-root <path> [--json]`; exit 0 means clean and exit 1 means violations;
- lifecycle: begin in `observe`, remove existing violations, then switch to `block`.

Baseline checks live in `tool-template/harness/checks/`. Run baseline and local checks with
`python3 ../tool-template/harness/run_checks.py --repo-root .`. Any baseline check is a code
example.
