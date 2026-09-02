"""{{tool_name}} CLI, subcommands, and shared exit-code contract.

Data defaults to ``$TOOLS_DATA/{{data_dir}}`` or ``~/tools-data/{{data_dir}}``.
``{{data_env}}`` overrides that root, and ``--home`` overrides everything. The current
working directory is never a data default, so running from the repository cannot silently
turn it into data storage. Add each capability under ``ext/`` and register its command here;
keep this core thin.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .shared.cliargs import ArgumentParser
from .shared.config import CommonConfigError, load_common_config, tools_data_root

# Shared tool exit contract. External supervisors classify these values. There is no exit 2:
# configuration and usage errors are EXIT_FAIL=1, with details on stderr. The custom argument
# parser also exits 1 for invalid usage instead of argparse's default 2.
EXIT_OK = 0
EXIT_QUOTA = 75       # EX_TEMPFAIL: wait for the subscription or quota window
EXIT_TRANSIENT = 111  # retryable network, service, or other temporary failure
EXIT_FAIL = 1         # permanent failure, including configuration and usage errors

# Environment variable names documented by .env.sample. Doctor reports presence only and
# never prints credential values.
SECRET_HINTS: tuple[str, ...] = ()
DATA_ENV = "{{data_env}}"
DATA_DIR = "{{data_dir}}"


def resolve_home(cli_home: str | None = None) -> Path:
    """Resolve explicit CLI, tool environment, shared root, then documented fallback."""

    raw = cli_home or os.environ.get(DATA_ENV)
    return Path(raw).expanduser() if raw else tools_data_root() / DATA_DIR


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(
        # After birth, replace this description with one sentence about the tool.
        prog="{{tool_name}}",
        description="New tool scaffold: domain description has not been provided",
    )
    parser.add_argument(
        "--home",
        help="tool data directory; overrides " + DATA_ENV
        + " and the default ~/tools-data/" + DATA_DIR,
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    subparsers.add_parser("doctor", help="inspect the environment and data home without mutation")
    # Register new commands here and implement them under ext/<feature>/.

    args = parser.parse_args(argv)
    home = resolve_home(args.home)
    if args.cmd == "doctor":
        return doctor(home)
    return EXIT_FAIL  # unreachable with required=True; guards against branch drift


def doctor(home: Path) -> int:
    """Report missing dependencies and configuration without writing or creating anything.

    A human installs missing components. Credential checks expose Boolean presence only,
    never values.
    """

    problems: list[str] = []
    tools = {name: shutil.which(name) is not None for name in ("git", "python3")}
    problems += ["missing executable " + name for name, ok in tools.items() if not ok]
    if not home.is_dir():
        problems.append("missing data directory " + str(home) + " (create it with mkdir -p)")
    elif not os.access(home, os.W_OK):
        problems.append("data directory is not writable: " + str(home))

    common_path = tools_data_root() / "config.toml"
    common_exists = common_path.exists()
    common_error = False
    try:
        common = load_common_config()
        common_valid = True if common.exists else None
    except CommonConfigError as error:
        common_valid = False
        common_error = True
        problems.append("shared configuration is invalid: " + str(error))

    print("{{tool_name}} doctor: " + ("READY" if not problems else "NOT READY"))
    print("  tools: " + ", ".join(
        name + "=" + ("present" if ok else "MISSING") for name, ok in tools.items()))
    print("  home: " + str(home) + ("" if home.is_dir() else " (absent)"))
    print("  shared config: path=" + str(common_path)
          + " exists=" + str(common_exists).lower()
          + " valid=" + ("-" if common_valid is None else str(common_valid).lower())
          + " error=" + str(common_error).lower())
    if SECRET_HINTS:
        print("  credentials (environment presence only): " + ", ".join(
            name + "=" + ("present" if os.environ.get(name) else "absent")
            for name in SECRET_HINTS))
    for problem in problems:
        print("  problem: " + problem)
    return EXIT_OK if not problems else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
