"""Generator contract: birth, in-sync diff, drift, missing files, and determinism.

Tests call the CLI main function directly, covering argument parsing and the core. Skeleton
input comes from the template repository's Git index, so tests exercise the committed
snapshot rather than working-tree drafts.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from tooltemplate import core
from tooltemplate.cli import main


def birth(tmp_path: Path, name: str = "tool-x") -> Path:
    into = tmp_path / name
    assert main(["birth", "--name", name, "--into", str(into)]) == 0
    return into


def tree_bytes(root: Path) -> dict[str, bytes]:
    """Map relative paths to bytes, excluding Git metadata that birth does not own."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".git" not in p.relative_to(root).parts:
            out["/".join(p.relative_to(root).parts)] = p.read_bytes()
    return out


def test_template_tests_scrub_external_tools_data():
    """An inherited TOOLS_DATA cannot redirect birth tests into a user's storage."""
    assert "TOOLS_DATA" not in os.environ


def test_birth_then_diff_in_sync(tmp_path, capsys):
    child = birth(tmp_path)
    assert main(["diff", "--target", str(child)]) == 0
    assert "in sync" in capsys.readouterr().out


def test_birth_stamps_everything(tmp_path):
    child = birth(tmp_path)
    snapshot = tree_bytes(child)
    # No placeholder remains in a path or file body.
    for rel, data in snapshot.items():
        assert "{{" not in rel
        assert b"{{" not in data, f"unstamped placeholder in {rel}"
    for rel in ("README.md", "docs/DESIGN.md", "docs/VISION.md", "tool_x/cli.py"):
        assert b"TODO" not in snapshot[rel], f"unfinished domain slot in {rel}"
    # Package path is stamped, the manifest exists, and Git is initialized.
    assert (child / "tool_x" / "cli.py").is_file()
    assert (child / ".tool-manifest.json").is_file()
    assert (child / ".git").is_dir()
    assert "tool-x" in (child / "README.md").read_text("utf-8")


def test_born_deploy_documents_launchd_path(tmp_path):
    child = birth(tmp_path)
    text = (child / "deploy" / "README.md").read_text("utf-8")
    assert "launchd" in text and "nvm-bin" in text and "Python 3.11+" in text


def test_drifted_file_detected(tmp_path, capsys):
    child = birth(tmp_path)
    with open(child / "tool_x" / "shared" / "fs.py", "a", encoding="utf-8") as f:
        f.write("# local fork\n")
    assert main(["diff", "--target", str(child)]) == 1
    out = capsys.readouterr().out
    assert "drifted" in out and "tool_x/shared/fs.py" in out


def test_missing_file_detected(tmp_path, capsys):
    child = birth(tmp_path)
    (child / "docs" / "conventions.md").unlink()
    assert main(["diff", "--target", str(child)]) == 1
    out = capsys.readouterr().out
    assert "missing" in out and "docs/conventions.md" in out


def test_untracked_edit_is_not_drift(tmp_path, capsys):
    """Child-owned content such as README is not template drift."""
    child = birth(tmp_path)
    with open(child / "README.md", "a", encoding="utf-8") as f:
        f.write("\nchild-owned text\n")
    assert main(["diff", "--target", str(child)]) == 0


def test_birth_deterministic(tmp_path):
    a = tree_bytes(birth(tmp_path / "a"))
    b = tree_bytes(birth(tmp_path / "b"))
    assert a == b  # byte identity is what lets stamping cancel in regen-diff


def test_birth_refuses_nonempty_target(tmp_path, capsys):
    into = tmp_path / "busy"
    into.mkdir()
    (into / "foreign.txt").write_text("do not overwrite", "utf-8")
    assert main(["birth", "--name", "tool-x", "--into", str(into)]) == 1
    assert (into / "foreign.txt").read_text("utf-8") == "do not overwrite"


def test_diff_without_manifest_is_operational_error(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert main(["diff", "--target", str(plain)]) == 2  # operational error, not drift


def test_diff_rejects_hostile_manifest(tmp_path, monkeypatch, capsys):
    """A target manifest is untrusted input whose package value enters output paths.

    Without validation, ``../../x`` or an absolute path escapes the regeneration directory
    and makes read-only diff write elsewhere. The temporary root is an empty sandbox;
    TemporaryDirectory removes its own contents, so any remaining entry proves an escape.
    """
    sandbox = tmp_path / "tmpdir"
    sandbox.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(sandbox))
    hostile = ["../../pwned", str(tmp_path / "pwned_abs"), "..", "a/b", "Bad-Pkg", 5]
    for i, pkg in enumerate(hostile):
        target = tmp_path / f"child{i}"
        target.mkdir()
        (target / core.MANIFEST_NAME).write_text(json.dumps(
            {"template": "tool-template", "tracked": [], "not_tracked_rationale": {},
             "params": {"tool_name": "tool-x", "pkg": pkg, "profile": "default"}}), "utf-8")
        assert main(["diff", "--target", str(target)]) == 2, f"pkg={pkg!r} was accepted"
        assert "tooltemplate diff" in capsys.readouterr().err
    assert list(sandbox.rglob("*")) == [], "diff wrote outside its temporary directory"
    assert not (tmp_path / "pwned_abs").exists()
    assert not (tmp_path / "pwned").exists()


