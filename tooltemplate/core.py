"""Generator core: indexed skeleton snapshot, stamping, birth, manifest, and regen-diff.

Birth is a pure function of an indexed ``skeleton/`` snapshot and parameters. Traversal is
sorted, JSON is stable, and output contains no timestamps, randomness, or absolute paths.
The index supplies file names, contents through ``git cat-file``, and executable bits; the
template working tree does not affect generation.

Determinism makes regeneration diff meaningful. Regenerating with identical parameters
causes parameter stamping in the temporary and target trees to cancel byte for byte, leaving
only actual content drift.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

MANIFEST_NAME = ".tool-manifest.json"
TEMPLATE_NAME = "tool-template"
PH_NAME = "{{tool_name}}"
PH_PKG = "{{pkg}}"
PH_DATA_DIR = "{{data_dir}}"
PH_DATA_ENV = "{{data_env}}"

# Entries allowed in an otherwise empty destination. Anything else stops birth: refusing is
# safer than overwriting an unexpected user file.
SAFE_EXISTING = {".git", ".idea", ".DS_Store"}

# Birth profiles map a profile name to skeleton-relative globs that it excludes. A second
# profile should be added only for a demonstrated class of children.
PROFILES: dict[str, list[str]] = {"default": []}

# Regeneration owns mechanics rather than child-specific content. Globs use child paths and
# {{pkg}} is stamped while the manifest is written. This current list, rather than the old
# target manifest, defines the boundary so newly added platform files appear as missing.
TRACKED_GLOBS = [
    "{{pkg}}/shared/**",
    "docs/conventions.md",
    "tests/conftest.py",
]

# Manifest documentation for child-owned paths. Keys are comma-separated child globs and
# <pkg> is a package-name placeholder. A completeness test ensures every generated file is
# covered either here or by TRACKED_GLOBS.
NOT_TRACKED_RATIONALE = {
    "README.md, AGENTS.md, CLAUDE.md, LICENSE, docs/*":
        "repository-specific content is owned by the child; docs/conventions.md is the "
        "separately tracked exception",
    "<pkg>/cli.py, <pkg>/__init__.py, <pkg>/__main__.py, <pkg>/ext/*, "
    "tests/test_smoke.py, tests/_helpers.py":
        "domain starting points that evolve independently in the child",
    "harness/*": "child repository identity and local checks; baseline checks live in the "
        "template",
    "smoke/*, deploy/*, .env.sample": "child-owned live artifacts and deployment guidance",
    ".gitignore, pyproject.toml": "repository infrastructure extended for child-specific "
        "dependencies and ignore rules; byte-level template sync is not useful",
    ".tool-manifest.json": "birth manifest written by the generator and read by diff; edit "
        "only when intentionally changing parameters such as a legacy package name",
}

_NAME_RE = re.compile(r"[a-z][a-z0-9-]*")
_PKG_RE = re.compile(r"[a-z][a-z0-9_]*")
_SKIP_PARTS = {".git", "__pycache__", ".pytest_cache"}

IN_SYNC = "in-sync"
DRIFTED = "drifted"
MISSING = "missing"


class ToolTemplateError(RuntimeError):
    """Operational generator error: birth exits 1 and diff exits 2."""


@dataclass(frozen=True)
class Params:
    """Pure birth input: one parameter set and snapshot produce one byte-identical tree."""

    tool_name: str  # kebab-case form stamped into names and prose
    pkg: str        # underscore form stamped into Python package names and paths
    profile: str

    @property
    def data_name(self) -> str:
        """Tool name used for data; the repository's ``tool-`` prefix is not repeated."""

        return self.tool_name.removeprefix("tool-")

    @property
    def data_dir(self) -> str:
        return self.data_name + "-data"

    @property
    def data_env(self) -> str:
        return self.data_name.replace("-", "_").upper() + "_DATA"


def make_params(tool_name: str, profile: str = "default", pkg: str | None = None) -> Params:
    """Validate and construct stamping parameters.

    By default, the Python package name is derived by replacing hyphens with underscores.
    ``--pkg`` supports repositories whose established import name differs from that rule.
    """

    if not _NAME_RE.fullmatch(tool_name):
        raise ToolTemplateError(
            f"--name {tool_name!r} is not kebab-case; expected {_NAME_RE.pattern}")
    if profile not in PROFILES:
        raise ToolTemplateError(f"unknown profile {profile!r}; available: {sorted(PROFILES)}")
    if pkg is None:
        pkg = tool_name.replace("-", "_")
    elif not _PKG_RE.fullmatch(pkg):
        raise ToolTemplateError(
            f"--pkg {pkg!r} is not a Python package name; expected {_PKG_RE.pattern}")
    return Params(tool_name=tool_name, pkg=pkg, profile=profile)


