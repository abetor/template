#!/usr/bin/env python3
# tool-check
# id: repo/secrets-not-tracked
# mode: block
"""Block known secrets in the Git index and nearby unignored storage files.

The check detects four high-signal conditions:

1. a tracked secret-storage filename such as .env, a private-key container, cookies, or
   credentials;
2. a known provider credential or private-key header in indexed text, plus a distinct scan
   of a divergent working copy;
3. a populated value in `.env.sample` or `.env.example`;
4. an untracked secret-storage file that is not ignored and is one ``git add -A`` from a
   commit.

Indexed blobs are authoritative because the future commit may still contain a value removed
only from disk. The scope is the index and working tree, never Git history. Historical review
and a separate history scan remain publication requirements.
"""

import argparse
import json
import re
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

CHECK_ID = "repo/secrets-not-tracked"

# A storage filename is itself sufficient evidence. PEM is the exception because public-key
# and certificate files are legitimate; a private header decides their result.
SECRET_FILE_GLOBS = (
    ".env", ".env.*", "*.key", "*.p12", "*.pfx",
    "id_rsa*", "id_ed25519*", ".netrc", "cookies.txt", "cookies.json",
    "credentials.json", "client_secret*.json",
)
SAMPLE_NAMES = (".env.sample", ".env.example")

# Patterns are intentionally high-signal and assembled so the scanner source does not match
# itself. Human review covers arbitrary values outside these recognizable formats.
_PRIVATE_PEM = re.compile(r"-----BEGIN [A-Z ]{0,20}PRIVATE KEY-----")
SECRET_PATTERNS = (
    ("OpenAI/Anthropic-style key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("GitHub token", re.compile(
        r"\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("AWS key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Telegram bot token", re.compile(r"\b[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}")),
    ("private PEM key", _PRIVATE_PEM),
)

# The scan boundary matches repo/data-not-inside. Larger blobs are blocked there, leaving no
# unscanned size gap between checks. Batch chunks cap peak memory.
MAX_SCAN_BYTES = 10 * 1024 * 1024
BATCH_BYTES = 32 * 1024 * 1024
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
_TEXT_MODES = ("100644", "100755")
_INDEX, _WORKTREE = "index", "working tree"


class CatFileProtocolError(RuntimeError):
    """Git cat-file did not prove complete indexed-blob reading."""


def _git(root: Path, *args: str) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), *args, "-z"], capture_output=True, text=True)
    return [name for name in proc.stdout.split("\0") if name] if proc.returncode == 0 else []


def index_entries(root: Path) -> list[tuple[str, str]]:
    """Return sorted unique ``(relative path, blob id)`` pairs from the index.

    All unmerged stages are included because scanning more versions is safer; a human will
    eventually choose one stage when resolving the conflict.
    """

    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "-z"], capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    out = set()
    for entry in proc.stdout.split("\0"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        parts = meta.split()
        if len(parts) >= 2 and parts[0] in _TEXT_MODES:
            out.add((path, parts[1]))
    return sorted(out)


def blob_texts(root: Path, shas: list[str]) -> dict[str, str]:
    """Read eligible indexed text after validating each blob type and size."""

    if not shas:
        return {}
    checked = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch-check"],
        input="\n".join(shas) + "\n",
        capture_output=True,
        text=True,
    )
    if checked.returncode != 0:
        raise CatFileProtocolError("git cat-file --batch-check failed: " + checked.stderr.strip())
    lines = checked.stdout.splitlines()
    if len(lines) != len(shas):
        raise CatFileProtocolError(
            f"git cat-file --batch-check returned {len(lines)} responses for {len(shas)} requests")
    out, chunk, chunk_bytes = {}, [], 0
    for expected_sha, line in zip(shas, lines):
        parts = line.split()
        try:
            size = int(parts[2])
        except (IndexError, ValueError):
            raise CatFileProtocolError(
                f"git cat-file --batch-check returned an unexpected header: {line!r}") from None
        if len(parts) != 3 or parts[0] != expected_sha or parts[1] != "blob" or size < 0:
            raise CatFileProtocolError(
                f"git cat-file --batch-check returned an unexpected header: {line!r}")
        if size > MAX_SCAN_BYTES:
            continue
        chunk.append(expected_sha)
        chunk_bytes += size
        if chunk_bytes >= BATCH_BYTES:
            out.update(_cat_batch(root, chunk))
            chunk, chunk_bytes = [], 0
    if chunk:
        out.update(_cat_batch(root, chunk))
    return out


