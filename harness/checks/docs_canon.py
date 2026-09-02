#!/usr/bin/env python3
# tool-check
# id: repo/docs-canon
# mode: block
"""Require the minimal public documentation set: README, DESIGN, and LICENSE.

Generated projects may keep additional internal workflow documents, but a public repository
must explain what it does, why it is designed that way, and how it is licensed. A whitespace-
only file is treated as absent.
"""

import argparse
import json
import sys
from pathlib import Path

CHECK_ID = "repo/docs-canon"
CANON = ("README.md", "docs/DESIGN.md", "LICENSE")


def run(root: Path) -> list[dict]:
    violations = []
    for rel in CANON:
        path = root / rel
        if not path.is_file():
            violations.append({"file": rel, "msg": "required public document is absent"})
        elif not path.read_text(encoding="utf-8", errors="replace").strip():
            violations.append({"file": rel, "msg": "required public document is empty"})
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