def test_diff_rejects_foreign_manifest(tmp_path):
    """A foreign template identity is an operational error, not whole-tree drift."""
    target = tmp_path / "child"
    target.mkdir()
    (target / core.MANIFEST_NAME).write_text(json.dumps(
        {"template": "other-generator",
         "params": {"tool_name": "tool-x", "pkg": "tool_x", "profile": "default"}}), "utf-8")
    assert main(["diff", "--target", str(target)]) == 2


def test_diff_rejects_symlink_manifest(tmp_path, capsys):
    """A symlink manifest cannot make diff read an arbitrary external JSON file."""
    child = birth(tmp_path / "born")
    external = tmp_path / "external-manifest.json"
    manifest = child / core.MANIFEST_NAME
    external.write_bytes(manifest.read_bytes())
    manifest.unlink()
    manifest.symlink_to(external)
    assert main(["diff", "--target", str(child)]) == 2
    assert "symlink" in capsys.readouterr().err


def test_diff_requires_explicit_profile_in_manifest(tmp_path, capsys):
    """A missing profile is invalid schema, never an implicit default."""
    child = birth(tmp_path)
    manifest = child / core.MANIFEST_NAME
    data = json.loads(manifest.read_text("utf-8"))
    del data["params"]["profile"]
    manifest.write_text(json.dumps(data), "utf-8")
    assert main(["diff", "--target", str(child)]) == 2
    assert "profile" in capsys.readouterr().err


def test_birth_pkg_override(tmp_path, capsys):
    """--pkg supports an established import name not derivable from repository name."""
    into = tmp_path / "tool-llm-wiki"
    assert main(["birth", "--name", "tool-llm-wiki", "--into", str(into),
                 "--pkg", "llmwiki"]) == 0
    assert (into / "llmwiki" / "cli.py").is_file()
    manifest = json.loads((into / core.MANIFEST_NAME).read_text("utf-8"))
    assert manifest["params"]["pkg"] == "llmwiki"
    assert "llmwiki/shared/**" in manifest["tracked"]
    assert main(["diff", "--target", str(into)]) == 0
    assert "in sync" in capsys.readouterr().out


def test_birth_bootstraps_tools_data_idempotently(tmp_path, capsys):
    """Birth creates shared and child data directories without changing existing data."""
    data_home = Path.home() / "tools-data" / "x-data"
    assert not data_home.exists()

    first = tmp_path / "first" / "tool-x"
    assert main(["birth", "--name", "tool-x", "--into", str(first)]) == 0
    assert data_home.is_dir()
    assert "data: " + str(data_home) in capsys.readouterr().out

    marker = data_home / "existing.txt"
    marker.write_text("preserve\n", "utf-8")
    second = tmp_path / "second" / "tool-x"
    assert main(["birth", "--name", "tool-x", "--into", str(second)]) == 0
    assert marker.read_text("utf-8") == "preserve\n"


def test_birth_data_home_permission_error_leaves_safe_retry(tmp_path, capsys, monkeypatch):
    """A data-home failure precedes files and Git, allowing the same birth to retry."""
    into = tmp_path / "tool-x"
    data_home = Path.home() / "tools-data" / "x-data"
    real_mkdir = Path.mkdir
    failed = False

    def fail_first_data_home(path, *args, **kwargs):
        nonlocal failed
        if path == data_home and not failed:
            failed = True
            raise PermissionError("HOME unavailable")
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_first_data_home)
    assert main(["birth", "--name", "tool-x", "--into", str(into)]) == 1
    assert "HOME unavailable" in capsys.readouterr().err
    assert into.is_dir() and list(into.iterdir()) == []

    assert main(["birth", "--name", "tool-x", "--into", str(into)]) == 0
    assert (into / core.MANIFEST_NAME).is_file()
    assert (into / ".git").is_dir()
    assert data_home.is_dir()


