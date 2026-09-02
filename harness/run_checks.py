#!/usr/bin/env python3
"""Discover and run template baseline plus target-local repository checks.

A check is an executable file with a ``# tool-check`` header and a
``--repo-root <path> [--json]`` interface. The baseline lives beside this runner and local
checks live under the target's ``harness/checks`` directory. This file deliberately lacks
the sentinel and is not discovered as a check.

Exit 1 means a block check reported violations or a check failed to return valid output.
Observe-mode violations are printed without failing the run.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

SENTINEL = "# tool-check"
HEADER_KEYS = ("id", "mode", "rule")
MODES = ("observe", "block")


def parse_header(path: Path) -> dict | None:
    """Return check-header metadata, or None when a file is not a check."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()[:20]
    except (OSError, UnicodeDecodeError):
        return None
    meta, in_header = {}, False
    for line in lines:
        stripped = line.strip()
        if stripped == SENTINEL:
            in_header = True
            continue
        if not in_header:
            continue
        if not stripped.startswith("#"):
            break
        key, separator, value = stripped.lstrip("#").strip().partition(":")
        if separator and key.strip() in HEADER_KEYS:
            meta[key.strip()] = value.strip()
        else:
            break
    if not in_header:
        return None
    if "id" not in meta:
        raise ValueError(f"{path}: check header has no id")
    meta.setdefault("mode", "observe")
    if meta["mode"] not in MODES:
        raise ValueError(f"{path}: mode={meta['mode']!r}, expected one of {MODES}")
    return meta


def discover(dirs: list[Path]) -> list[tuple[Path, dict]]:
    """Discover checks in order, deduplicating paths and rejecting duplicate IDs."""

    specs: list[tuple[Path, dict]] = []
    seen_paths: set[Path] = set()
    seen_ids: dict[str, Path] = {}
    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.suffix != ".py" or path.name.startswith(("_", ".")):
                continue
            resolved = path.resolve()
            if resolved in seen_paths:
                continue
            meta = parse_header(path)
            if meta is None:
                continue
            if meta["id"] in seen_ids:
                raise ValueError(
                    f"duplicate check id {meta['id']}: {path} and {seen_ids[meta['id']]}")
            seen_paths.add(resolved)
            seen_ids[meta["id"]] = path
            specs.append((path, meta))
    return specs


def run_check(path: Path, repo_root: Path) -> dict:
    """Run one check with JSON output; malformed stdout is a check error."""

    proc = subprocess.run(
        [sys.executable, str(path), "--repo-root", str(repo_root), "--json"],
        capture_output=True,
        text=True,
    )
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {
            "id": path.stem,
            "ok": False,
            "violations": [],
            "error": f"check returned no JSON (rc={proc.returncode}): {proc.stderr.strip()[:300]}",
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="run baseline and local repository checks")
    parser.add_argument("--repo-root", required=True, help="repository root to inspect")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()

    baseline_dir = Path(__file__).resolve().parent / "checks"
    specs = discover([baseline_dir, repo_root / "harness" / "checks"])
    if not specs:
        print("no checks found")
        return 1

    exit_code = 0
    for path, meta in specs:
        payload = run_check(path, repo_root)
        violations = payload.get("violations", [])
        error = payload.get("error", "")
        if error:
            status = "ERROR"
        elif payload.get("ok"):
            status = "ok"
        else:
            status = f"{len(violations)} violation(s)" + (
                "" if meta["mode"] == "block" else " (observe)")
        print(f"  {meta['id']:<24} [{meta['mode']:>7}]  {status}")
        if error:
            print(f"      {error}")
        for violation in violations:
            location = f"{violation['file']}: " if violation.get("file") else ""
            print(f"      {location}{violation['msg']}")
        if error or (violations and meta["mode"] == "block"):
            exit_code = 1

    print(f"summary: {len(specs)} checks, exit {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
