"""Isolate tests from user storage and credentials through temporary HOME and cwd.

A test that reaches the real home directory or writes into the caller's cwd can silently
damage local state. Autouse fixtures enforce hermetic behavior by construction.
"""
import re
import sys
from pathlib import Path

import pytest

# Import the package without installation so tests run from any directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Hide variables declared in .env.sample, including commented examples. Otherwise a real
# credential inherited by a supposedly hermetic test may call a live API and pass only on one
# machine. Remove only explicitly documented names; heuristics across os.environ could break
# unrelated PATH-like variables.
_ENV_VAR_RE = re.compile(r"([A-Z][A-Z0-9_]*)=")


def _env_sample_vars(sample: Path | None = None) -> list[str]:
    """Read variable names from sample lines formatted as ``[# ]NAME= # purpose``."""
    if sample is None:
        sample = Path(__file__).resolve().parents[1] / ".env.sample"
    if not sample.is_file():
        return []
    names = []
    for line in sample.read_text("utf-8").splitlines():
        m = _ENV_VAR_RE.match(line.lstrip("# ").strip())
        if m:
            names.append(m.group(1))
    return names


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    # The underscore avoids collisions with child tests that create tmp_path/"home".
    home = tmp_path / "_isolated_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("TOOLS_DATA", raising=False)
    monkeypatch.chdir(tmp_path)
    for name in _env_sample_vars():
        monkeypatch.delenv(name, raising=False)