def test_birth_rejects_bad_pkg(tmp_path, capsys):
    into = tmp_path / "tool-x"
    assert main(["birth", "--name", "tool-x", "--into", str(into),
                 "--pkg", "Bad-Pkg"]) == 1
    assert "not a Python package name" in capsys.readouterr().err


def test_not_tracked_rationale_covers_everything(tmp_path):
    """Every generated file is template-owned or explained by not_tracked_rationale."""
    child = birth(tmp_path)
    manifest = json.loads((child / core.MANIFEST_NAME).read_text("utf-8"))
    globs = list(manifest["tracked"])
    for key in manifest["not_tracked_rationale"]:
        globs += [g.strip().replace("<pkg>", "tool_x") for g in key.split(",")]
    uncovered = [rel for rel in tree_bytes(child)
                 if not any(core._match(rel, g) for g in globs)]
    assert not uncovered, f"files without ownership or rationale: {uncovered}"


def test_child_usage_error_exits_1(tmp_path):
    """An invalid child CLI flag exits 1 rather than argparse's default 2."""
    child = birth(tmp_path)
    proc = subprocess.run([sys.executable, "-m", "tool_x", "--no-such-flag"],
                          cwd=child, capture_output=True, text=True)
    assert proc.returncode == 1, f"rc={proc.returncode}: {proc.stderr}"
    assert "error" in proc.stderr


