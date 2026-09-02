#!/usr/bin/env python3
# tool-check
# id: repo/data-not-inside
# mode: block
"""Keep runtime data beside a repository through configurable home paths, not inside it.

The check catches root ``in/``, ``out/``, and ``jobs/`` directories plus files larger than
10 MiB among tracked and unignored repository files. It also reads staged blob sizes so a
smaller or removed working copy cannot hide content already prepared for commit.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

CHECK_ID = "repo/data-not-inside"
DATA_DIRS = ("in", "out", "jobs")
MAX_BYTES = 10 * 1024 * 1024


class GitIndexError(RuntimeError):
    """The index could not be inspected completely, so the block check must fail."""


def repo_files(root: Path) -> list[Path]:
    """Return tracked and unignored files, falling back to a non-Git tree walk."""

    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return [root / name for name in proc.stdout.split("\0") if name]
    return [path for path in root.rglob("*") if path.is_file() and ".git" not in path.parts]


def index_blob_sizes(root: Path) -> list[tuple[str, int]] | None:
    """Return indexed blob sizes, or None when the root is not a Git worktree."""

    inside = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    if inside.returncode != 0:
        return None
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "-z"], capture_output=True, text=True)
    if listed.returncode != 0:
        raise GitIndexError("git ls-files failed: " + listed.stderr.strip())

    entries = []
    for entry in listed.stdout.split("\0"):
        if not entry:
            continue
        meta, separator, rel = entry.partition("\t")
        parts = meta.split()
        if not separator or len(parts) != 3:
            raise GitIndexError(f"git ls-files returned an unparseable entry: {entry!r}")
        mode, sha, _stage = parts
        if mode == "160000":
            continue  # a submodule entry points to a commit rather than a data blob
        entries.append((rel, sha))

    shas = sorted({sha for _rel, sha in entries})
    if not shas:
        return []
    checked = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch-check"],
        input="\n".join(shas) + "\n",
        capture_output=True,
        text=True,
    )
    if checked.returncode != 0:
        raise GitIndexError("git cat-file --batch-check failed: " + checked.stderr.strip())
    lines = checked.stdout.splitlines()
    if len(lines) != len(shas):
        raise GitIndexError(
            f"git cat-file --batch-check returned {len(lines)} responses for {len(shas)} requests")
    sizes = {}
    for expected_sha, line in zip(shas, lines):
        parts = line.split()
        try:
            size = int(parts[2])
        except (IndexError, ValueError):
            raise GitIndexError(
                f"git cat-file --batch-check returned an unexpected header: {line!r}") from None
        if len(parts) != 3 or parts[:2] != [expected_sha, "blob"] or size < 0:
            raise GitIndexError(
                f"git cat-file --batch-check returned an unexpected header: {line!r}")
        sizes[expected_sha] = size
    return [(rel, sizes[sha]) for rel, sha in entries]


def run(root: Path) -> list[dict]:
    violations = []
    for name in DATA_DIRS:
        if (root / name).is_dir():
            violations.append({
                "file": name + "/",
                "msg": "data directory at repository root; move it to configurable --home",
            })
    large_paths = set()
    for path in sorted(repo_files(root)):
        try:
            size = path.stat().st_size
        except OSError:
            continue  # broken symlink or concurrent removal is outside this check
        if size > MAX_BYTES:
            rel = str(path.relative_to(root))
            large_paths.add(rel)
            violations.append({
                "file": rel,
                "msg": f"file is {size / 1024 / 1024:.1f} MiB (>10 MiB); large data is external",
            })
    try:
        indexed = index_blob_sizes(root)
    except GitIndexError as error:
        violations.append({
            "file": ".git/index",
            "msg": f"indexed blob sizes were not fully checked: {error}; failing closed",
        })
        indexed = []
    for rel, size in indexed or []:
        if size > MAX_BYTES and rel not in large_paths:
            violations.append({
                "file": rel,
                "msg": f"indexed blob is {size / 1024 / 1024:.1f} MiB (>10 MiB); changing the "
                "working copy does not change the future commit",
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