def _cat_batch(root: Path, shas: list[str]) -> dict[str, str]:
    """Read one cat-file batch and return UTF-8 text by blob ID, skipping binary blobs."""

    proc = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input="\n".join(shas).encode() + b"\n",
        capture_output=True,
    )
    if proc.returncode != 0:
        raise CatFileProtocolError(
            "git cat-file --batch failed: "
            + proc.stderr.decode("utf-8", "replace").strip())
    data, pos, out = proc.stdout, 0, {}
    for expected_sha in shas:
        newline = data.find(b"\n", pos)
        if newline < 0:
            raise CatFileProtocolError("git cat-file --batch returned a truncated header")
        header_raw = data[pos:newline]
        try:
            header = header_raw.decode("ascii").split()
            size = int(header[2])
        except (UnicodeDecodeError, IndexError, ValueError):
            raise CatFileProtocolError(
                f"git cat-file --batch returned an unexpected header: {header_raw!r}") from None
        if (len(header) != 3 or header[0] != expected_sha
                or header[1] != "blob" or size < 0):
            raise CatFileProtocolError(
                f"git cat-file --batch returned an unexpected header: {header_raw!r}")
        start, end = newline + 1, newline + 1 + size
        if end >= len(data) or data[end:end + 1] != b"\n":
            raise CatFileProtocolError(
                f"git cat-file --batch returned truncated blob {expected_sha} of size {size}")
        raw = data[start:end]
        pos = end + 1
        try:
            out[expected_sha] = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
    if pos != len(data):
        raise CatFileProtocolError(
            f"git cat-file --batch returned {len(data) - pos} extra bytes after responses")
    return out


def worktree_text(path: Path) -> str | None:
    """Return a small UTF-8 working-tree file, or None for absent, binary, or large data."""

    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def is_secret_name(rel: str) -> bool:
    name = Path(rel).name
    if name in SAMPLE_NAMES:
        return False
    lower = name.lower()
    return any(fnmatch(lower, glob) for glob in SECRET_FILE_GLOBS)


def is_pem_key_name(rel: str) -> bool:
    """A PEM key-like filename requires content inspection but is not a violation alone."""

    return fnmatch(Path(rel).name.lower(), "*key*.pem")


def _variants(root: Path, rel: str, index_texts: list[str]) -> list[tuple[str, str]]:
    """Return indexed contents plus a working copy only when it differs."""

    out = [(_INDEX, text) for text in index_texts]
    working = worktree_text(root / rel)
    if working is not None and all(working != text for _, text in out):
        out.append((_WORKTREE, working))
    return out


def run(root: Path) -> list[dict]:
    violations = []
    entries = index_entries(root)
    tracked = sorted({rel for rel, _sha in entries})
    untracked = _git(root, "ls-files", "--others", "--exclude-standard")

    for rel in tracked:
        if is_secret_name(rel):
            violations.append({
                "file": rel,
                "msg": "secret-storage file is tracked; remove it from the index, ignore the "
                "name, and rotate the value",
            })
    for rel in sorted(untracked):
        if is_secret_name(rel):
            violations.append({
                "file": rel,
                "msg": "secret-storage file is untracked but not ignored; it is one git add -A "
                "from exposure",
            })
        elif is_pem_key_name(rel):
            text = worktree_text(root / rel)
            if text is not None and _PRIVATE_PEM.search(text):
                violations.append({
                    "file": rel,
                    "msg": "private PEM key is untracked but not ignored; it is one git add -A "
                    "from exposure",
                })

    try:
        texts = blob_texts(root, sorted({sha for _rel, sha in entries}))
    except CatFileProtocolError as error:
        violations.append({
            "file": ".git/index",
            "msg": f"index was not scanned completely: {error}; failing closed",
        })
        texts = {}
    by_rel: dict[str, list[str]] = {}
    for rel, sha in entries:
        if sha in texts:
            by_rel.setdefault(rel, []).append(texts[sha])

    for rel in tracked:
        variants = _variants(root, rel, by_rel.get(rel, []))
        for label, pattern in SECRET_PATTERNS:
            for source, text in variants:
                match = pattern.search(text)
                if match:
                    violations.append({
                        "file": rel,
                        "msg": f"looks like {label} ({match.group(0)[:4]}...), source: {source}; "
                        "resolve secrets from the runtime environment and store names only",
                    })
                    break

    for name in SAMPLE_NAMES:
        variants = _variants(root, name, by_rel.get(name, []))
        for source, text in variants:
            for line_number, line in enumerate(text.splitlines(), 1):
                match = _ENV_LINE.match(line)
                if match and match.group(2).split("#")[0].strip():
                    violations.append({
                        "file": name,
                        "msg": f"line {line_number} ({source}): {match.group(1)} contains a value; "
                        "samples document NAME= and purpose, not configuration",
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