def test_born_child_uses_tools_data_root_and_override_priority(tmp_path):
    """A generated CLI enforces --home > tool env > TOOLS_DATA precedence."""
    child = birth(tmp_path, "tool-probe")
    tools_data = tmp_path / "common-data"
    default_home = tools_data / "probe-data"
    default_home.mkdir(parents=True)
    child_env = dict(os.environ, TOOLS_DATA=str(tools_data))
    child_env.pop("PROBE_DATA", None)
    proc = subprocess.run([sys.executable, "-m", "tool_probe", "doctor"],
                          cwd=child, env=child_env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "home: " + str(default_home) in proc.stdout

    env_home = tmp_path / "env-data"
    env_home.mkdir()
    child_env["PROBE_DATA"] = str(env_home)
    proc = subprocess.run([sys.executable, "-m", "tool_probe", "doctor"], cwd=child,
                          env=child_env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "home: " + str(env_home) in proc.stdout

    cli_home = tmp_path / "cli-data"
    cli_home.mkdir()
    proc = subprocess.run([sys.executable, "-m", "tool_probe", "--home", str(cli_home),
                           "doctor"], cwd=child, env=child_env,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "home: " + str(cli_home) in proc.stdout


def test_birth_uses_tools_data_root(tmp_path, monkeypatch, capsys):
    """Operational birth creates data home below the selected TOOLS_DATA root."""
    tools_data = tmp_path / "custom-tools-data"
    monkeypatch.setenv("TOOLS_DATA", str(tools_data))
    birth(tmp_path / "born", "tool-probe")
    assert (tools_data / "probe-data").is_dir()
    assert "data: " + str(tools_data / "probe-data") in capsys.readouterr().out


def _fake_template(root: Path, readme: str) -> Path:
    """Build a miniature Git template so tests can alter an index safely."""
    (root / "skeleton" / "docs").mkdir(parents=True)
    (root / "skeleton" / "README.md").write_text(readme, "utf-8")
    (root / "skeleton" / "docs" / "conventions.md").write_text("canonical\n", "utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    return root


def test_birth_takes_content_from_index_not_worktree(tmp_path):
    """An unstaged skeleton edit cannot leak into a child.

    Contents come from the index through git cat-file. Reading the working tree would make
    birth non-reproducible and regeneration compare a child with an unrelated draft.
    """
    root = _fake_template(tmp_path / "fake", "# {{tool_name}}\nfrom index\n")
    worktree = root / "skeleton" / "README.md"
    worktree.write_text("# {{tool_name}}\nworking-tree draft\n", "utf-8")

    child = tmp_path / "child"
    core.birth_into(core.make_params("tool-x"), child, root)
    assert (child / "README.md").read_text("utf-8") == "# tool-x\nfrom index\n"

    # Conversely, git add must make the change arrive; otherwise an implementation that
    # never reads file contents could pass this test.
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    child2 = tmp_path / "child2"
    core.birth_into(core.make_params("tool-x"), child2, root)
    assert "draft" in (child2 / "README.md").read_text("utf-8")


def test_birth_warns_about_changes_outside_index(tmp_path, capsys, monkeypatch):
    """Birth reports an unstaged edit instead of silently excluding it."""
    root = _fake_template(tmp_path / "fake", "# {{tool_name}}\nfrom index\n")
    (root / "skeleton" / "README.md").write_text("# {{tool_name}}\ndraft\n", "utf-8")
    monkeypatch.setattr(core, "template_root", lambda: root)
    assert main(["birth", "--name", "tool-x", "--into", str(tmp_path / "c")]) == 0
    out = capsys.readouterr().out
    assert "changes outside the index" in out and "skeleton/README.md" in out


def test_diff_warns_about_changes_outside_index(tmp_path, capsys, monkeypatch):
    """Diff reports excluded modified and untracked skeleton files.

    The precise category is changes outside the index, not merely modified files.
    """
    root = _fake_template(tmp_path / "fake", "# {{tool_name}}\nfrom index\n")
    monkeypatch.setattr(core, "template_root", lambda: root)
    child = tmp_path / "c"
    assert main(["birth", "--name", "tool-x", "--into", str(child)]) == 0
    capsys.readouterr()

    (root / "skeleton" / "docs" / "conventions.md").write_text("outside-index edit\n", "utf-8")
    (root / "skeleton" / "new_file.py").write_text("x = 1\n", "utf-8")
    assert main(["diff", "--target", str(child)]) == 0  # outside-index edit is not drift
    out = capsys.readouterr().out
    assert "changes outside the index (2)" in out, out
    assert "skeleton/docs/conventions.md" in out and "skeleton/new_file.py" in out


def test_birth_takes_exec_bit_from_index(tmp_path):
    """Executable bits come from the index just like contents.

    The fixture opposes index and working-tree modes in both directions: a script is 100755
    in the index and 644 on disk, while README is 100644 in the index and 755 on disk. An
    implementation reading disk modes fails both halves.
    """
    root = _fake_template(tmp_path / "fake", "# {{tool_name}}\nfrom index\n")
    script = root / "skeleton" / "bin.sh"
    script.write_text("#!/bin/sh\necho {{tool_name}}\n", "utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "update-index", "--chmod=+x", "skeleton/bin.sh"], cwd=root,
                   check=True, capture_output=True)
    script.chmod(0o644)                              # disk non-executable, index executable
    (root / "skeleton" / "README.md").chmod(0o755)   # and the reverse

    modes = dict((rel, mode) for rel, mode, _sha in core.skeleton_entries(root))
    assert modes["bin.sh"] == "100755" and modes["README.md"] == "100644"

    child = tmp_path / "child"
    core.birth_into(core.make_params("tool-x"), child, root)
    assert (child / "bin.sh").stat().st_mode & 0o111, "indexed executable bit was lost"
    assert not (child / "README.md").stat().st_mode & 0o111, "mode came from working tree"


def test_birth_refuses_unmerged_index(tmp_path):
    """An unresolved skeleton merge fails before destination creation.

    An unmerged index holds stages 1/2/3 for one path. Without the guard, incidental blob-ID
    ordering would choose one side and birth a tree that exists in no commit.
    """
    root = _fake_template(tmp_path / "fake", "# {{tool_name}}\nbase\n")
    shas = {}
    for stage, text in ((1, "base\n"), (2, "ours\n"), (3, "theirs\n")):
        proc = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=root, input=text,
                              text=True, capture_output=True, check=True)
        shas[stage] = proc.stdout.strip()
    index_info = "0 " + "0" * 40 + "\tskeleton/README.md\n" + "".join(
        f"100644 {shas[st]} {st}\tskeleton/README.md\n" for st in (1, 2, 3))
    subprocess.run(["git", "update-index", "--index-info"], cwd=root, input=index_info,
                   text=True, capture_output=True, check=True)

    child = tmp_path / "child"
    with pytest.raises(core.ToolTemplateError) as e:
        core.birth_into(core.make_params("tool-x"), child, root)
    assert "stage" in str(e.value) and "unresolved merge" in str(e.value)
    assert not child.exists(), "destination was created before rejection"


def test_parse_index_entries_refuses_duplicate_rel(tmp_path):
    """A duplicate relative path is rejected rather than silently overwritten."""
    dup = "".join(f"100644 {sha * 40} 0\tskeleton/README.md\x00" for sha in "ab")
    with pytest.raises(core.ToolTemplateError) as e:
        core.parse_index_entries(dup)
    assert "duplicate" in str(e.value)


def test_birth_warns_without_git_identity(tmp_path, capsys, monkeypatch):
    """Missing Git identity warns at birth instead of surprising the first commit."""
    # HOME is isolated by conftest. Disable other identity sources that a host may provide.
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    birth(tmp_path)
    assert "Git identity is not configured" in capsys.readouterr().out