def template_root() -> Path:
    """Resolve the template repository from the package location, independent of cwd."""

    root = Path(__file__).resolve().parent.parent
    if not (root / "skeleton").is_dir():
        raise ToolTemplateError(f"skeleton/ not found beside the package: {root}")
    return root


def skeleton_files(root: Path) -> list[str]:
    """Return sorted skeleton-relative file paths from the Git index."""

    return [rel for rel, _mode, _sha in skeleton_entries(root)]


def skeleton_entries(root: Path) -> list[tuple[str, str, str]]:
    """Return sorted ``(relative path, mode, blob id)`` tuples from the Git index.

    This intentionally uses ``git ls-files`` rather than walking the disk. Both executable
    modes and blob IDs come from the future commit, so working-tree edits cannot leak into a
    generated repository.
    """

    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "-z", "--", "skeleton"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ToolTemplateError("git ls-files failed: " + proc.stderr.strip())
    return parse_index_entries(proc.stdout)


def parse_index_entries(ls_files_out: str) -> list[tuple[str, str, str]]:
    """Parse ``git ls-files -s -z`` output and enforce pre-write index guards.

    A non-zero stage is an unresolved merge whose stages could otherwise overwrite each
    other according to incidental ordering. Duplicate relative paths are also rejected even
    though a normal stage-zero Git index cannot contain them. Both guards run before any
    destination write.
    """

    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for entry in ls_files_out.split("\0"):
        if not entry:
            continue
        meta, _, path = entry.partition("\t")
        parts = meta.split()
        if len(parts) < 3:
            raise ToolTemplateError(f"git ls-files -s returned an unparseable entry: {entry!r}")
        mode, sha, stage = parts[0], parts[1], parts[2]
        if stage != "0":
            raise ToolTemplateError(
                f"{path}: index stage {stage} is an unresolved merge; resolve it and run "
                "git add before birth")
        if mode not in ("100644", "100755"):
            raise ToolTemplateError(
                f"{path}: unsupported index mode {mode}; the skeleton accepts regular "
                "files only, not symlinks or submodules")
        rel = path[len("skeleton/"):]
        if rel in seen:
            raise ToolTemplateError(
                f"{path}: duplicate relative path in index; refusing before destination write")
        seen.add(rel)
        out.append((rel, mode, sha))
    if not out:
        raise ToolTemplateError("skeleton/ is empty in the Git index; were its files added?")
    return sorted(out)


def index_blobs(root: Path, shas: list[str]) -> dict[str, bytes]:
    """Read all indexed blob contents through one ``git cat-file --batch`` process.

    Content comes from the index rather than the working tree. Otherwise an unstaged edit
    could enter a child and regeneration could compare against an unreproducible draft.
    """

    if not shas:
        return {}
    proc = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input="\n".join(shas).encode() + b"\n",
        capture_output=True,
    )
    if proc.returncode != 0:
        raise ToolTemplateError(
            "git cat-file failed: " + proc.stderr.decode("utf-8", "replace").strip())
    data, pos, out = proc.stdout, 0, {}
    for sha in shas:
        nl = data.find(b"\n", pos)
        header = data[pos:nl].decode("utf-8", "replace") if nl >= 0 else ""
        parts = header.split()
        if len(parts) != 3 or parts[1] != "blob":
            raise ToolTemplateError(f"git cat-file returned an unexpected header: {header!r}")
        start = nl + 1
        out[sha] = data[start:start + int(parts[2])]
        pos = start + int(parts[2]) + 1  # trailing newline after the blob body
    return out


def stamp(text: str, p: Params) -> str:
    """Stamp non-overlapping placeholders as a pure function."""

    return (
        text.replace(PH_NAME, p.tool_name)
        .replace(PH_PKG, p.pkg)
        .replace(PH_DATA_DIR, p.data_dir)
        .replace(PH_DATA_ENV, p.data_env)
    )


def _match(rel: str, glob: str) -> bool:
    """Match a relative path; a ``prefix/**`` pattern includes everything below it."""

    if glob.endswith("/**"):
        return rel.startswith(glob[:-2])
    return fnmatch(rel, glob)


def ensure_safe_target(into: Path) -> None:
    """Create or validate a destination without overwriting unexpected contents."""

    if not into.exists():
        into.mkdir(parents=True)
        return
    if not into.is_dir():
        raise ToolTemplateError(f"destination {into} is not a directory")
    unknown = sorted(entry.name for entry in into.iterdir() if entry.name not in SAFE_EXISTING)
    if unknown:
        raise ToolTemplateError(
            f"destination {into} is not empty ({', '.join(unknown[:5])}); refusing to "
            f"overwrite anything. Only these entries are safe: "
            f"{', '.join(sorted(SAFE_EXISTING))}")


