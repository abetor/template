# VISION - {{tool_name}}

After birth, explain why the tool exists, the problem it solves, the target scenario in the
form "a user does X and the tool produces Y", and deliberate non-goals.

Inherited properties:

1. Self-contained: cloning this repository is enough; there are no imports from siblings.
2. Provider-agnostic: artifact contracts stay stable while adapters may vary.
3. Keyless by default: paid services are optional configuration, not a requirement.
4. Data beside the repository: configurable through `--home`, `{{data_env}}`, or
   `TOOLS_DATA`, with `~/tools-data/{{data_dir}}` as the documented final fallback.
5. Shareable: a new contributor can install and use the repository without private context.
