"""Exercise shared tools-data/config.toml through code from a generated child."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from tooltemplate.cli import main

TEMPLATE_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def config_module(tmp_path_factory):
    fixture_root = tmp_path_factory.mktemp("born-config")
    child = fixture_root / "tool-x"
    home = fixture_root / "home"
    home.mkdir()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("TOOLS_DATA", raising=False)
    try:
        assert main(["birth", "--name", "tool-x", "--into", str(child)]) == 0
    finally:
        monkeypatch.undo()
    path = child / "tool_x" / "shared" / "config.py"
    spec = importlib.util.spec_from_file_location("born_shared.config", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop(spec.name, None)


def write_config(root: Path, text: str) -> Path:
    root.mkdir()
    path = root / "config.toml"
    path.write_text(text, "utf-8")
    return path


def test_common_config_valid(config_module, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "tools-data"
    path = write_config(root, """
schema_version = 1

[paths]
vault = "~/life-os-vault"
topics_root = "/data/topics"
sources_root = "/data/sources"

[harness.claude]
argv = ["claude"]
model_default = "sonnet"

[harness.codex]
argv = ["codex", "exec"]
effort_default = "high"

[tools.researcher]
argv = ["python3", "-m", "researcher"]
cwd = "~/tools-workspace/tool-researcher"
env = ["OPENAI_API_KEY"]
""")
    config = config_module.load_common_config(root)
    assert config.path == path and config.exists and config.schema_version == 1
    assert config.paths.vault == Path.home() / "life-os-vault"
    assert config.paths.topics_root == Path("/data/topics")
    assert [item.name for item in config.harnesses] == ["claude", "codex"]
    assert config.harnesses[0].model_default == "sonnet"
    assert config.tools[0].argv == ("python3", "-m", "researcher")
    assert config.tools[0].cwd == Path.home() / "tools-workspace" / "tool-researcher"
    assert config.tools[0].env_names == ("OPENAI_API_KEY",)
    assert config.tool("researcher") is config.tools[0]
    assert config.tool("missing") is None


def test_deploy_example_matches_schema(config_module, tmp_path):
    example = TEMPLATE_ROOT / "deploy" / "config.example.toml"
    config_path = tmp_path / "config.toml"
    config_path.write_bytes(example.read_bytes())
    config = config_module.load_common_config(tmp_path)
    assert config.exists and config.path == config_path
    assert [item.name for item in config.harnesses] == ["claude", "codex"]
    assert [item.name for item in config.tools] == [
        "coursedump", "gateway", "lifeos", "llmwiki", "researcher", "scheduler"]
    coursedump = next(item for item in config.tools if item.name == "coursedump")
    assert coursedump.argv == ("uv", "run", "coursedump")


def test_deploy_example_documents_launchd_path():
    example = TEMPLATE_ROOT / "deploy" / "config.example.toml"
    text = example.read_text("utf-8")
    assert "launchd" in text and "nvm-bin" in text and "Python 3.11+" in text


def test_common_config_rejects_unknown_key(config_module, tmp_path):
    root = tmp_path / "tools-data"
    path = write_config(root, """
schema_version = 1
[paths]
vault = "/vault"
topics_root = "/topics"
sources_root = "/sources"
[tools.researcher]
argv = ["researcher"]
secret_value = "forbidden"
""")
    with pytest.raises(config_module.CommonConfigError) as error:
        config_module.load_common_config(root)
    assert str(path) in str(error.value)
    assert "tools.researcher" in str(error.value) and "secret_value" in str(error.value)


def test_common_config_rejects_broken_toml(config_module, tmp_path):
    root = tmp_path / "tools-data"
    path = write_config(root, "schema_version = [\n")
    with pytest.raises(config_module.CommonConfigError) as error:
        config_module.load_common_config(root)
    assert str(path) in str(error.value) and "TOML" in str(error.value)


@pytest.mark.parametrize(("paths", "tool", "key"), [
    (("vault", "relative/vault"), None, "paths.vault"),
    (None, ("cwd", "relative/repo"), "tools.researcher.cwd"),
])
def test_common_config_rejects_relative_paths(
        config_module, tmp_path, paths, tool, key):
    values = {
        "vault": "/vault",
        "topics_root": "/topics",
        "sources_root": "/sources",
    }
    if paths:
        values[paths[0]] = paths[1]
    tool_cwd = f'cwd = "{tool[1]}"\n' if tool else ""
    root = tmp_path / "tools-data"
    path = write_config(root, f"""
