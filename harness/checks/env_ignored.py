#!/usr/bin/env python3
# tool-check
# id: repo/env-ignored
# mode: block
"""Require real .env files to be ignored and environment samples to remain trackable.

The companion secret check detects an existing sensitive file. This check catches the loaded
condition where the next ``git add -A`` would include a newly created .env. Conversely,
``.env.sample`` and ``.env.example`` are documentation and must not disappear under a broad
``.env.*`` rule.

The check inspects ignore rules only. It requires the portable rule to come from the root
``.gitignore`` rather than a global excludes file or ``.git/info/exclude``. Git errors and
malformed verbose output fail closed.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

CHECK_ID = "repo/env-ignored"
MUST_IGNORE = (".env", ".env.local")
MUST_NOT_IGNORE = (".env.sample", ".env.example")


def ignore_result(root: Path, rel: str) -> tuple[bool | None, str | None, str | None]:
    """Return ``(ignored, rule source, error)`` from Git's verbose NUL protocol.

    ``--no-index`` prevents a staged file from hiding a missing rule. Returning the source
    ensures a machine-local ignore file cannot masquerade as repository protection.
    """

    proc = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--no-index", "--verbose", "--stdin", "-z"],
        input=rel + "\0",
        capture_output=True,
        text=True,
    )
    if proc.returncode == 1 and not proc.stdout:
        return False, None, None
    if proc.returncode != 0:
        detail = proc.stderr.strip() or f"exit {proc.returncode}"
        return None, None, f"git check-ignore failed: {detail}"
    fields = proc.stdout.split("\0")
    if not fields or fields[-1] != "" or len(fields[:-1]) != 4:
        return None, None, f"git check-ignore returned unexpected verbose output {proc.stdout!r}"
    source, _line, pattern, path = fields[:-1]
    if path != rel:
        return None, None, f"git check-ignore returned {path!r}, expected {rel!r}"
    ignored = not pattern.startswith("!")
    source_path = Path(source)
    if not source_path.is_absolute():
        source_path = root / source_path
    repo_ignore = root / ".gitignore"
    portable_source = ".gitignore" if source_path.resolve() == repo_ignore.resolve() else source
    return ignored, portable_source, None


def run(root: Path) -> list[dict]:
    violations = []
    for rel in MUST_IGNORE:
        ignored, source, error = ignore_result(root, rel)
        if error:
            violations.append({
                "file": ".gitignore", "msg": f"{rel}: {error}; failing closed"})
        elif ignored is False:
            violations.append({
                "file": ".gitignore",
                "msg": f"{rel} is not ignored; add .env and .env.* before a future git add -A",
            })
        elif source != ".gitignore":
            violations.append({
                "file": ".gitignore",
                "msg": f"{rel} is ignored by {source}, not the repository .gitignore; the rule "
                "will not survive clone",
            })
    for rel in MUST_NOT_IGNORE:
        ignored, source, error = ignore_result(root, rel)
        if error:
            violations.append({
                "file": ".gitignore", "msg": f"{rel}: {error}; failing closed"})
        elif ignored is True:
            violations.append({
                "file": ".gitignore",
                "msg": f"{rel} is ignored even though it is documentation; add !{rel}",
            })
        elif source not in (None, ".gitignore"):
            violations.append({
                "file": ".gitignore",
                "msg": f"{rel} is included only through {source}, not the repository .gitignore; "
                "the result will not survive clone",
            })
    return violations


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog=CHECK_ID, description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    violations = run(Path(args.repo_root).resolve())
    if args.json:
        print(json.dumps({"id": CHECK_ID, "ok": not violations, "violations": violations}))
    elif violations:
        print(f"{CHECK_ID}: {len(violations)} violation(s)")
        for violation in violations:
            print(f"  {violation['file']}: {violation['msg']}")
    else:
        print(f"{CHECK_ID}: OK")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
