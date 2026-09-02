"""Filesystem primitives for atomic writes and self-ignoring state directories.

Vendored from tool-template and owned by the generated repository.
"""
from __future__ import annotations

import os
from pathlib import Path

# A state directory ignores its own contents in every repository, independently of the root
# .gitignore. ``git add .`` therefore does not capture runtime state.
GITIGNORE_BODY = "# tool runtime state is not part of the repository\n*\n"


def atomic_write(path: str | Path, data: str | bytes, encoding: str = "utf-8") -> None:
    """Write beside the destination and atomically replace it within one filesystem.

    Readers never observe a partially written destination. A crashed writer may leave a
    temporary fragment but does not corrupt the previous complete value.
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if isinstance(data, str):
        tmp.write_text(data, encoding=encoding)
    else:
        tmp.write_bytes(data)
    os.replace(tmp, path)


def ensure_state_dir(path: str | Path) -> Path:
    """Create a self-ignoring state directory idempotently and return its path.

    An existing .gitignore is preserved because the repository owner may have customized
    it. Exclusive creation avoids clobbering a file created by a concurrent process.
    """

    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    gitignore = directory / ".gitignore"
    if not gitignore.exists():
        try:
            with open(gitignore, "x", encoding="utf-8") as file:
                file.write(GITIGNORE_BODY)
        except FileExistsError:
            pass  # another process created it between exists() and open()
    return directory
