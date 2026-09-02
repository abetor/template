#!/usr/bin/env python3
# tool-check
# id: repo/agents-size
# mode: block
"""Keep an optional public AGENTS.md contributor contract at or below 6,000 characters.

Public repositories may omit AGENTS.md. When present, it is a concise contributor contract,
not a journal or duplicate of design documentation. Growth beyond the limit is a signal to
move rationale into docs and retain links here.
"""

import argparse
import json
import sys
from pathlib import Path

CHECK_ID = "repo/agents-size"
MAX_CHARS = 6000


def run(root: Path) -> list[dict]:
    path = root / "AGENTS.md"
    if not path.exists():
        return []
    if not path.is_file():
        return [{"file": "AGENTS.md", "msg": "AGENTS.md exists but is not a regular file"}]
    size = len(path.read_text(encoding="utf-8", errors="replace"))
    if size > MAX_CHARS:
        return [{
            "file": "AGENTS.md",
            "msg": f"{size} characters exceeds {MAX_CHARS}; move prose to docs and keep links",
        }]
    return []


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
