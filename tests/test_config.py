"""TOML 설정 로드, 값 검증 및 작업공간 생성을 검증한다."""

import json
from pathlib import Path

import pytest

from cae_agent.config import (
    ConfigError,
    load_config,
    prepare_workspace,
    render_config_json,
)


def test_default_config_uses_safe_values(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)

    assert config.ansys.version == "261"
    assert config.ansys.workbench_port == 50055
    assert config.ansys.headless is False
    assert config.agent.provider == "codex"
    assert config.agent.model is None
    assert config.agent.max_retries == 3
    assert config.agent.timeout_seconds == 300
    assert config.workspace.root == (tmp_path / "workspace").resolve()
    assert config.source_file is None


def test_toml_values_override_defaults(tmp_path: Path) -> None:
    config_file = tmp_path / "custom.toml"
    config_file.write_text(
        """
[ansys]
version = "252"
workbench_port = 50100
headless = true

[agent]
provider = "claude"
max_retries = 5

[workspace]
root = "runs"
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.ansys.version == "252"
    assert config.ansys.workbench_port == 50100
    assert config.ansys.headless is True
    assert config.agent.provider == "claude"
    assert config.agent.max_retries == 5
    assert config.workspace.root == (tmp_path / "runs").resolve()


@pytest.mark.parametrize("port", [0, 65536])
def test_invalid_port_is_rejected(tmp_path: Path, port: int) -> None:
    config_file = tmp_path / "invalid.toml"
    config_file.write_text(
        f"[ansys]\nworkbench_port = {port}",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="workbench_port"):
        load_config(config_file)


def test_boolean_is_not_accepted_as_retry_count(tmp_path: Path) -> None:
    config_file = tmp_path / "invalid.toml"
    config_file.write_text(
        "[agent]\nmax_retries = true",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="max_retries"):
        load_config(config_file)


def test_explicit_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="찾을 수 없습니다"):
        load_config(tmp_path / "missing.toml")


def test_workspace_directories_are_created(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)

    prepare_workspace(config.workspace)

    assert all(path.is_dir() for path in config.workspace.directories())


def test_json_output_contains_resolved_paths(tmp_path: Path) -> None:
    config = load_config(current_directory=tmp_path)

    payload = json.loads(render_config_json(config))

    assert payload["workspace"]["root"] == str(
        (tmp_path / "workspace").resolve()
    )
    assert payload["source_file"] is None
