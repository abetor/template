"""Isolate tests from user storage by redirecting HOME and cwd to temporary paths.

The generator locates its template from the package rather than cwd, so changing cwd is safe
and all children created by tests remain below tmp_path.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("TOOLS_DATA", raising=False)
    monkeypatch.chdir(tmp_path)
