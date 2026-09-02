"""Check contracts: template self-hosting, clean generated child, and caught violations."""
import importlib.util
import subprocess
import sys
from pathlib import Path

from tooltemplate.cli import main

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]
RUNNER = TEMPLATE_ROOT / "harness" / "run_checks.py"


def run_checks(repo_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RUNNER), "--repo-root", str(repo_root)],
                          capture_output=True, text=True)


def test_self_hosting_template_repo_green():
    proc = run_checks(TEMPLATE_ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # No block check reports a violation.
    assert "violation(s)" not in proc.stdout, proc.stdout


def test_born_child_green(tmp_path):
    child = tmp_path / "tool-x"
    assert main(["birth", "--name", "tool-x", "--into", str(child)]) == 0
    proc = run_checks(child)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_violations_caught(tmp_path):
    """A repository with internal data, a giant file, and no docs fails relevant checks."""
    bad = tmp_path / "bad"
    (bad / "in").mkdir(parents=True)
    (bad / "big.bin").write_bytes(b"\0" * (10 * 1024 * 1024 + 1))
    proc = run_checks(bad)
    assert proc.returncode == 1
    out = proc.stdout
    assert "in/" in out and "big.bin" in out          # data-not-inside
    assert "README.md" in out                          # docs-canon
    assert "LICENSE" in out                            # docs-canon


def test_whitespace_only_doc_is_empty(tmp_path):
    """Whitespace-only documentation is empty according to strip(), not merely size."""
    child = tmp_path / "tool-x"
    assert main(["birth", "--name", "tool-x", "--into", str(child)]) == 0
    (child / "docs" / "DESIGN.md").write_text(" \n\t\n", encoding="utf-8")
    proc = run_checks(child)
    assert proc.returncode == 1
    assert "docs/DESIGN.md" in proc.stdout and "empty" in proc.stdout


def _git_repo(root: Path) -> Path:
    """Create a Git repository because indexed content, not only disk, is under test."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, capture_output=True)
    return root


SECRETS_CHECK = TEMPLATE_ROOT / "harness" / "checks" / "secrets_not_tracked.py"


def secrets_check(repo_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SECRETS_CHECK), "--repo-root", str(repo_root)],
                          capture_output=True, text=True)


def load_secrets_check():
    """Load check constants to compare supported samples with skeleton ignore rules."""
    spec = importlib.util.spec_from_file_location("secrets_not_tracked", SECRETS_CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_secrets_check_catches_tracked_store(tmp_path):
    """A secret-storage filename in the index is a violation by name alone."""
    repo = _git_repo(tmp_path / "repo")
    (repo / ".env").write_text("TOKEN=x\n", "utf-8")
    subprocess.run(["git", "add", "-f", ".env"], cwd=repo, check=True, capture_output=True)
    proc = secrets_check(repo)
    assert proc.returncode == 1 and ".env" in proc.stdout


def test_secrets_check_catches_literal_in_tracked_text(tmp_path):
    """A key literal in an ordinary tracked file is also a violation.

    Concatenation prevents the synthetic literal from appearing in this test source and
    correctly failing template self-hosting.
    """
    repo = _git_repo(tmp_path / "repo")
    (repo / "config.py").write_text("KEY = '" + "sk-" + "A" * 24 + "'\n", "utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    proc = secrets_check(repo)
    assert proc.returncode == 1 and "config.py" in proc.stdout


def test_secrets_check_scans_index_blob_not_worktree(tmp_path):
    """The check reads the future commit from the index, not only the working tree.

    A staged secret remains commit-bound after the disk copy is cleaned or removed. An
    implementation that scans only disk would incorrectly pass this mutation.
    """
    repo = _git_repo(tmp_path / "repo")
    (repo / "config.py").write_text("KEY = '" + "sk-" + "B" * 24 + "'\n", "utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)

    (repo / "config.py").write_text("KEY = os.environ['KEY']\n", "utf-8")  # disk only is clean
    proc = secrets_check(repo)
    assert proc.returncode == 1, proc.stdout
    assert "config.py" in proc.stdout and "source: index" in proc.stdout

    (repo / "config.py").unlink()  # removed from disk but still present in the index
    proc = secrets_check(repo)
    assert proc.returncode == 1 and "config.py" in proc.stdout, proc.stdout


def test_secrets_check_scans_env_sample_from_index(tmp_path):
    """A staged sample value remains a failure after only the disk copy is cleaned."""
    repo = _git_repo(tmp_path / "repo")
    (repo / ".env.sample").write_text("# docs\nAPI_KEY=populated-value\n", "utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    (repo / ".env.sample").write_text("# docs\nAPI_KEY=\n", "utf-8")
    proc = secrets_check(repo)
    assert proc.returncode == 1, proc.stdout
    assert "contains a value" in proc.stdout and "(index)" in proc.stdout


def test_secrets_check_fails_closed_on_truncated_cat_file_batch(tmp_path, monkeypatch, capsys):
    """Truncated batch output becomes a violation instead of silently skipping a blob."""
    repo = _git_repo(tmp_path / "repo")
    (repo / "config.py").write_text("safe = True\n", "utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    mod = load_secrets_check()
    real_run = mod.subprocess.run

    def truncated_batch(args, **kwargs):
        if args[-1] == "--batch":
            sha = kwargs["input"].decode().splitlines()[0]
            return subprocess.CompletedProcess(args, 0, f"{sha} blob 10\nabc".encode(), b"")
        return real_run(args, **kwargs)

    monkeypatch.setattr(mod.subprocess, "run", truncated_batch)
    assert mod.main(["--repo-root", str(repo)]) == 1
    out = capsys.readouterr().out
    assert ".git/index" in out and "failing closed" in out, out


def test_secrets_check_catches_value_in_env_sample_and_unignored_store(tmp_path):
    """A sample value and an unignored neighboring .env are both violations."""
    repo = _git_repo(tmp_path / "repo")
    (repo / ".env.sample").write_text("# docs\nAPI_KEY=populated-value\n", "utf-8")
    (repo / ".env").write_text("API_KEY=x\n", "utf-8")
    proc = secrets_check(repo)
    assert proc.returncode == 1
    assert "contains a value" in proc.stdout and "not ignored" in proc.stdout


def test_secrets_check_covers_window_up_to_data_boundary(tmp_path):
    """Secret and data checks leave no unscanned size window below 10 MiB.

    A 2 MiB tracked JSON value once passed both checks when secret scanning stopped at
    1 MiB and large-data blocking began at 10 MiB.
    """
    repo = _git_repo(tmp_path / "repo")
    (repo / "dump.json").write_text('{"filler": "' + "x" * (2 * 1024 * 1024)
                                    + '", "t": "' + "xoxb-" + "9" * 24 + '"}\n', "utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    proc = secrets_check(repo)
    assert proc.returncode == 1 and "dump.json" in proc.stdout, proc.stdout


def test_secrets_check_hands_over_giants_to_data_check(tmp_path):
    """Above the scan boundary, indexed blob size is blocked by data-not-inside.

    Removing a working copy after staging does not change the future commit.
    """
    repo = _git_repo(tmp_path / "repo")
    (repo / "huge.bin").write_bytes(b"x" * (11 * 1024 * 1024))
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    (repo / "huge.bin").unlink()
    assert secrets_check(repo).returncode == 0
    proc = run_checks(repo)
    assert proc.returncode == 1 and "huge.bin" in proc.stdout, proc.stdout
    assert "indexed blob is 11.0 MiB" in proc.stdout, proc.stdout


def test_secrets_check_catches_any_assignment_form_in_sample(tmp_path):
    """Sample checks catch export, lowercase names, and whitespace around assignments."""
    repo = _git_repo(tmp_path / "repo")
    (repo / ".env.sample").write_text(
        "# docs\n"
        "export API_KEY=value\n"
        "api_key=value\n"
        "OTHER_KEY = value\n"
        "CLEAN_KEY=   # valid: name and purpose only\n", "utf-8")
    proc = secrets_check(repo)
    assert proc.returncode == 1, proc.stdout
    for var in ("API_KEY", "api_key", "OTHER_KEY"):
        assert var in proc.stdout, proc.stdout
    assert "CLEAN_KEY" not in proc.stdout


def test_secrets_check_pem_blocks_private_key_not_certificate(tmp_path):
    """A PEM filename is legal until its content contains a private-key header."""
    repo = _git_repo(tmp_path / "repo")
    cert = "-----BEGIN CERTIFICATE-----\nMIIBpublic\n-----END CERTIFICATE-----\n"
    public_key = "-----BEGIN PUBLIC KEY-----\nMIIBpublic\n-----END PUBLIC KEY-----\n"
    (repo / "fullchain.pem").write_text(cert, "utf-8")
    (repo / "ca-bundle.pem").write_text(cert, "utf-8")
    (repo / "public-key.pem").write_text(public_key, "utf-8")
    (repo / "keyboard.pem").write_text("not a key\n", "utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    assert secrets_check(repo).returncode == 0, secrets_check(repo).stdout

    (repo / "public-key.pem").write_text("-----BEGIN RSA PRIVATE" + " KEY-----\nx\n", "utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    proc = secrets_check(repo)
    assert proc.returncode == 1 and "public-key.pem" in proc.stdout, proc.stdout

    # Concatenation keeps the complete private header out of this self-hosted test source.
    (repo / "public-key.pem").write_text(public_key, "utf-8")
    (repo / "fullchain.pem").write_text("-----BEGIN RSA PRIVATE" + " KEY-----\nx\n", "utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    proc = secrets_check(repo)
    assert proc.returncode == 1 and "fullchain.pem" in proc.stdout, proc.stdout

    (repo / "fullchain.pem").write_text(cert, "utf-8")
    (repo / "untracked-key.pem").write_text(
        "-----BEGIN RSA PRIVATE" + " KEY-----\nx\n", "utf-8")
    proc = secrets_check(repo)
    assert proc.returncode == 1 and "untracked-key.pem" in proc.stdout, proc.stdout


def test_born_child_does_not_ignore_sample_names(tmp_path):
    """Every supported sample filename remains trackable under skeleton ignore rules."""
    child = tmp_path / "tool-x"
    assert main(["birth", "--name", "tool-x", "--into", str(child)]) == 0
    for name in load_secrets_check().SAMPLE_NAMES:
        proc = subprocess.run(["git", "check-ignore", "--no-index", "-q", name],
                              cwd=child, capture_output=True)
        assert proc.returncode == 1, f"{name} is ignored by the skeleton .gitignore"


def test_secrets_check_green_on_born_child(tmp_path):
    """A generated child has an empty sample and ignores a real .env."""
    child = tmp_path / "tool-x"
    assert main(["birth", "--name", "tool-x", "--into", str(child)]) == 0
    (child / ".env").write_text("API_KEY=x\n", "utf-8")  # real local file is ignored
    proc = secrets_check(child)
    assert proc.returncode == 0, proc.stdout


def env_check(repo_root: Path) -> subprocess.CompletedProcess:
    check = TEMPLATE_ROOT / "harness" / "checks" / "env_ignored.py"
    return subprocess.run([sys.executable, str(check), "--repo-root", str(repo_root)],
                          capture_output=True, text=True)


def test_env_ignore_check_green_on_born_child(tmp_path):
    """Skeleton rules ignore .env while keeping samples trackable."""
    child = tmp_path / "tool-x"
    assert main(["birth", "--name", "tool-x", "--into", str(child)]) == 0
    proc = env_check(child)
    assert proc.returncode == 0, proc.stdout


def test_env_ignore_check_blocks_repo(tmp_path):
    """A missing ignore rule fails even before any .env exists on disk."""
    child = tmp_path / "tool-x"
    assert main(["birth", "--name", "tool-x", "--into", str(child)]) == 0
    (child / ".gitignore").write_text("__pycache__/\n", "utf-8")  # remove env rules
    assert not (child / ".env").exists()

    proc = env_check(child)
    assert proc.returncode == 1 and ".env is not ignored" in proc.stdout, proc.stdout
    assert secrets_check(child).returncode == 0  # secret check sees facts, this sees exposure

    proc = run_checks(child)
    assert proc.returncode == 1, proc.stdout
    assert "repo/env-ignored" in proc.stdout and "[  block]" in proc.stdout


def test_env_ignore_check_wants_samples_tracked(tmp_path):
    """A sample hidden by ignore rules is also a violation."""
    child = tmp_path / "tool-x"
    assert main(["birth", "--name", "tool-x", "--into", str(child)]) == 0
    (child / ".gitignore").write_text(".env\n.env.*\n", "utf-8")  # omit exceptions
    proc = env_check(child)
    assert proc.returncode == 1
    assert ".env.sample is ignored" in proc.stdout and ".env.example" in proc.stdout


def test_env_ignore_check_requires_repo_gitignore_source(tmp_path):
    """Machine-local info/exclude and global excludes do not protect a clone."""
    repo = _git_repo(tmp_path / "repo")
    info_exclude = repo / ".git" / "info" / "exclude"
    info_exclude.write_text(".env\n.env.local\n", "utf-8")
    proc = env_check(repo)
    assert proc.returncode == 1 and ".git/info/exclude" in proc.stdout, proc.stdout

    info_exclude.write_text("", "utf-8")
    global_excludes = tmp_path / "global-ignore"
    global_excludes.write_text(".env\n.env.local\n", "utf-8")
    subprocess.run(["git", "config", "core.excludesFile", str(global_excludes)], cwd=repo,
                   check=True, capture_output=True)
    proc = env_check(repo)
    assert proc.returncode == 1 and str(global_excludes) in proc.stdout, proc.stdout


def test_env_ignore_check_fails_closed_on_git_error(tmp_path):
    """A non-Git directory makes check-ignore fail and must not become a false success."""
    root = tmp_path / "not-a-repo"
    root.mkdir()
    proc = env_check(root)
    assert proc.returncode == 1, proc.stdout
    assert "git check-ignore failed" in proc.stdout and "failing closed" in proc.stdout


def test_local_child_check_discovered(tmp_path):
    """Discovery finds a child-local check and enforces its block mode."""
    child = tmp_path / "tool-x"
    assert main(["birth", "--name", "tool-x", "--into", str(child)]) == 0
    local = child / "harness" / "checks" / "always_red.py"
    local.write_text(
        '#!/usr/bin/env python3\n'
        '# tool-check\n'
        '# id: tool-x/always-red\n'
        '# mode: block\n'
        'import json\n'
        'print(json.dumps({"id": "tool-x/always-red", "ok": False,\n'
        '                  "violations": [{"file": "", "msg": "deliberate failure"}]}))\n',
        encoding="utf-8")
    proc = run_checks(child)
    assert proc.returncode == 1
    assert "tool-x/always-red" in proc.stdout