schema_version = 1
[paths]
vault = "{values['vault']}"
topics_root = "{values['topics_root']}"
sources_root = "{values['sources_root']}"
[tools.researcher]
argv = ["researcher"]
{tool_cwd}""")
    with pytest.raises(config_module.CommonConfigError) as error:
        config_module.load_common_config(root)
    assert str(path) in str(error.value)
    assert key in str(error.value) and "absolute" in str(error.value)


def test_common_config_rejects_env_values(config_module, tmp_path):
    root = tmp_path / "tools-data"
    path = write_config(root, """
schema_version = 1
[paths]
vault = "/vault"
topics_root = "/topics"
sources_root = "/sources"
[tools.researcher]
argv = ["researcher"]
env = ["TOKEN=very-secret-value"]
""")
    with pytest.raises(config_module.CommonConfigError) as error:
        config_module.load_common_config(root)
    message = str(error.value)
    assert str(path) in message and "tools.researcher.env[0]" in message


def test_common_config_env_error_does_not_echo_value(config_module, tmp_path):
    root = tmp_path / "tools-data"
    write_config(root, """
schema_version = 1
[paths]
vault = "/vault"
topics_root = "/topics"
sources_root = "/sources"
[tools.researcher]
argv = ["researcher"]
env = ["TOKEN=very-secret-value"]
""")
    with pytest.raises(config_module.CommonConfigError) as error:
        config_module.load_common_config(root)
    message = str(error.value)
    assert "tools.researcher.env[0]" in message
    assert "very-secret-value" not in message


@pytest.mark.parametrize("version", ["2", '"1"'])
def test_common_config_rejects_wrong_schema_version(
        config_module, tmp_path, version):
    root = tmp_path / "tools-data"
    path = write_config(root, f"""
schema_version = {version}
[paths]
vault = "/vault"
topics_root = "/topics"
sources_root = "/sources"
""")
    with pytest.raises(config_module.CommonConfigError) as error:
        config_module.load_common_config(root)
    message = str(error.value)
    assert str(path) in message and "schema_version" in message
    assert "integer 1" in message


def test_common_config_missing_is_explicit(config_module, tmp_path):
    root = tmp_path / "no-tools-data"
    config = config_module.load_common_config(root)
    assert config.path == root / "config.toml"
    assert config.exists is False
    assert config.schema_version is None and config.paths is None
    assert config.harnesses == () and config.tools == ()


def test_tools_data_root_uses_env(config_module, tmp_path, monkeypatch):
    custom = tmp_path / "custom"
    monkeypatch.setenv("TOOLS_DATA", str(custom))
    assert config_module.tools_data_root() == custom
    assert config_module.load_common_config().path == custom / "config.toml"


def test_doctor_reports_common_config_status(config_module, tmp_path, monkeypatch, capsys):
    tools_data = tmp_path / "tools-data"
    home = tools_data / "x-data"
    home.mkdir(parents=True)
    monkeypatch.setenv("TOOLS_DATA", str(tools_data))

    child_root = Path(config_module.__file__).parents[2]
    sys.path.insert(0, str(child_root))
    try:
        from tool_x.cli import doctor

        assert doctor(home) == 0
        missing = capsys.readouterr().out
        assert ("shared config: path=" + str(tools_data / "config.toml")
                + " exists=false valid=- error=false") in missing

        (tools_data / "config.toml").write_text("""
schema_version = 1
[paths]
vault = "/vault"
topics_root = "/topics"
sources_root = "/sources"
[tools.researcher]
argv = ["researcher"]
env = ["TOKEN=doctor-secret-value"]
""", "utf-8")
        assert doctor(home) == 1
        broken = capsys.readouterr().out
        assert "exists=true valid=false error=true" in broken
        assert str(tools_data / "config.toml") in broken
        assert "tools.researcher.env[0]" in broken
        assert "expected an environment name, not a value" in broken
        assert "doctor-secret-value" not in broken

        (tools_data / "config.toml").write_text("""
schema_version = 1
[paths]
vault = "/vault"
topics_root = "/topics"
sources_root = "/sources"
""", "utf-8")
        assert doctor(home) == 0
        valid = capsys.readouterr().out
        assert "exists=true valid=true error=false" in valid
    finally:
        sys.path.remove(str(child_root))
        for name in [key for key in sys.modules if key == "tool_x" or key.startswith("tool_x.")]:
            sys.modules.pop(name, None)