def birth_into(p: Params, into: Path, root: Path) -> int:
    """Copy and stamp an indexed skeleton snapshot into a destination, then add a manifest.

    The return value is the number of skeleton files written. Git initialization does not
    happen here because temporary diff regeneration does not need a repository.
    """

    entries = skeleton_entries(root)
    blobs = index_blobs(root, [sha for _rel, _mode, sha in entries])
    ensure_safe_target(into)
    copied = 0
    for rel, mode, sha in entries:
        if any(_match(rel, glob) for glob in PROFILES[p.profile]):
            continue  # layer excluded by the selected profile
        dst = into / stamp(rel, p)
        dst.parent.mkdir(parents=True, exist_ok=True)
        data = blobs[sha]
        try:
            data = stamp(data.decode("utf-8"), p).encode("utf-8")
        except UnicodeDecodeError:
            pass  # binary skeleton files are copied unchanged
        dst.write_bytes(data)
        dst.chmod(0o755 if mode == "100755" else 0o644)
        copied += 1
    write_manifest(into, p)
    return copied


def write_manifest(into: Path, p: Params) -> None:
    """Write birth parameters, tracked globs, and rationale as stable JSON."""

    payload = {
        "template": TEMPLATE_NAME,
        "params": {"tool_name": p.tool_name, "pkg": p.pkg, "profile": p.profile},
        "tracked": [stamp(glob, p) for glob in TRACKED_GLOBS],
        "not_tracked_rationale": NOT_TRACKED_RATIONALE,
    }
    (into / MANIFEST_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_manifest(target: Path) -> Params:
    """Read and validate target parameters without trusting target-owned paths.

    A child manifest is untrusted, manually editable input. Its package value enters
    regeneration paths, so birth-level validation prevents traversal outside the temporary
    directory. Tracked globs come from current code rather than this manifest.
    """

    path = target / MANIFEST_NAME
    if path.is_symlink():
        raise ToolTemplateError(
            f"{MANIFEST_NAME} in {target} is a symlink; the manifest must be a regular "
            "target file")
    if not path.is_file():
        raise ToolTemplateError(
            f"{MANIFEST_NAME} is missing from {target}; was it created by this template?")
    try:
        data = json.loads(path.read_text("utf-8"))
        template = data["template"]
        raw = data["params"]
        params = make_params(raw["tool_name"], raw["profile"], raw["pkg"])
    except ToolTemplateError as error:
        raise ToolTemplateError(f"{MANIFEST_NAME} in {target}: {error}") from error
    except (ValueError, KeyError, TypeError) as error:
        raise ToolTemplateError(f"invalid {MANIFEST_NAME}: {error}") from error
    if template != TEMPLATE_NAME:
        raise ToolTemplateError(
            f"{MANIFEST_NAME}: template={template!r}, expected {TEMPLATE_NAME!r}; "
            "foreign manifest")
    return params


def tracked_set(base: Path, globs: list[str]) -> set[str]:
    """Return relative files under ``base`` that match tracked globs.

    Git metadata and Python or pytest caches are runtime artifacts rather than repository
    product files and are skipped.
    """

    out: set[str] = set()
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(base).parts
        if _SKIP_PARTS.intersection(rel_parts):
            continue
        rel = "/".join(rel_parts)
        if any(_match(rel, glob) for glob in globs):
            out.add(rel)
    return out


def compute_diff(target: Path) -> list[tuple[str, str]]:
    """Return sorted ``(relative path, status)`` entries for a regeneration diff.

    The function detects drift without applying it. A temporary tree is born with the same
    parameters and profile as the target, and selected files are compared byte for byte.
    """

    if not target.is_dir():
        raise ToolTemplateError(f"destination {target} does not exist or is not a directory")
    params = read_manifest(target)
    root = template_root()
    globs = [stamp(glob, params) for glob in TRACKED_GLOBS]
    result: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="tool-template-diff-") as tmp:
        tmp_root = Path(tmp) / "regen"
        birth_into(params, tmp_root, root)
        tmp_set = tracked_set(tmp_root, globs)
        target_set = tracked_set(target, globs)
        for rel in sorted(tmp_set | target_set):
            if rel in tmp_set and rel in target_set:
                same = (tmp_root / rel).read_bytes() == (target / rel).read_bytes()
                result.append((rel, IN_SYNC if same else DRIFTED))
            elif rel in tmp_set:
                result.append((rel, MISSING + " (absent from target)"))
            else:
                result.append((rel, MISSING + " (absent from template)"))
    return result
