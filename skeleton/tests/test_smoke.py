"""CLI smoke tests: doctor is non-mutating and an invalid flag exits 1.

Live provider runs belong under smoke/ where exit 77 means skipped.
"""
import os
from pathlib import Path

import pytest
from conftest import _env_sample_vars

from {{pkg}}.cli import DATA_ENV, EXIT_FAIL, EXIT_OK, main


def test_tests_scrub_external_tools_data():
    """Inherited TOOLS_DATA cannot redirect tests into user storage."""
    assert "TOOLS_DATA" not in os.environ


def test_doctor_ok(tmp_path, capsys):
    # An empty home is valid only while the scaffold has no required domain configuration.
    # Replace this expectation when the real tool introduces mandatory files.
    home = tmp_path / "data"
    home.mkdir()
    assert main(["--home", str(home), "doctor"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "doctor" in out
    assert "shared config:" in out
    assert "exists=false valid=- error=false" in out


def test_doctor_uses_tools_data_default_and_env_override(tmp_path, monkeypatch, capsys):
    """Resolution is CLI, tool env, TOOLS_DATA, then fallback; never cwd."""
    assert DATA_ENV == "{{data_env}}"
    monkeypatch.delenv(DATA_ENV, raising=False)
    monkeypatch.delenv("TOOLS_DATA", raising=False)
    default_home = Path.home() / "tools-data" / "{{data_dir}}"
    default_home.mkdir(parents=True)
    assert main(["doctor"]) == EXIT_OK
    assert "home: " + str(default_home) in capsys.readouterr().out

    env_home = tmp_path / "from-env"
    env_home.mkdir()
    monkeypatch.setenv(DATA_ENV, str(env_home))
    assert main(["doctor"]) == EXIT_OK
    assert "home: " + str(env_home) in capsys.readouterr().out

    cli_home = tmp_path / "from-cli"
    cli_home.mkdir()
    assert main(["--home", str(cli_home), "doctor"]) == EXIT_OK
    assert "home: " + str(cli_home) in capsys.readouterr().out

    tools_data = tmp_path / "shared-root"
    (tools_data / "{{data_dir}}").mkdir(parents=True)
    monkeypatch.delenv(DATA_ENV, raising=False)
    monkeypatch.setenv("TOOLS_DATA", str(tools_data))
    assert main(["doctor"]) == EXIT_OK
    assert "home: " + str(tools_data / "{{data_dir}}") in capsys.readouterr().out


def test_doctor_missing_home_fails_and_does_not_create(tmp_path, capsys):
    home = tmp_path / "no-such-home"
    assert main(["--home", str(home), "doctor"]) == EXIT_FAIL
    assert not home.exists()  # doctor diagnoses without mutation


def test_usage_error_exits_1(capsys):
    """Invalid usage exits 1 rather than argparse's default 2."""
    with pytest.raises(SystemExit) as e:
        main(["doctor", "--no-such-flag"])
    assert e.value.code == EXIT_FAIL
    assert "error" in capsys.readouterr().err


def test_env_sample_creds_scrubbed(tmp_path):
    """The conftest isolator removes every variable declared in .env.sample."""
    # Header prose does not match the ``[# ]NAME= # purpose`` line format.
    sample = tmp_path / ".env.sample"
    sample.write_text("# prose header: NAME=\n# FOO_TOKEN=   # credential\nBAR_KEY=x\n", "utf-8")
    assert _env_sample_vars(sample) == ["FOO_TOKEN", "BAR_KEY"]
    # Actual effect: no repository sample variable is visible to the test.
    leaked = [n for n in _env_sample_vars() if n in os.environ]
    assert not leaked, f"sample credentials are visible to the test: {leaked}"
