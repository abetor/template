"""Command-line interface for deterministic birth and regeneration diff.

Usage::

    python3 -m tooltemplate birth --name tool-x --into ../tool-x [--profile default] [--pkg pkg_x]
    python3 -m tooltemplate diff --target ../tool-x

Diff exits 0 for no drift, 1 for detected drift, and 2 for an operational error. Consumers
can therefore distinguish a failed comparison from a successful comparison that found
differences.
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

from . import core


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tooltemplate",
        description="create tool repositories from skeleton/ and detect drift by regeneration",
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    birth_parser = subparsers.add_parser(
        "birth", help="create a new tool repository from the skeleton")
    birth_parser.add_argument(
        "--name",
        required=True,
        help="kebab-case tool name; the default package replaces hyphens with underscores",
    )
    birth_parser.add_argument("--into", required=True, help="new repository destination")
    birth_parser.add_argument(
        "--pkg",
        default=None,
        help="explicit Python package name when it cannot be derived from --name",
    )
    birth_parser.add_argument(
        "--profile",
        default="default",
        help="birth profile: " + " | ".join(sorted(core.PROFILES)),
    )

    diff_parser = subparsers.add_parser(
        "diff", help="detect drift in template-owned child files by regeneration")
    diff_parser.add_argument(
        "--target", required=True, help="generated repository containing .tool-manifest.json")

    args = parser.parse_args(argv)
    if args.cmd == "birth":
        return run_birth(args.name, args.into, args.profile, args.pkg)
    return run_diff(args.target)


def run_birth(name: str, into_arg: str, profile: str, pkg: str | None = None) -> int:
    into = Path(into_arg).expanduser()
    try:
        params = core.make_params(name, profile, pkg)
        root = core.template_root()
        # Validate before the external mkdir. An unsafe target must not create a data home;
        # a data-home failure must leave a retryable empty destination without files or Git.
        core.ensure_safe_target(into)
        data_home = ensure_data_home(params)
        count = core.birth_into(params, into, root)
        ensure_git_repo(into)
    except core.ToolTemplateError as error:
        print(f"tooltemplate birth: {error}", file=sys.stderr)
        return 1
    print(
        f"created {params.tool_name} (package {params.pkg}, profile {params.profile}) "
        f"at {into}: {count} files plus {core.MANIFEST_NAME}")
    print(f"  data: {data_home}")
    warn_unstaged_skeleton(root)
    warn_missing_git_identity(into)
    print(f"verify: cd {into} && python3 -m pytest -q")
    return 0


def ensure_git_repo(into: Path) -> None:
    """Initialize each child repository idempotently at birth."""

    if (into / ".git").exists():
        return
    proc = subprocess.run(
        ["git", "-C", str(into), "init", "--quiet"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise core.ToolTemplateError("git init failed: " + proc.stderr.strip())


def ensure_data_home(params: core.Params) -> Path:
    """Create the configured canonical data home without modifying existing data."""

    raw_root = os.environ.get("TOOLS_DATA")
    data_root = Path(raw_root).expanduser() if raw_root else Path.home() / "tools-data"
    path = data_root / params.data_dir
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise core.ToolTemplateError(f"cannot create data directory {path}: {error}") from error
    return path


def warn_missing_git_identity(into: Path) -> None:
    """Report missing identity without failing birth.

    Git refuses the first child commit when ``user.name`` or ``user.email`` is absent. The
    warning provides both global and repository-local commands because identity may be
    intentionally scoped. Complete copyable commands are more useful than naming settings.
    """

    missing = [key for key in ("user.name", "user.email") if not _git_config(into, key)]
    if missing:
        repo = shlex.quote(str(into))
        print(
            "  warning: Git identity is not configured (" + ", ".join(missing)
            + " unresolved); Git will refuse the first commit. Configure globally:\n"
            '      git config --global user.name "First Last"\n'
            '      git config --global user.email "you@example.com"\n'
            "    or only in this repository:\n"
            f'      git -C {repo} config user.name "First Last"\n'
            f'      git -C {repo} config user.email "you@example.com"')


def warn_unstaged_skeleton(root: Path) -> None:
    """Report skeleton changes excluded from the index snapshot.

    Both birth and diff use indexed contents, so a working-tree edit without ``git add``
    affects neither a child nor regeneration. The condition intentionally includes untracked
    files, hence the precise phrase "changes outside the index".
    """

    proc = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--", "skeleton"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return
    dirty = [line[3:] for line in proc.stdout.splitlines() if line[1:2] != " "]
    if dirty:
        print(
            f"  warning: skeleton/ has changes outside the index ({len(dirty)}); they were "
            f"excluded from the indexed snapshot: {', '.join(sorted(dirty)[:3])}"
            + (" ..." if len(dirty) > 3 else "")
            + "; run git add to include them")


def _git_config(into: Path, key: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(into), "config", "--get", key], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def run_diff(target_arg: str) -> int:
    target = Path(target_arg).expanduser()
    try:
        result = core.compute_diff(target)
    except core.ToolTemplateError as error:
        print(f"tooltemplate diff: {error}", file=sys.stderr)
        return 2
    warn_unstaged_skeleton(core.template_root())
    bad = [(rel, status) for rel, status in result if status != core.IN_SYNC]
    for rel, status in bad:
        print(f"  {status:<30} {rel}")
    if bad:
        print(
            f"regen-diff {target}: DRIFT - {len(bad)} file(s) differ, "
            f"{len(result) - len(bad)} in sync")
        return 1
    print(f"regen-diff {target}: in sync ({len(result)} tracked files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
