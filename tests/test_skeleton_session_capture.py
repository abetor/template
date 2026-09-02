"""Regression coverage for session capture in a generated child."""
from __future__ import annotations

import subprocess
import sys

from tooltemplate.cli import main


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def test_capture_separates_blocks_without_blank_line_at_eof(tmp_path):
    child = tmp_path / "tool-x"
    assert main(["birth", "--name", "tool-x", "--into", str(child)]) == 0
    sys.path.insert(0, str(child))
    try:
        from tool_x.shared.session_capture import capture
    finally:
        sys.path.remove(str(child))

    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("one\n", "utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "--quiet", "-m", "first")

    journal = capture(tmp_path)
    assert journal is not None
    assert journal.read_text("utf-8").endswith("\n")
    assert not journal.read_text("utf-8").endswith("\n\n")

    tracked.write_text("two\n", "utf-8")
    capture(tmp_path)
    text = journal.read_text("utf-8")
    assert "\n\n## " in text
    assert not text.endswith("\n\n")
